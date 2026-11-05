"""Local drafts, exact reviews and transactionally consumed dry-run permissions.

There is deliberately no sender. A receipt records one local simulation only.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from .database import ApplicationDatabase
from .models import ApplicationRecord, EvaluationResult, JobPosting
from .migrations import legacy_identity
from .sources.models import NormalizedJob
from .workflow_contracts import (
    WorkflowError, canonical_json, content_digest, require_dry_run,
    vacancy_digest, vacancy_key,
)

_HASH = re.compile(r'[0-9a-f]{64}\Z')
_AUTHORIZATION = re.compile(r'[0-9a-f]{32}\Z')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identifier(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise WorkflowError('invalid_candidacy_identifier')
    return value


def _hash(value: Any) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise WorkflowError('invalid_content_hash')
    return value


def _content(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 1_000_000 or '\x00' in value:
        raise WorkflowError('invalid_draft_content')
    return value


class CandidacyWorkflow:
    def __init__(self, database: ApplicationDatabase, resumes: object) -> None:
        if not callable(getattr(resumes, 'verify_version', None)):
            raise WorkflowError('resume_verifier_required')
        self.database = database
        self.resumes = resumes

    @staticmethod
    def _row(connection: sqlite3.Connection, candidacy_id: int) -> sqlite3.Row:
        row = connection.execute('SELECT * FROM candidacies WHERE id=?',
                                 (_identifier(candidacy_id),)).fetchone()
        if row is None:
            raise WorkflowError('unknown_candidacy')
        return row

    @staticmethod
    def _vacancy(connection: sqlite3.Connection, vacancy_id: int) -> NormalizedJob:
        row = connection.execute('SELECT * FROM vacancies WHERE id=?',
                                 (_identifier(vacancy_id),)).fetchone()
        if row is None:
            raise WorkflowError('unknown_vacancy')
        try:
            payload = json.loads(row['job_json'])
            job = NormalizedJob(**payload)
            if ([row['source'], row['source_board'], row['source_job_id']] != vacancy_key(job)
                    or not all(isinstance(item, str) and item for item in vacancy_key(job))
                    or not isinstance(job.company, str) or not job.company.strip()
                    or not isinstance(job.locations, list)
                    or not all(isinstance(item, str) for item in job.locations)
                    or not isinstance(job.provenance, dict)
                    or not isinstance(job.eligibility_evidence, dict)):
                raise ValueError()
            for name in ('title', 'url', 'description', 'published_at'):
                value = getattr(job, name)
                if value is not None and not isinstance(value, str):
                    raise ValueError()
            for name in ('work_mode', 'retrieved_at', 'verification_status'):
                if not isinstance(getattr(job, name), str):
                    raise ValueError()
            canonical_json(payload)
            return job
        except (TypeError, ValueError, KeyError):
            raise WorkflowError('invalid_vacancy_snapshot') from None

    def _resume(self, version_id: str, job: NormalizedJob) -> dict[str, Any]:
        _hash(version_id)
        try:
            metadata = self.resumes.verify_version(version_id)
            if not isinstance(metadata, dict) or metadata.get('version_id') != version_id:
                raise ValueError()
            for key in ('version_id', 'master_id', 'sha256', 'vacancy_digest'):
                _hash(metadata[key])
            if metadata['language'] not in ('es', 'en') or metadata['format'] not in ('txt', 'docx'):
                raise ValueError()
            for key in ('text', 'candidate_name', 'created_at'):
                if not isinstance(metadata[key], str):
                    raise ValueError()
            datetime.fromisoformat(metadata['created_at'].replace('Z', '+00:00'))
            claims = metadata['claim_ids']
            if (not isinstance(claims, list) or not all(isinstance(item, str) and item for item in claims)
                    or len(set(claims)) != len(claims)):
                raise ValueError()
            if (metadata['vacancy_key'] != vacancy_key(job)
                    or metadata['vacancy_digest'] != vacancy_digest(job)):
                raise WorkflowError('resume_vacancy_mismatch')
            # Detach the verifier's object and reject non-JSON metadata/NaN.
            return json.loads(canonical_json(metadata))
        except Exception:
            # Verifiers may report filesystem errors containing private paths.
            raise WorkflowError('resume_integrity_failed') from None

    @staticmethod
    def _snapshot(candidacy: sqlite3.Row, job: NormalizedJob,
                  resume: dict[str, Any]) -> dict[str, Any]:
        return {'candidacy_id': int(candidacy['id']),
                'application_id': int(candidacy['application_id']),
                'vacancy_id': int(candidacy['vacancy_id']),
                'revision': int(candidacy['revision']),
                'company': candidacy['company'],
                'vacancy_key': vacancy_key(job), 'vacancy_digest': vacancy_digest(job),
                'vacancy': asdict(job), 'resume_version_id': candidacy['resume_version_id'],
                'resume': resume, 'content': candidacy['content']}

    def _critical(self, connection: sqlite3.Connection, candidacy: sqlite3.Row) -> dict[str, Any]:
        """Verify current bindings; persist revocation even when raising.

        Callers reserve the SQLite writer before checking files. It serializes
        edits, review and consumption; document verification is repeated here.
        """
        try:
            revision = connection.execute('''
                SELECT snapshot_json FROM candidacy_revisions WHERE candidacy_id=? AND revision=?
            ''', (candidacy['id'], candidacy['revision'])).fetchone()
            if revision is None:
                raise ValueError()
            stored = json.loads(revision['snapshot_json'])
            job = self._vacancy(connection, candidacy['vacancy_id'])
            metadata = self._resume(candidacy['resume_version_id'], job)
            current = self._snapshot(candidacy, job, metadata)
            # A refreshed observation is the one field excluded from approval.
            current['vacancy']['retrieved_at'] = stored['vacancy']['retrieved_at']
            if canonical_json(current) != canonical_json(stored) or job.company != candidacy['company']:
                raise ValueError()
            return stored
        except Exception:
            self.database._invalidate_candidacy(connection, candidacy, 'integrity_failed')
            connection.commit()
            raise WorkflowError('candidacy_integrity_failed') from None

    @staticmethod
    def _trackable(connection: sqlite3.Connection, candidacy: sqlite3.Row) -> None:
        row = connection.execute('SELECT status FROM applications WHERE id=?',
                                 (candidacy['application_id'],)).fetchone()
        if row is None or row['status'] not in ('saved', 'interested'):
            raise WorkflowError('tracker_blocks_authorization')

    def create(self, vacancy_id: int, resume_version_id: str, content: str | None) -> int:
        require_dry_run()
        _identifier(vacancy_id)
        _hash(resume_version_id)
        if content is not None:
            _content(content)
        with self.database._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            existing = connection.execute('SELECT * FROM candidacies WHERE vacancy_id=?',
                                          (vacancy_id,)).fetchone()
            if existing:
                self._critical(connection, existing)
                return int(existing['id'])
            job = self._vacancy(connection, vacancy_id)
            identity = legacy_identity(job.url or '', job.company, job.title or 'Untitled role')
            application = connection.execute("""
                SELECT a.* FROM applications a JOIN application_identities i ON i.application_id=a.id
                WHERE i.identity=?
            """, (identity,)).fetchone()
            if application:
                managed = connection.execute('SELECT * FROM candidacies WHERE application_id=?',
                                             (application['id'],)).fetchone()
                if managed:
                    # Check the existing binding before touching any requested
                    # CV, including a source alias of the managed application.
                    self._critical(connection, managed)
                    raise WorkflowError('application_already_managed')
                if (self._job_values(job) != tuple(application[key] for key in (
                        'title', 'company', 'location', 'url', 'description'))
                        and application['status'] not in ('saved', 'interested')):
                    raise WorkflowError('historical_application_conflict')
            metadata = self._resume(resume_version_id, job)
            if content is None:
                from .drafts import build_draft
                content = _content(build_draft(job, metadata))
            record = ApplicationRecord(None, JobPosting(
                title=job.title or 'Untitled role', company=job.company,
                location=', '.join(job.locations), url=job.url or '',
                description=job.description or ''),
                EvaluationResult(0, 'insufficient_information', algorithm_version='unevaluated'))
            application_id = self.database._add_on_connection(connection, record)
            timestamp = _now()
            cursor = connection.execute('''
                INSERT INTO candidacies(application_id, vacancy_id, resume_version_id,
                    workflow_state, revision, content, company, created_at, updated_at)
                VALUES (?, ?, ?, 'draft', 1, ?, ?, ?, ?)
            ''', (application_id, vacancy_id, resume_version_id, content, job.company, timestamp, timestamp))
            candidacy_id = int(cursor.lastrowid)
            candidacy = self._row(connection, candidacy_id)
            if application:
                self._adopt_application(connection, candidacy, application, job)
            snapshot = self._snapshot(candidacy, job, metadata)
            connection.execute('''
                INSERT INTO candidacy_revisions(candidacy_id, revision, snapshot_json, created_at)
                VALUES (?, 1, ?, ?)
            ''', (candidacy_id, canonical_json(snapshot), timestamp))
            self.database._event(connection, candidacy, 'created', snapshot)
            return candidacy_id

    @staticmethod
    def _job_values(job: NormalizedJob) -> tuple[str, ...]:
        return (job.title or 'Untitled role', job.company, ', '.join(job.locations),
                job.url or '', job.description or '')

    def _adopt_application(self, connection: sqlite3.Connection, candidacy: sqlite3.Row,
                           application: sqlite3.Row, job: NormalizedJob) -> None:
        values = self._job_values(job)
        if values == tuple(application[key] for key in ('title', 'company', 'location', 'url', 'description')):
            return
        pending = EvaluationResult(0, 'insufficient_information', algorithm_version='unevaluated')
        self.database._event(connection, candidacy, 'application_snapshot_preserved', {
            'reason': 'legacy_adoption', 'application': dict(application),
            'target_vacancy_id': candidacy['vacancy_id'], 'target_vacancy': asdict(job),
            'target_evaluation': pending.to_dict(),
        })
        # Preserve IDs, notes, status and both historical tracker dates. The
        # candidacy/event timestamps separately record the explicit adoption.
        connection.execute("""
            UPDATE applications SET title=?, company=?, location=?, url=?, description=?,
                score=?, recommendation=?, evaluation_json=? WHERE id=?
        """, (*values, pending.score, pending.recommendation, canonical_json(pending.to_dict()),
              application['id']))

    def get(self, candidacy_id: int) -> dict[str, Any] | None:
        _identifier(candidacy_id)
        with self.database._connection() as connection:
            row = connection.execute('''
                SELECT c.*, a.status, a.notes FROM candidacies c
                JOIN applications a ON a.id=c.application_id WHERE c.id=?
            ''', (candidacy_id,)).fetchone()
        return dict(row) if row is not None else None

    def list(self) -> list[dict[str, Any]]:
        with self.database._connection() as connection:
            rows = connection.execute('''
                SELECT c.*, a.status, a.notes FROM candidacies c
                JOIN applications a ON a.id=c.application_id ORDER BY c.id
            ''').fetchall()
        return [dict(row) for row in rows]

    def history(self, candidacy_id: int) -> list[dict[str, Any]]:
        with self.database._connection() as connection:
            connection.execute('BEGIN')
            self._row(connection, candidacy_id)
            result = []
            for table, kind in (('candidacy_revisions', 'revision'), ('candidacy_events', 'event'),
                                ('candidacy_authorizations', 'authorization')):
                rows = connection.execute('SELECT * FROM ' + table + ' WHERE candidacy_id=?',
                                          (candidacy_id,)).fetchall()
                for row in rows:
                    item = dict(row)
                    item['type'] = kind
                    try:
                        item['snapshot'] = json.loads(item.pop('snapshot_json'))
                        if 'receipt_json' in item:
                            value = item.pop('receipt_json')
                            item['receipt'] = json.loads(value) if value is not None else None
                    except (TypeError, ValueError):
                        raise WorkflowError('invalid_workflow_history') from None
                    result.append(item)
        return sorted(result, key=lambda item: (item['created_at'], item['type'], str(item.get('id', ''))))

    def edit(self, candidacy_id: int, *, resume_version_id: str | None = None,
             content: str | None = None, vacancy_id: int | None = None,
             regenerate_content: bool = False) -> bool:
        require_dry_run()
        if type(regenerate_content) is not bool:
            raise WorkflowError('invalid_regenerate_content')
        if regenerate_content and content is not None:
            raise WorkflowError('conflicting_content_changes')
        if resume_version_id is not None:
            _hash(resume_version_id)
        if content is not None:
            _content(content)
        if vacancy_id is not None:
            _identifier(vacancy_id)
        with self.database._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            candidacy = self._row(connection, candidacy_id)
            new_version = candidacy['resume_version_id'] if resume_version_id is None else resume_version_id
            new_content = candidacy['content'] if content is None else content
            new_vacancy = candidacy['vacancy_id'] if vacancy_id is None else vacancy_id
            current_snapshot = None
            try:
                current_snapshot = self._critical(connection, candidacy)
            except WorkflowError:
                # A valid new version can repair a damaged draft only after
                # its old permission has been persistently revoked.
                connection.execute('BEGIN IMMEDIATE')
                latest = self._row(connection, candidacy_id)
                if any(latest[key] != candidacy[key] for key in (
                        'revision', 'content', 'resume_version_id', 'vacancy_id', 'company')):
                    raise WorkflowError('candidacy_changed') from None
                candidacy = latest
                if new_version == candidacy['resume_version_id']:
                    raise
            if (not regenerate_content and (new_version, new_content, new_vacancy) == (
                    candidacy['resume_version_id'], candidacy['content'], candidacy['vacancy_id'])):
                return False
            job = self._vacancy(connection, new_vacancy)
            if (current_snapshot is not None and new_version == candidacy['resume_version_id']
                    and new_vacancy == candidacy['vacancy_id']):
                metadata = current_snapshot['resume']
            else:
                metadata = self._resume(new_version, job)
            if regenerate_content:
                from .drafts import build_draft
                new_content = _content(build_draft(job, metadata))
            if (new_version, new_content, new_vacancy) == (
                    candidacy['resume_version_id'], candidacy['content'], candidacy['vacancy_id']):
                return False
            conflict = connection.execute('SELECT id FROM candidacies WHERE vacancy_id=? AND id!=?',
                                          (new_vacancy, candidacy_id)).fetchone()
            if conflict:
                raise WorkflowError('vacancy_already_managed')
            identity = legacy_identity(job.url or '', job.company, job.title or 'Untitled role')
            alias = connection.execute('SELECT application_id FROM application_identities WHERE identity=?',
                                       (identity,)).fetchone()
            if alias and alias['application_id'] != candidacy['application_id']:
                raise WorkflowError('application_already_exists')
            connection.execute('INSERT OR IGNORE INTO application_identities(identity, application_id) VALUES (?, ?)',
                               (identity, candidacy['application_id']))
            self.database._invalidate_candidacy(connection, candidacy, 'draft_changed')
            timestamp = _now()
            connection.execute('''
                UPDATE candidacies SET vacancy_id=?, resume_version_id=?, content=?, company=?,
                    revision=revision+1, workflow_state='draft', review_digest=NULL, updated_at=? WHERE id=?
            ''', (new_vacancy, new_version, new_content, job.company, timestamp, candidacy_id))
            self._update_application_job(connection, candidacy, job, new_vacancy, timestamp)
            updated = self._row(connection, candidacy_id)
            snapshot = self._snapshot(updated, job, metadata)
            connection.execute('''
                INSERT INTO candidacy_revisions(candidacy_id, revision, snapshot_json, created_at)
                VALUES (?, ?, ?, ?)
            ''', (candidacy_id, updated['revision'], canonical_json(snapshot), timestamp))
            self.database._event(connection, updated, 'edited', snapshot)
            return True

    def _update_application_job(self, connection: sqlite3.Connection, candidacy: sqlite3.Row,
                                job: NormalizedJob, vacancy_id: int, timestamp: str) -> None:
        application = connection.execute('SELECT * FROM applications WHERE id=?',
                                         (candidacy['application_id'],)).fetchone()
        revision = connection.execute("""
            SELECT snapshot_json FROM candidacy_revisions WHERE candidacy_id=? AND revision=?
        """, (candidacy['id'], candidacy['revision'])).fetchone()
        previous = json.loads(revision['snapshot_json'])
        fields = ('title', 'company', 'location', 'url', 'description')
        values = self._job_values(job)
        changed = (vacancy_id != candidacy['vacancy_id']
                   or vacancy_digest(job) != previous['vacancy_digest']
                   or values != tuple(application[field] for field in fields))
        if changed:
            # Preserve exact old JSON and the job it evaluated before replacing
            # either. CV/content-only edits retain the existing evaluation.
            self.database._event(connection, candidacy, 'application_snapshot_preserved',
                                 {'application': dict(application), 'vacancy_id': candidacy['vacancy_id'],
                                  'vacancy': previous['vacancy']})
            pending = EvaluationResult(0, 'insufficient_information', algorithm_version='unevaluated')
            connection.execute("""
                UPDATE applications SET score=?, recommendation=?, evaluation_json=? WHERE id=?
            """, (pending.score, pending.recommendation, canonical_json(pending.to_dict()),
                  candidacy['application_id']))
        connection.execute("""
            UPDATE applications SET title=?, company=?, location=?, url=?, description=?, updated_at=? WHERE id=?
        """, (*values, timestamp, candidacy['application_id']))

    def review(self, candidacy_id: int) -> dict[str, Any]:
        require_dry_run()
        with self.database._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            candidacy = self._row(connection, candidacy_id)
            snapshot = self._critical(connection, candidacy)
            self._trackable(connection, candidacy)
            digest = content_digest(snapshot)
            if candidacy['workflow_state'] != 'simulated' and candidacy['review_digest'] != digest:
                connection.execute('''
                    UPDATE candidacies SET review_digest=?, workflow_state='reviewed', updated_at=? WHERE id=?
                ''', (digest, _now(), candidacy_id))
                self.database._event(connection, candidacy, 'reviewed',
                                     {'review_digest': digest, 'snapshot': snapshot})
            return {'review_digest': digest, 'snapshot': snapshot}

    def approve(self, candidacy_id: int, review_digest: str) -> str:
        require_dry_run()
        _hash(review_digest)
        with self.database._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            candidacy = self._row(connection, candidacy_id)
            snapshot = self._critical(connection, candidacy)
            self._trackable(connection, candidacy)
            if (candidacy['workflow_state'] not in ('reviewed', 'approved')
                    or candidacy['review_digest'] != review_digest
                    or content_digest(snapshot) != review_digest):
                raise WorkflowError('review_required')
            existing = connection.execute('''
                SELECT * FROM candidacy_authorizations WHERE candidacy_id=? AND revision=?
            ''', (candidacy_id, candidacy['revision'])).fetchone()
            if existing:
                if (existing['status'] == 'active' and existing['review_digest'] == review_digest
                        and existing['snapshot_json'] == canonical_json(snapshot)):
                    return str(existing['authorization_id'])
                raise WorkflowError('authorization_unavailable')
            authorization_id = uuid.uuid4().hex
            connection.execute('''
                INSERT INTO candidacy_authorizations(authorization_id, candidacy_id, revision,
                    review_digest, snapshot_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?)
            ''', (authorization_id, candidacy_id, candidacy['revision'], review_digest,
                  canonical_json(snapshot), _now()))
            connection.execute("UPDATE candidacies SET workflow_state='approved', updated_at=? WHERE id=?",
                               (_now(), candidacy_id))
            self.database._event(connection, candidacy, 'approved',
                                 {'authorization_id': authorization_id, 'review_digest': review_digest,
                                  'snapshot': snapshot})
            return authorization_id

    def simulate(self, authorization_id: str) -> dict[str, Any]:
        policy = require_dry_run()
        if not isinstance(authorization_id, str) or not _AUTHORIZATION.fullmatch(authorization_id):
            raise WorkflowError('invalid_authorization_identifier')
        with self.database._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            authorization = connection.execute('''
                SELECT * FROM candidacy_authorizations WHERE authorization_id=?
            ''', (authorization_id,)).fetchone()
            if authorization is None or authorization['status'] != 'active':
                raise WorkflowError('authorization_unavailable')
            candidacy = self._row(connection, authorization['candidacy_id'])
            snapshot = self._critical(connection, candidacy)
            try:
                self._trackable(connection, candidacy)
                if (candidacy['workflow_state'] != 'approved'
                        or candidacy['revision'] != authorization['revision']
                        or candidacy['review_digest'] != authorization['review_digest']
                        or content_digest(snapshot) != authorization['review_digest']
                        or canonical_json(snapshot) != authorization['snapshot_json']):
                    raise WorkflowError('authorization_binding_changed')
            except WorkflowError:
                self.database._invalidate_candidacy(connection, candidacy, 'authorization_binding_changed')
                connection.commit()
                raise WorkflowError('authorization_binding_changed') from None
            receipt = {**policy, 'submitted': False, 'authorization_id': authorization_id,
                       'candidacy_id': int(candidacy['id']), 'application_id': int(candidacy['application_id']),
                       'revision': int(candidacy['revision']), 'review_digest': authorization['review_digest'],
                       'simulated_at': _now()}
            consumed = connection.execute('''
                UPDATE candidacy_authorizations SET status='consumed', consumed_at=?, receipt_json=?
                WHERE authorization_id=? AND status='active'
            ''', (receipt['simulated_at'], canonical_json(receipt), authorization_id))
            if consumed.rowcount != 1:
                raise WorkflowError('authorization_unavailable')
            connection.execute("UPDATE candidacies SET workflow_state='simulated', updated_at=? WHERE id=?",
                               (receipt['simulated_at'], candidacy['id']))
            self.database._event(connection, candidacy, 'simulated', receipt)
            return receipt

    def update_tracking(self, candidacy_id: int, *, status: str | None = None,
                        notes: str | None = None, outcome: str | None = None,
                        next_step: str | None = None, follow_up_on: str | None = None) -> bool:
        require_dry_run()
        with self.database._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            candidacy = self._row(connection, candidacy_id)
            return self.database._update_managed_tracking(connection, candidacy, status=status,
                        notes=notes, outcome=outcome, next_step=next_step, follow_up_on=follow_up_on)
