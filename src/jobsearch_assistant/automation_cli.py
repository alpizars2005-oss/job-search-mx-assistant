"""One-shot and read-only operational commands, with redacted JSON output."""
from __future__ import annotations

import json
import math
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
from .notifications import NotificationDispatcher, notification_problem
from .runtime_control import RunControl, RunLock
from .sources.config import load_source_config
from .sources.models import SourceError
from .telegram import load_telegram_config
from .workflow_cli import _read_object
from .workflow_contracts import WorkflowError, require_dry_run


def add_automation_parsers(sub):
    operations = sub.add_parser('automation', help='Run once or inspect redacted local operational state')
    commands = operations.add_subparsers(dest='automation_command', required=True)
    run = commands.add_parser('run', help='Discover and evaluate once; never prepare or submit candidacies')
    run.add_argument('--config', type=Path)
    run.add_argument('--budget-seconds', type=float, default=120)
    run.add_argument('--notify', action='store_true', help='Explicitly authorize configured minimal Telegram notifications')
    run.add_argument('--language', choices=('es', 'en'), default='es')
    health = commands.add_parser('health', help='Read-only SQLite, last run and source diagnostics')
    health.add_argument('--max-age-seconds', type=float, default=86400)
    runs = commands.add_parser('runs', help='List redacted run summaries')
    runs.add_argument('--limit', type=int, default=20)
    show = commands.add_parser('show', help='Read one redacted run summary')
    show.add_argument('run_id')


def _private_home():
    home = data_home()
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
        connection = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.1)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()


def health(path, max_age_seconds=86400):
    if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise WorkflowError('invalid_health_age')
    result = {'healthy': False, 'code': 'database_unavailable'}
    try:
        database = ReadOnlyDatabase(path)
        with database._connection() as connection:
            if connection.execute('PRAGMA quick_check(1)').fetchone()[0] != 'ok':
                return {**result, 'code': 'database_integrity'}
            version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if not version or version[0] != str(SCHEMA_VERSION):
                return {**result, 'code': 'schema_upgrade_required'}
            last = connection.execute('SELECT id,status,finished_at FROM automation_runs ORDER BY started_at DESC,id DESC LIMIT 1').fetchone()
            source_rows = connection.execute('''SELECT provider,failures,last_status,last_success,last_failure
                FROM automation_source_health ORDER BY provider''').fetchall()
            states = connection.execute('SELECT provider,state_json FROM automation_http_state ORDER BY provider').fetchall()
            pending = dict(connection.execute('SELECT status,COUNT(*) FROM notification_outbox GROUP BY status').fetchall())
            delivery = connection.execute('SELECT run_id,metrics_json,updated_at FROM automation_notification_health WHERE id=1').fetchone()
        if last is None:
            return {**result, 'code': 'no_runs'}
        age = ((datetime.now(timezone.utc) - datetime.fromisoformat(last['finished_at'])).total_seconds()
               if last['finished_at'] else None)
        valid = last['status'] == 'success' and age is not None and 0 <= age <= max_age_seconds
        delivery_result = None if delivery is None else {
            'run_id': delivery['run_id'], 'updated_at': delivery['updated_at'],
            **json.loads(delivery['metrics_json'])}
        delivery_bad = delivery_result is not None and notification_problem(delivery_result)
        return {'healthy': valid and not delivery_bad,
                'code': 'run_unhealthy' if not valid else 'notification_unhealthy' if delivery_bad else 'ok',
                'last_run_id': last['id'], 'last_status': last['status'],
                'sources': [dict(row) for row in source_rows],
                'http_states': [{'source': r['provider'], **json.loads(r['state_json'])} for r in states],
                'notifications': pending, 'last_delivery': delivery_result}
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
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
    # No default-profile fallback and no rewriting malformed private inputs.
    try:
        profile = CandidateProfile.from_dict(_read_object(home / 'profile.json', 512 * 1024))
    except (OSError, ValueError, TypeError, UnicodeError):
        raise WorkflowError('invalid_automation_profile') from None
    configs, policy = load_source_config(args.config)
    telegram = load_telegram_config() if args.notify else None
    with _signals(cancelled), RunLock(home / 'automation.lock'):
        control.check()
        database = ApplicationDatabase(home / 'applications.sqlite3', timeout=0.1, control=control)
        def log(record):
            print(json.dumps(record, ensure_ascii=True, allow_nan=False), file=sys.stderr, flush=True)
        runner = AutomationRunner(database, profile, configs, policy,
                                  control=control, language=args.language, log=log)
        result = runner.run()
        if args.notify:
            result['notifications'] = NotificationDispatcher(database, telegram, control=control).drain(authorized=True)
            runner.store.record_notifications(result['run_id'], result['notifications'])
        code = {'success': 0, 'partial': 1, 'failed': 1, 'deadline': 4, 'interrupted': 130}[result['status']]
        delivery = result.get('notifications')
        if delivery is not None:
            if delivery['status'] == 'run_cancelled':
                code = 130
            elif delivery['status'] == 'run_deadline' and code != 130:
                code = 4
            elif notification_problem(delivery) and code == 0:
                code = 1
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
        else:
            database = ReadOnlyDatabase(path)
            with database._connection() as connection:
                marker = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                if not marker or marker[0] != str(SCHEMA_VERSION):
                    raise WorkflowError('schema_upgrade_required')
            store = AutomationStore(database)
            result = store.history(args.limit) if args.automation_command == 'runs' else store.show(args.run_id)
            code = 0
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return code
    except WorkflowError as error:
        print(json.dumps({'event': 'automation_error', 'code': error.code}), file=sys.stderr)
        return 3 if error.code == 'run_locked' else 2
    except SourceError as error:
        code = error.code if error.code in ('run_cancelled', 'run_deadline') else 'automation_source_error'
        print(json.dumps({'event': 'automation_error', 'code': code}), file=sys.stderr)
        return 130 if code == 'run_cancelled' else 4 if code == 'run_deadline' else 2
    except (OSError, ValueError, TypeError, sqlite3.Error):
        print(json.dumps({'event': 'automation_error', 'code': 'automation_configuration_or_storage_error'}), file=sys.stderr)
        return 2
