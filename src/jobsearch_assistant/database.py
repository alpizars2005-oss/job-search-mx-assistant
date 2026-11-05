from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .migrations import SCHEMA_VERSION, initialize_database, legacy_identity
from .models import (
    VALID_STATUSES,
    ApplicationRecord,
    CandidateProfile,
    EvaluationResult,
    JobPosting,
)
from .sources.models import NormalizedJob
from .workflow_contracts import WorkflowError, content_digest, require_dry_run

__all__ = ['SCHEMA_VERSION', 'ApplicationDatabase']


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()



class ApplicationDatabase:
    def __init__(self, path: Path, *, timeout: float = 30, control=None) -> None:
        self.path = Path(path)
        self.timeout, self.control = timeout, control
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        timeout = self.timeout if self.control is None else min(self.timeout, max(0.01, self.control.remaining()))
        connection = sqlite3.connect(self.path, timeout=timeout)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a transactional connection and always release its file handles."""
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        initialize_database(self.path, timeout=self.timeout, control=self.control)

    def upsert_vacancy(self, job: NormalizedJob) -> int:
        """Update source evidence atomically, retaining the stable vacancy ID."""
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            return self._upsert_vacancy_on_connection(connection, job)

    def _upsert_vacancy_on_connection(self, connection, job: NormalizedJob) -> int:
        """Reuse the same validation/invalidation in a larger local transaction."""
        payload = _canonical_json(asdict(job))
        previous = connection.execute(
            'SELECT id, job_json FROM vacancies WHERE source=? AND source_board=? AND source_job_id=?',
            (job.source, job.source_board, job.source_job_id),
        ).fetchone()
        if previous:
            old_data = json.loads(previous['job_json'])
            new_data = asdict(job)
            old_data.pop('retrieved_at', None)
            new_data.pop('retrieved_at', None)
            if content_digest(old_data) != content_digest(new_data):
                managed = connection.execute('SELECT * FROM candidacies WHERE vacancy_id=?',
                                             (previous['id'],)).fetchone()
                if managed:
                    require_dry_run()
                    self._invalidate_candidacy(connection, managed, 'vacancy_changed')
        connection.execute('''
            INSERT INTO vacancies(source, source_board, source_job_id, job_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source, source_board, source_job_id)
            DO UPDATE SET job_json=excluded.job_json
        ''', (job.source, job.source_board, job.source_job_id, payload))
        row = connection.execute('''
            SELECT id FROM vacancies WHERE source=? AND source_board=? AND source_job_id=?
        ''', (job.source, job.source_board, job.source_job_id)).fetchone()
        return int(row[0])

    def get_vacancy(self, vacancy_id: int) -> NormalizedJob | None:
        with self._connection() as connection:
            row = connection.execute('SELECT job_json FROM vacancies WHERE id=?',
                                     (vacancy_id,)).fetchone()
        return NormalizedJob(**json.loads(row[0])) if row else None

    def list_vacancies(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute('SELECT id, job_json FROM vacancies ORDER BY id').fetchall()
        return [{'id': int(row['id']), 'job': json.loads(row['job_json'])} for row in rows]

    def save_evaluation(
        self, vacancy_id: int, profile: CandidateProfile, result: EvaluationResult,
        *, job: NormalizedJob | None = None,
    ) -> int:
        """Append an immutable evaluation, or return an identical saved result.

        Pass the exact evaluated job to preserve its snapshot if another writer
        refreshes the vacancy meanwhile. Without it, the caller must have
        evaluated the vacancy currently stored. Hashes cover the entire job and
        profile, including evidence and retrieval time, with canonical JSON.
        Divergent results for the same inputs/version are rejected explicitly.
        """
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            return self._save_evaluation_on_connection(connection, vacancy_id, profile, result, job=job)

    def _save_evaluation_on_connection(self, connection, vacancy_id, profile, result, *, job=None):
        profile_data = profile.to_dict()
        profile_json = _canonical_json(profile_data)
        result_json = _canonical_json(result.to_dict())
        vacancy = connection.execute('SELECT * FROM vacancies WHERE id=?',
                                     (vacancy_id,)).fetchone()
        if vacancy is None:
            raise ValueError('Unknown vacancy')
        if job is not None:
            if (job.source, job.source_board, job.source_job_id) != (
                vacancy['source'], vacancy['source_board'], vacancy['source_job_id']
            ):
                raise ValueError('Evaluated job does not match vacancy identity')
            job_data = asdict(job)
        else:
            job_data = json.loads(vacancy['job_json'])
        job_json = _canonical_json(job_data)
        input_fingerprint = _fingerprint({'job': job_data, 'profile': profile_data})
        existing = connection.execute('''
            SELECT id, evaluation_json FROM evaluations
            WHERE vacancy_id=? AND algorithm_version=? AND input_fingerprint=?
        ''', (vacancy_id, result.algorithm_version, input_fingerprint)).fetchone()
        if existing:
            if existing['evaluation_json'] != result_json:
                raise ValueError('Conflicting evaluation for the same inputs and algorithm version')
            return int(existing['id'])
        cursor = connection.execute('''
            INSERT INTO evaluations(
                vacancy_id, algorithm_version, profile_fingerprint, input_fingerprint,
                job_snapshot_json, profile_snapshot_json, evaluation_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (vacancy_id, result.algorithm_version, _fingerprint(profile_data),
              input_fingerprint, job_json, profile_json, result_json))
        return int(cursor.lastrowid)

    def list_evaluations(self, vacancy_id: int) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute('''
                SELECT * FROM evaluations WHERE vacancy_id=? ORDER BY id
            ''', (vacancy_id,)).fetchall()
        return [{
            'id': int(row['id']), 'vacancy_id': int(row['vacancy_id']),
            'algorithm_version': row['algorithm_version'],
            'profile_fingerprint': row['profile_fingerprint'],
            'input_fingerprint': row['input_fingerprint'],
            'job_snapshot': json.loads(row['job_snapshot_json']),
            'profile_snapshot': json.loads(row['profile_snapshot_json']),
            'evaluation': json.loads(row['evaluation_json']),
        } for row in rows]

    def add(self, record: ApplicationRecord) -> int:
        if record.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {record.status}")
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            return self._add_on_connection(connection, record)

    @staticmethod
    def _add_on_connection(connection: sqlite3.Connection, record: ApplicationRecord) -> int:
        """Reuse tracker identity within the caller's transaction."""
        payload = json.dumps(record.evaluation.to_dict(), ensure_ascii=False)
        identity = legacy_identity(record.job.url, record.job.company, record.job.title)
        existing = connection.execute(
            'SELECT application_id FROM application_identities WHERE identity=?',
            (identity,),
        ).fetchone()
        if existing:
            return int(existing[0])
        cursor = connection.execute(
            """
            INSERT INTO applications(
                title, company, location, url, description,
                score, recommendation, evaluation_json,
                status, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.job.title,
                record.job.company,
                record.job.location,
                record.job.url,
                record.job.description,
                record.evaluation.score,
                record.evaluation.recommendation,
                payload,
                record.status,
                record.notes,
                record.created_at,
                record.updated_at,
            ),
        )
        record_id = int(cursor.lastrowid)
        connection.execute(
            'INSERT INTO application_identities(identity, application_id) VALUES (?, ?)',
            (identity, record_id),
        )
        return record_id

    def list(self, status: str | None = None) -> list[ApplicationRecord]:
        query = "SELECT * FROM applications"
        params: tuple[Any, ...] = ()
        if status:
            if status not in VALID_STATUSES:
                raise ValueError(f"Invalid status: {status}")
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY updated_at DESC, id DESC"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def update(self, record_id: int, status: str | None = None, notes: str | None = None) -> bool:
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            managed = connection.execute('SELECT * FROM candidacies WHERE application_id=?',
                                         (record_id,)).fetchone()
            if managed:
                require_dry_run()
                if type(record_id) is not int or record_id <= 0:
                    raise WorkflowError('invalid_application_identifier')
                return self._update_managed_tracking(connection, managed, status=status, notes=notes)
            if status is not None and status not in VALID_STATUSES:
                raise ValueError(f"Invalid status: {status}")
            assignments: list[str] = []
            values: list[Any] = []
            if status is not None:
                assignments.append("status = ?")
                values.append(status)
            if notes is not None:
                assignments.append("notes = ?")
                values.append(notes)
            if not assignments:
                return False
            assignments.append("updated_at = ?")
            values.append(datetime.now(timezone.utc).isoformat(timespec="seconds"))
            values.append(record_id)
            cursor = connection.execute(
                f"UPDATE applications SET {', '.join(assignments)} WHERE id = ?", tuple(values),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _event(connection: sqlite3.Connection, candidacy: sqlite3.Row, kind: str, snapshot: Any) -> None:
        connection.execute("""
            INSERT INTO candidacy_events(candidacy_id, revision, event_type, snapshot_json, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (candidacy['id'], candidacy['revision'], kind, _canonical_json(snapshot),
              datetime.now(timezone.utc).isoformat()))

    @classmethod
    def _invalidate_candidacy(cls, connection: sqlite3.Connection, candidacy: sqlite3.Row,
                             reason: str) -> None:
        cursor = connection.execute("""
            UPDATE candidacy_authorizations SET status='invalidated'
            WHERE candidacy_id=? AND status='active'
        """, (candidacy['id'],))
        if cursor.rowcount or candidacy['review_digest'] is not None:
            connection.execute("""
                UPDATE candidacies SET review_digest=NULL,
                    workflow_state=CASE WHEN workflow_state='simulated' THEN 'simulated' ELSE 'draft' END,
                    updated_at=? WHERE id=?
            """, (datetime.now(timezone.utc).isoformat(), candidacy['id']))
            cls._event(connection, candidacy, 'invalidated', {'reason': reason})

    @classmethod
    def _update_managed_tracking(cls, connection: sqlite3.Connection, candidacy: sqlite3.Row, *,
                                 status: str | None = None, notes: str | None = None,
                                 outcome: str | None = None, next_step: str | None = None,
                                 follow_up_on: str | None = None) -> bool:
        application = connection.execute('SELECT status, notes FROM applications WHERE id=?',
                                         (candidacy['application_id'],)).fetchone()
        graph = {
            'saved': {'interested', 'applied', 'rejected', 'withdrawn'},
            'interested': {'saved', 'applied', 'rejected', 'withdrawn'},
            'applied': {'screening', 'interview', 'offer', 'rejected', 'withdrawn'},
            'screening': {'interview', 'offer', 'rejected', 'withdrawn'},
            'interview': {'offer', 'rejected', 'withdrawn'},
            'offer': set(), 'rejected': set(), 'withdrawn': set(),
        }
        if (status is not None and (not isinstance(status, str) or status not in graph
                or (status != application['status'] and status not in graph.get(application['status'], set())))):
            raise WorkflowError('invalid_tracker_transition')
        for value in (notes, outcome, next_step, follow_up_on):
            if value is not None and (not isinstance(value, str) or len(value) > 100_000):
                raise WorkflowError('invalid_tracking_value')
        if follow_up_on:
            try:
                parsed = date.fromisoformat(follow_up_on)
                if parsed.isoformat() != follow_up_on:
                    raise ValueError()
            except ValueError:
                raise WorkflowError('invalid_follow_up_date') from None
        tracker = {'status': application['status'], 'notes': application['notes'],
                   'outcome': candidacy['outcome'], 'next_step': candidacy['next_step'],
                   'follow_up_on': candidacy['follow_up_on']}
        previous = tracker.copy()
        for key, value in (('status', status), ('notes', notes), ('outcome', outcome),
                           ('next_step', next_step), ('follow_up_on', follow_up_on)):
            if value is not None:
                tracker[key] = value
        if previous == tracker:
            return False
        now = datetime.now(timezone.utc).isoformat()
        connection.execute('UPDATE applications SET status=?, notes=?, updated_at=? WHERE id=?',
                           (tracker['status'], tracker['notes'], now, candidacy['application_id']))
        connection.execute('UPDATE candidacies SET outcome=?, next_step=?, follow_up_on=?, updated_at=? WHERE id=?',
                           (tracker['outcome'], tracker['next_step'], tracker['follow_up_on'], now, candidacy['id']))
        if tracker['status'] not in ('saved', 'interested'):
            cls._invalidate_candidacy(connection, candidacy, 'tracker_advanced')
        cls._event(connection, candidacy, 'tracking_updated', tracker)
        return True

    def update_status(self, record_id: int, status: str) -> bool:
        return self.update(record_id, status=status)

    def find_duplicate(self, job: JobPosting) -> int | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT application_id FROM application_identities WHERE identity=?',
                (legacy_identity(job.url, job.company, job.title),),
            ).fetchone()
            return int(row[0]) if row else None

    def summary(self) -> dict[str, int]:
        result = {status: 0 for status in VALID_STATUSES}
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM applications GROUP BY status"
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        for row in rows:
            result[row["status"]] = int(row["count"])
        result["total"] = int(total)
        return result

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ApplicationRecord:
        evaluation_data = json.loads(row["evaluation_json"])
        evaluation = EvaluationResult(**evaluation_data)
        job = JobPosting(
            title=row["title"],
            company=row["company"],
            location=row["location"],
            url=row["url"],
            description=row["description"],
        )
        return ApplicationRecord(
            id=int(row["id"]),
            job=job,
            evaluation=evaluation,
            status=row["status"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
