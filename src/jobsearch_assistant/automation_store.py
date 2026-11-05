"""Atomic observations, immutable evaluation references and redacted run history."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from .matching import evaluate_match
from .workflow_contracts import WorkflowError, canonical_json, content_digest, require_dry_run, vacancy_digest


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def safe_reports(reports):
    """Allow only implementation codes/counters, never provider/user text."""
    result = []
    for report in reports:
        source = report.get('source')
        status = report.get('status')
        if source not in ('greenhouse', 'lever', 'ashby') or status not in (
                'disabled', 'ok', 'partial', 'paused', 'error'):
            raise WorkflowError('invalid_run_report')
        item = {'source': source, 'status': status}
        for key in ('requests', 'rejected', 'duplicates'):
            value = report.get(key, 0)
            if type(value) is not int or value < 0:
                raise WorkflowError('invalid_run_report')
            item[key] = value
        item['issues'] = [code for code in report.get('issues', [])
                          if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,50}|http_[0-9]{3}', code)]
        result.append(item)
    return result


class AutomationStore:
    """The caller holds RunLock for mutations/recovery; CLI enforces that rule."""

    def __init__(self, database, *, language='es'):
        self.database = database
        if language not in ('es', 'en'):
            raise WorkflowError('invalid_language')
        self.language = language

    def start(self, config_digest, profile_digest):
        require_dry_run()
        run_id, now = uuid.uuid4().hex, timestamp()
        with self.database._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            recovered = connection.execute("""UPDATE automation_runs SET status='interrupted', finished_at=?
                WHERE status='running'""", (now,)).rowcount
            connection.execute('''INSERT INTO automation_runs
                (id,started_at,status,config_digest,profile_digest,recovered_runs)
                VALUES (?,?,'running',?,?,?)''', (run_id, now, config_digest, profile_digest, recovered))
        return run_id

    def observe(self, run_id, job, profile):
        require_dry_run()
        semantic, profile_hash = vacancy_digest(job), content_digest(profile.to_dict())
        with self.database._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            active = connection.execute('SELECT status FROM automation_runs WHERE id=?', (run_id,)).fetchone()
            if not active or active['status'] != 'running':
                raise WorkflowError('run_not_active')
            existing = connection.execute('''SELECT id,job_json FROM vacancies
                WHERE source=? AND source_board=? AND source_job_id=?''',
                (job.source, job.source_board, job.source_job_id)).fetchone()
            if existing:
                item = connection.execute('SELECT * FROM automation_items WHERE run_id=? AND vacancy_id=?',
                                          (run_id, existing['id'])).fetchone()
                if item:
                    return self._item(item)
            # Reuse Fase 4's invalidation guard in THIS transaction.
            vacancy_id = self.database._upsert_vacancy_on_connection(connection, job)
            previous = connection.execute('SELECT * FROM automation_observations WHERE vacancy_id=?',
                                          (vacancy_id,)).fetchone()
            if previous and (previous['semantic_digest'], previous['profile_digest'],
                             previous['algorithm_version']) == (semantic, profile_hash, 'matching_v2'):
                evaluation_id, change = previous['evaluation_id'], 'unchanged'
                evaluation = connection.execute('SELECT evaluation_json FROM evaluations WHERE id=?',
                                                (evaluation_id,)).fetchone()
                classification = json.loads(evaluation['evaluation_json'])['recommendation']
            else:
                result = evaluate_match(profile, job)
                evaluation_id = self.database._save_evaluation_on_connection(
                    connection, vacancy_id, profile, result, job=job)
                classification = result.recommendation
                if not existing:
                    change = 'new'
                elif previous and previous['semantic_digest'] == semantic:
                    change = 'reevaluated'
                elif existing:
                    old = json.loads(existing['job_json'])
                    old.pop('retrieved_at', None)
                    change = 'changed' if content_digest(old) != semantic else 'reevaluated'
                connection.execute('''INSERT INTO automation_observations VALUES (?,?,?,?,?)
                    ON CONFLICT(vacancy_id) DO UPDATE SET semantic_digest=excluded.semantic_digest,
                    profile_digest=excluded.profile_digest,algorithm_version=excluded.algorithm_version,
                    evaluation_id=excluded.evaluation_id''',
                    (vacancy_id, semantic, profile_hash, result.algorithm_version, evaluation_id))
            connection.execute('INSERT INTO automation_items VALUES (?,?,?,?,?)',
                               (run_id, vacancy_id, evaluation_id, change, classification))
            if change != 'unchanged':
                from .notifications import queue_event
                kind = ('priority' if classification == 'high_priority' else
                        'eligibility_pending' if classification == 'insufficient_information' else None)
                if kind:
                    queue_event(connection, f'{kind}:{evaluation_id}', kind, entity_id=vacancy_id,
                                language=self.language)
            return {'vacancy_id': vacancy_id, 'evaluation_id': evaluation_id,
                    'change': change, 'classification': classification}

    @staticmethod
    def _item(row):
        return {'vacancy_id': row['vacancy_id'], 'evaluation_id': row['evaluation_id'],
                'change': row['change_kind'], 'classification': row['classification']}

    def save_http_state(self, payload):
        require_dry_run()
        if payload.get('version') != 1 or set(payload.get('providers', {})) - {'greenhouse', 'lever', 'ashby'}:
            raise WorkflowError('invalid_http_state')
        with self.database._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            for provider, state in payload['providers'].items():
                if set(state) != {'failures', 'paused_until', 'not_before'}:
                    raise WorkflowError('invalid_http_state')
                if type(state['failures']) is not int or state['failures'] < 0:
                    raise WorkflowError('invalid_http_state')
                for key in ('paused_until', 'not_before'):
                    value = state[key]
                    if value is not None:
                        if not isinstance(value, str) or len(value) > 50:
                            raise WorkflowError('invalid_http_state')
                        date = datetime.fromisoformat(value)
                        if date.tzinfo is None:
                            raise WorkflowError('invalid_http_state')
                connection.execute('''INSERT INTO automation_http_state VALUES (?,?)
                    ON CONFLICT(provider) DO UPDATE SET state_json=excluded.state_json''',
                    (provider, canonical_json(state)))

    def load_http_state(self):
        with self.database._connection() as connection:
            rows = connection.execute('SELECT * FROM automation_http_state').fetchall()
        return {'version': 1, 'providers': {row['provider']: json.loads(row['state_json']) for row in rows}}

    def finish(self, run_id, status, reports):
        require_dry_run()
        if status not in ('success', 'partial', 'deadline', 'interrupted', 'failed'):
            raise WorkflowError('invalid_run_status')
        reports, now = safe_reports(reports), timestamp()
        from .notifications import queue_event
        with self.database._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            updated = connection.execute('''UPDATE automation_runs SET status=?,finished_at=?,reports_json=?
                WHERE id=? AND status='running' ''', (status, now, canonical_json(reports), run_id))
            if not updated.rowcount:
                raise WorkflowError('run_not_active')
            providers = sorted({r['source'] for r in reports if r['status'] != 'disabled'})
            for provider in providers:
                relevant = [r for r in reports if r['source'] == provider and r['status'] != 'disabled']
                ok = all(r['status'] == 'ok' for r in relevant)
                old = connection.execute('SELECT * FROM automation_source_health WHERE provider=?',
                                         (provider,)).fetchone()
                failures = 0 if ok else (old['failures'] + 1 if old else 1)
                episode = None if ok else (old['episode'] if old and old['episode'] else run_id)
                if ok and old and old['failures']:
                    queue_event(connection, f'recovered:{provider}:{old["episode"]}', 'recovered', language=self.language)
                if not ok:
                    queue_event(connection, f'error:{provider}:{episode}', 'source_error', language=self.language)
                connection.execute('''INSERT INTO automation_source_health VALUES (?,?,?,?,?,?)
                    ON CONFLICT(provider) DO UPDATE SET failures=excluded.failures,episode=excluded.episode,
                    last_success=excluded.last_success,last_failure=excluded.last_failure,last_status=excluded.last_status''',
                    (provider, failures, episode, now if ok else old['last_success'] if old else None,
                     now if not ok else old['last_failure'] if old else None, 'ok' if ok else 'error'))
            # Announce existing drafts only; no generation or approval occurs here.
            for candidate in connection.execute("SELECT id,revision FROM candidacies WHERE workflow_state='draft'"):
                queue_event(connection, f'review:{candidate[0]}:{candidate[1]}', 'review_pending', entity_id=candidate[0], language=self.language)
            count = connection.execute('SELECT COUNT(*) FROM automation_items WHERE run_id=?', (run_id,)).fetchone()[0]
            queue_event(connection, f'summary:{run_id}', 'run_summary', count=count, language=self.language)
        return self.show(run_id)

    def show(self, run_id):
        with self.database._connection() as connection:
            connection.execute('BEGIN')
            row = connection.execute('''SELECT id,started_at,finished_at,status,recovered_runs,reports_json
                FROM automation_runs WHERE id=?''', (run_id,)).fetchone()
            if row is None:
                raise WorkflowError('unknown_run')
            counts = {key: 0 for key in ('total', 'new', 'changed', 'reevaluated', 'unchanged',
                                        'high_priority', 'insufficient_information')}
            for item in connection.execute('SELECT change_kind,classification FROM automation_items WHERE run_id=?', (run_id,)):
                counts['total'] += 1
                counts[item['change_kind']] += 1
                if item['classification'] in ('high_priority', 'insufficient_information'):
                    counts[item['classification']] += 1
        return {'run_id': row['id'], 'started_at': row['started_at'], 'finished_at': row['finished_at'],
                'status': row['status'], 'recovered_runs': row['recovered_runs'],
                'counts': counts, 'sources': json.loads(row['reports_json']),
                'dry_run': True, 'auto_submit': False, 'submitted': False}

    def history(self, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise WorkflowError('invalid_run_limit')
        with self.database._connection() as connection:
            rows = connection.execute('SELECT id FROM automation_runs ORDER BY started_at DESC,id DESC LIMIT ?', (limit,)).fetchall()
        return [self.show(row[0]) for row in rows]
