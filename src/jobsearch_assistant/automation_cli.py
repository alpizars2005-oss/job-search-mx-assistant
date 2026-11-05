"""One-shot and read-only operational commands, with redacted JSON output."""
from __future__ import annotations

import json
import math
import re
import signal
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .automation import AutomationRunner
from .automation_store import AutomationStore
from .config import data_home
from .database import ApplicationDatabase
from .migrations import SCHEMA_VERSION
from .models import CandidateProfile
from .runtime_control import RunControl, RunLock, probe_run_lock
from .sources.config import load_source_config
from .sources.models import SourceError
from .sources.http import SafeHttpClient
from .workflow_cli import _read_object
from .workflow_contracts import WorkflowError, canonical_json, content_digest, require_dry_run
from .private_storage import private_directory, private_path, sqlite_private


def add_automation_parsers(sub):
    operations = sub.add_parser('automation', help='Run once or inspect redacted local operational state')
    commands = operations.add_subparsers(dest='automation_command', required=True)
    run = commands.add_parser('run', help='Discover and evaluate once; never prepare or submit candidacies')
    run.add_argument('--config', type=Path)
    run.add_argument('--budget-seconds', type=float, default=120)
    run.add_argument('--language', choices=('es', 'en'), default='es')
    health = commands.add_parser('health', help='Read-only SQLite, last run and source diagnostics')
    health.add_argument('--max-age-seconds', type=float, default=86400)
    runs = commands.add_parser('runs', help='List redacted run summaries')
    runs.add_argument('--limit', type=int, default=20)
    show = commands.add_parser('show', help='Read one redacted run summary')
    show.add_argument('run_id')
    commands.add_parser('sources', help='Read durable source constraints and their exact digest')
    resume = commands.add_parser('resume-source', help='Audit removal of an expired manual suspension')
    resume.add_argument('provider', choices=('greenhouse', 'lever', 'ashby'))
    resume.add_argument('--state-digest', required=True)
    resume.add_argument('--reason-code', required=True, choices=('external_deadline_elapsed',))
    review = commands.add_parser('review-restored-sources', help='Acknowledge manual review after restore')
    review.add_argument('--state-digest', required=True)
    review.add_argument('--reason-code', required=True, choices=('external_limits_reviewed',))


def _private_home():
    home = private_path(data_home())
    checkout = Path(__file__).resolve().parents[2]
    if home == checkout or checkout in home.parents:
        raise WorkflowError('automation_home_inside_checkout')
    for component in (home, *home.parents):
        if component.is_symlink():
            raise WorkflowError('unsafe_automation_home')
    return home


class ReadOnlyDatabase:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _connection(self):
        connection = sqlite_private(self.path, read_only=True, timeout=0.1)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()


def _date(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('invalid_operational_date')
    return parsed.astimezone(timezone.utc)


def _source_snapshot(connection):
    providers = {row['provider']: json.loads(row['state_json']) for row in connection.execute(
        'SELECT provider,state_json FROM automation_http_state ORDER BY provider')}
    version = 2 if any('suspension' in state for state in providers.values()) else 1
    if version == 2:
        providers = {name: dict(state, suspension=state.get('suspension'))
                     for name, state in providers.items()}
    payload = {'version': version, 'providers': providers}
    SafeHttpClient().import_state(payload)  # Strict validation, never an HTTP request.
    marker = connection.execute("SELECT value FROM meta WHERE key='source_review_required'").fetchone()
    snapshot = {'http_state': payload, 'review_required': bool(marker and marker[0] != '0')}
    return {**snapshot, 'state_digest': content_digest(snapshot)}


def source_state(database):
    with database._connection() as connection:
        connection.execute('BEGIN')
        return _source_snapshot(connection)


def _check_elapsed(values, now):
    suspension = values.get('suspension')
    if suspension is not None and suspension['not_before'] is None:
        raise SourceError('retry_after_unbounded')
    deadlines = [values['paused_until'], values['not_before']]
    if suspension is not None:
        deadlines.append(suspension['not_before'])
    if any(value is not None and _date(value) > now for value in deadlines):
        raise SourceError('retry_after_active')


def recover_sources(database, *, expected_digest, reason_code, provider=None,
                    review_restore=False, now=None):
    """Call under RunLock; authorize one exact snapshot and append its audit.

    Restoring an old snapshot cannot prove that newer external constraints did
    not exist. Review is an explicit operator attestation, never an inferred
    expiry. Known active or unrepresentable deadlines cannot be bypassed.
    """
    require_dry_run()
    if (not isinstance(expected_digest, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_digest)
            or type(review_restore) is not bool):
        raise WorkflowError('invalid_source_authorization')
    if review_restore:
        if provider is not None or reason_code != 'external_limits_reviewed':
            raise WorkflowError('invalid_source_authorization')
    elif provider not in ('greenhouse', 'lever', 'ashby') or reason_code != 'external_deadline_elapsed':
        raise WorkflowError('invalid_source_authorization')
    now = _date((now or datetime.now(timezone.utc)).isoformat())
    with database._connection() as connection:
        connection.execute('BEGIN IMMEDIATE')
        snapshot = _source_snapshot(connection)
        if snapshot['state_digest'] != expected_digest:
            raise WorkflowError('source_state_changed')
        payload = snapshot['http_state']
        if review_restore:
            if not snapshot['review_required']:
                raise WorkflowError('source_review_not_required')
            for values in payload['providers'].values():
                _check_elapsed(values, now)
            connection.execute("INSERT OR REPLACE INTO meta VALUES ('source_review_required','0')")
            kind = 'restored_sources_review'
        else:
            values = payload['providers'].get(provider)
            if values is not None:
                _check_elapsed(values, now)
            client = SafeHttpClient(now=lambda: now)
            client.import_state(payload)
            client.resume_provider(provider)
            state = client.export_state()['providers'][provider]
            connection.execute('UPDATE automation_http_state SET state_json=? WHERE provider=?',
                               (canonical_json(state), provider))
            kind = 'source_resume'
        connection.execute('''INSERT INTO operational_control_events
            (kind,provider,reason_code,state_digest,created_at) VALUES (?,?,?,?,?)''',
            (kind, provider, reason_code, expected_digest, now.isoformat()))
        return _source_snapshot(connection)


def health(path, max_age_seconds=86400, *, now=None):
    if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise WorkflowError('invalid_health_age')
    result = {'healthy': False, 'code': 'database_unavailable'}
    try:
        requested_now = now
        now = _date((now or datetime.now(timezone.utc)).isoformat())
        lock_path = Path(path).with_name('automation.lock')
        lock_before = probe_run_lock(lock_path)
        database = ReadOnlyDatabase(path)
        with database._connection() as connection:
            connection.execute('BEGIN')
            if connection.execute('PRAGMA quick_check(1)').fetchone()[0] != 'ok':
                return {**result, 'code': 'database_integrity'}
            version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if not version or version[0] != str(SCHEMA_VERSION):
                return {**result, 'code': 'schema_upgrade_required'}
            last = connection.execute('SELECT id,status,started_at,finished_at FROM automation_runs ORDER BY started_at DESC,id DESC LIMIT 1').fetchone()
            success = connection.execute("SELECT id,finished_at FROM automation_runs WHERE status='success' ORDER BY finished_at DESC,id DESC LIMIT 1").fetchone()
            failure = connection.execute("SELECT id,status,finished_at FROM automation_runs WHERE status NOT IN ('success','running') ORDER BY finished_at DESC,id DESC LIMIT 1").fetchone()
            source_rows = connection.execute('''SELECT provider,failures,last_status,last_success,last_failure
                FROM automation_source_health ORDER BY provider''').fetchall()
            snapshot = _source_snapshot(connection)
        if last is None:
            return {**result, 'code': 'no_runs'}
        now = _date((requested_now or datetime.now(timezone.utc)).isoformat())
        age = ((now - _date(last['finished_at'])).total_seconds()
               if last['finished_at'] else None)
        lock = probe_run_lock(lock_path)
        # Completion can commit and release the mutex between our database
        # snapshot and the second probe. A legitimate holder observed during
        # this check proves activity at its snapshot boundary; do not turn that
        # normal transition into an abandoned-process alarm.
        if last['status'] == 'running' and lock['state'] == 'free' and lock_before['state'] == 'held':
            lock = lock_before
        execution = {'state': 'idle', 'lock': lock['state'], 'age_seconds': age}
        valid = last['status'] == 'success' and age is not None and 0 <= age <= max_age_seconds
        code = 'ok' if valid else 'stale' if last['status'] == 'success' else 'run_unhealthy'
        if last['status'] == 'running':
            elapsed = (now - _date(last['started_at'])).total_seconds()
            metadata = lock['metadata']
            active = False
            delayed = False
            if lock['state'] == 'held' and isinstance(metadata, dict) and set(metadata) == {
                    'version', 'acquired_at', 'budget_seconds'}:
                budget = metadata['budget_seconds']
                if (type(metadata['version']) is int and metadata['version'] == 1
                        and type(budget) in (int, float) and math.isfinite(budget)
                        and 0 < budget <= 86400):
                    try:
                        acquired = _date(metadata['acquired_at'])
                    except (ValueError, TypeError, OverflowError):
                        acquired = None
                    if acquired is not None and acquired <= _date(last['started_at']) <= now:
                        active = 0 <= (now - acquired).total_seconds() <= budget + 30
                        delayed = not active
            code = ('active' if active else 'delayed' if delayed else
                    'abandoned' if lock['state'] == 'free' else 'lock_unknown')
            valid = active
            execution = {'state': code, 'lock': lock['state'], 'age_seconds': elapsed}
        providers = snapshot['http_state']['providers']
        degraded = any(row['failures'] > 0 for row in source_rows) or any(
            values.get('suspension') is not None or values['failures'] > 0
            for values in providers.values())
        if valid and snapshot['review_required']:
            valid, code = False, 'source_review_required'
        elif valid and degraded:
            valid, code = False, 'source_degraded'
        successful = None if success is None else {
            'run_id': success['id'], 'finished_at': success['finished_at'],
            'stale': not 0 <= (now - _date(success['finished_at'])).total_seconds() <= max_age_seconds}
        failed = None if failure is None else {
            'run_id': failure['id'], 'status': failure['status'], 'finished_at': failure['finished_at']}
        return {'healthy': valid, 'code': code,
                'last_run_id': last['id'], 'last_status': last['status'],
                'last_success': successful, 'last_failure': failed, 'execution': execution,
                'sources': [dict(row) for row in source_rows],
                'http_states': [{'source': name, **values} for name, values in providers.items()],
                'source_review_required': snapshot['review_required']}
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, SourceError):
        return result


@contextmanager
def _signals(cancelled):
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for name in ('SIGINT', 'SIGTERM'):
            number = getattr(signal, name, None)
            if number is not None:
                previous[number] = signal.signal(number, lambda *_: cancelled.set())
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _run(args, home):
    if not math.isfinite(args.budget_seconds) or not 0.05 <= args.budget_seconds <= 86400:
        raise WorkflowError('invalid_run_budget')
    cancelled = threading.Event()
    control = RunControl(args.budget_seconds, cancelled=cancelled)
    require_dry_run()
    private_directory(home)
    # No default-profile fallback and no rewriting malformed private inputs.
    try:
        profile = CandidateProfile.from_dict(_read_object(home / 'profile.json', 512 * 1024, private=True))
    except (OSError, ValueError, TypeError, UnicodeError):
        raise WorkflowError('invalid_automation_profile') from None
    configs, policy = load_source_config(args.config)
    with _signals(cancelled), RunLock(home / 'automation.lock', budget_seconds=args.budget_seconds):
        control.check()
        database = ApplicationDatabase(home / 'applications.sqlite3', timeout=0.1, control=control)
        def log(record):
            print(json.dumps(record, ensure_ascii=True, allow_nan=False), file=sys.stderr, flush=True)
        runner = AutomationRunner(database, profile, configs, policy,
                                  control=control, language=args.language, log=log)
        result = runner.run()
        code = {'success': 0, 'partial': 1, 'failed': 1, 'deadline': 4, 'interrupted': 130}[result['status']]
        return code, result


def dispatch_automation(args):
    try:
        home = _private_home()
        path = home / 'applications.sqlite3'
        if args.automation_command == 'run':
            code, result = _run(args, home)
        elif args.automation_command == 'health':
            result = health(path, args.max_age_seconds)
            code = 0 if result['healthy'] else 1
        elif args.automation_command in ('resume-source', 'review-restored-sources'):
            require_dry_run()
            private_directory(home)
            with RunLock(home / 'automation.lock'):
                database = ApplicationDatabase(path, timeout=0.1)
                result = recover_sources(database, expected_digest=args.state_digest,
                    reason_code=args.reason_code, provider=getattr(args, 'provider', None),
                    review_restore=args.automation_command == 'review-restored-sources')
            code = 0
        else:
            database = ReadOnlyDatabase(path)
            with database._connection() as connection:
                marker = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                if not marker or marker[0] != str(SCHEMA_VERSION):
                    raise WorkflowError('schema_upgrade_required')
            store = AutomationStore(database)
            result = (source_state(database) if args.automation_command == 'sources' else
                      store.history(args.limit) if args.automation_command == 'runs' else store.show(args.run_id))
            code = 0
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return code
    except WorkflowError as error:
        print(json.dumps({'event': 'automation_error', 'code': error.code}), file=sys.stderr)
        return 3 if error.code == 'run_locked' else 2
    except SourceError as error:
        code = error.code if error.code in (
            'run_cancelled', 'run_deadline', 'retry_after_active', 'retry_after_unbounded',
            'source_not_suspended', 'invalid_http_state') else 'automation_source_error'
        print(json.dumps({'event': 'automation_error', 'code': code}), file=sys.stderr)
        return 130 if code == 'run_cancelled' else 4 if code == 'run_deadline' else 2
    except (OSError, ValueError, TypeError, sqlite3.Error):
        print(json.dumps({'event': 'automation_error', 'code': 'automation_configuration_or_storage_error'}), file=sys.stderr)
        return 2
