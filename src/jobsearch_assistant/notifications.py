"""Transactional private outbox with conservative recovery of remote effects."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from .runtime_control import BoundedTransport, RunControl, RunLock
from .sources.models import HttpResponse, SourceError
from .telegram import TelegramConfig, TelegramRequest, format_event, validate_event
from .workflow_contracts import WorkflowError


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_notification_tables(connection: sqlite3.Connection) -> None:
    """Create additive schema inside the caller's migration transaction."""
    connection.execute('''
        CREATE TABLE IF NOT EXISTS notification_outbox (
            id INTEGER PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK(kind IN (
                'priority','review_pending','eligibility_pending',
                'source_error','recovered','run_summary')),
            entity_id INTEGER CHECK(entity_id IS NULL OR entity_id > 0),
            event_count INTEGER NOT NULL CHECK(event_count >= 0),
            language TEXT NOT NULL CHECK(language IN ('es','en')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','sending','sent','failed','uncertain')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
            not_before REAL NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE INDEX IF NOT EXISTS notification_outbox_pending
        ON notification_outbox(status, id)
    ''')
    # One configured chat per database. A shared cooldown is conservative even
    # if an operator changes that chat or rotates the bot token.
    connection.execute('''
        CREATE TABLE IF NOT EXISTS notification_delivery_state (
            id INTEGER PRIMARY KEY CHECK(id=1),
            next_allowed_at REAL NOT NULL DEFAULT 0
        )
    ''')
    connection.execute('INSERT OR IGNORE INTO notification_delivery_state(id) VALUES (1)')


def queue_event(connection: sqlite3.Connection, key: str, kind: str, *,
                entity_id: int | None = None, count: int = 1, language: str = 'es') -> bool:
    """Queue once without committing the caller's vacancy/evaluation transaction."""
    validate_event(kind, entity_id, count, language)
    if not isinstance(key, str) or not key or len(key) > 1024:
        raise WorkflowError('invalid_notification_key')
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
    now = _timestamp()
    cursor = connection.execute('''
        INSERT INTO notification_outbox(event_key,kind,entity_id,event_count,language,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?) ON CONFLICT(event_key) DO NOTHING
    ''', (digest, kind, entity_id, count, language, now, now))
    return cursor.rowcount == 1


def invalidate_restored_notifications(connection: sqlite3.Connection) -> None:
    """A backup cannot establish whether old pending intents reached Telegram."""
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notification_outbox'"
    ).fetchone()
    if exists:
        connection.execute("""
            UPDATE notification_outbox SET status='uncertain',last_error='notification_restored',updated_at=?
            WHERE status IN ('pending','sending')
        """, (_timestamp(),))


class _CombinedControl:
    def __init__(self, local, external):
        self.local, self.external = local, external

    def check(self):
        self.local.check()
        if self.external is not None:
            self.external.check()

    def remaining(self):
        remaining = self.local.remaining()
        return remaining if self.external is None else min(remaining, self.external.remaining())

    def sleep(self, delay):
        self.check()
        if delay >= self.remaining():
            raise SourceError('run_deadline')
        (self.local if self.external is None else self.external).sleep(delay)
        self.check()


def _json_object(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError()
        data[key] = value
    return data


def _invalid_constant(_):
    raise ValueError()


def _retry_delay(payload, headers, now):
    delays = []
    parameters = payload.get('parameters', {})
    if not isinstance(parameters, dict):
        raise TypeError()
    if 'retry_after' in parameters:
        value = parameters['retry_after']
        if type(value) is not int or value < 0:
            raise ValueError()
        delays.append(float(value))
    if 'retry-after' in headers:
        value = headers['retry-after']
        if not isinstance(value, str):
            raise ValueError()
        if re.fullmatch(r'[0-9]+', value.strip()):
            delay = float(value.strip())
        else:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                raise ValueError()
            delay = max(0.0, parsed.timestamp() - now)
        delays.append(delay)
    if not delays or not all(math.isfinite(delay) for delay in delays):
        raise ValueError()
    delay = max(delays)
    if not math.isfinite(now + delay):
        raise ValueError()
    return delay


def _classify(response, max_bytes, now):
    if (not isinstance(response, HttpResponse) or type(response.status) is not int
            or not isinstance(response.body, bytes) or len(response.body) > max_bytes):
        return 'uncertain', 'telegram_invalid_response', 0
    if 300 <= response.status < 400:
        return 'uncertain', 'telegram_unsafe_redirect', 0
    if 500 <= response.status <= 599:
        return 'uncertain', 'telegram_ambiguous_response', 0
    try:
        headers = {key.lower(): value for key, value in response.headers.items()}
        if (headers.get('content-encoding', 'identity').lower() != 'identity'
                or headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json'):
            raise ValueError()
        payload = json.loads(response.body.decode('utf-8'), object_pairs_hook=_json_object,
                             parse_constant=_invalid_constant)
        if not isinstance(payload, dict):
            raise TypeError()
        if response.status == 200 and payload.get('ok') is True:
            result = payload.get('result')
            if (isinstance(result, dict) and type(result.get('message_id')) is int
                    and result['message_id'] > 0):
                return 'sent', None, 0
            raise ValueError()
        code = payload.get('error_code')
        if (payload.get('ok') is not False or type(code) is not int
                or not 400 <= code <= 499 or response.status not in (200, code)):
            raise ValueError()
        if code == 429:
            try:
                delay = _retry_delay(payload, headers, now)
            except (ValueError, TypeError, OverflowError, OSError):
                return 'failed', 'telegram_invalid_retry_after', 0
            return 'pending', 'telegram_rate_limited', now + delay
        return 'failed', 'telegram_rejected', 0
    except (ValueError, TypeError, UnicodeError, RecursionError, AttributeError):
        return 'uncertain', 'telegram_invalid_response', 0


class NotificationDispatcher:
    """Serialize drains with an OS lock, reserve in SQLite, then perform I/O.

    ``transport`` injects an offline callable(config,text,timeout,max_bytes).
    Production calls always execute inside the runtime's terminable subprocess.
    A durable 'sending' intent is never automatically replayed after a crash.
    """

    def __init__(self, database, config: TelegramConfig, *, transport=None, control=None):
        self.path = Path(database.path)
        self.config, self.transport, self.control = config, transport, control

    @contextmanager
    def _connection(self, control):
        control.check()
        connection = sqlite3.connect(self.path, timeout=max(0, min(0.1, control.remaining())))
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _pending(self, connection):
        return int(connection.execute(
            "SELECT COUNT(*) FROM notification_outbox WHERE status='pending'"
        ).fetchone()[0])

    def _claim(self, connection, control):
        control.check()
        now = time.time()
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            cursor = connection.execute("""
                UPDATE notification_outbox SET status='failed',last_error='telegram_attempt_limit',updated_at=?
                WHERE status='pending' AND attempts>=?
            """, (_timestamp(), self.config.max_attempts))
            exhausted = cursor.rowcount
            row = connection.execute("""
                SELECT * FROM notification_outbox WHERE status='pending' ORDER BY id LIMIT 1
            """).fetchone()
            if row is None:
                return None, 0, exhausted
            state = connection.execute(
                'SELECT next_allowed_at FROM notification_delivery_state WHERE id=1'
            ).fetchone()
            delay = max(0, row['not_before'] - now, state[0] - now)
            if delay > 0:
                return None, delay, exhausted
            control.check()
            connection.execute("""
                UPDATE notification_outbox SET status='sending',attempts=attempts+1,updated_at=?
                WHERE id=? AND status='pending'
            """, (_timestamp(), row['id']))
            connection.execute('UPDATE notification_delivery_state SET next_allowed_at=? WHERE id=1',
                               (now + self.config.min_interval,))
            return dict(row), 0, exhausted

    def _finish(self, connection, row, status, error, not_before):
        if status == 'pending' and row['attempts'] + 1 >= self.config.max_attempts:
            status, error = 'failed', 'telegram_attempt_limit'
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('''
                UPDATE notification_outbox SET status=?,last_error=?,not_before=?,updated_at=?
                WHERE id=? AND status='sending'
            ''', (status, error, not_before, _timestamp(), row['id']))
            if not_before:
                connection.execute('''
                    UPDATE notification_delivery_state SET next_allowed_at=MAX(next_allowed_at,?) WHERE id=1
                ''', (not_before,))
        return status

    def drain(self, authorized: bool = False) -> dict:
        metrics = {'status': 'complete', 'attempted': 0, 'sent': 0,
                   'failed': 0, 'uncertain': 0, 'pending': 0}
        if authorized is not True:
            return {**metrics, 'status': 'unauthorized'}
        if not self.config.enabled:
            return {**metrics, 'status': 'disabled'}
        if not self.config.configured:
            return {**metrics, 'status': 'unconfigured'}
        control = _CombinedControl(RunControl(self.config.budget_seconds), self.control)
        lockpath = self.path.with_name(self.path.name + '.notifications.lock')
        try:
            control.check()
            with RunLock(lockpath), self._connection(control) as connection:
                with connection:
                    connection.execute('BEGIN IMMEDIATE')
                    cursor = connection.execute("""
                        UPDATE notification_outbox SET status='uncertain',last_error='notification_interrupted',updated_at=?
                        WHERE status='sending'
                    """, (_timestamp(),))
                    metrics['uncertain'] += cursor.rowcount
                try:
                    while metrics['attempted'] < self.config.max_messages:
                        row, delay, exhausted = self._claim(connection, control)
                        metrics['failed'] += exhausted
                        if delay:
                            if delay >= control.remaining():
                                metrics['status'] = 'deferred'
                                break
                            control.sleep(delay)
                            continue
                        if row is None:
                            break
                        metrics['attempted'] += 1
                        try:
                            text = format_event(row['kind'], entity_id=row['entity_id'],
                                                count=row['event_count'], language=row['language'])
                            control.check()
                            timeout = min(self.config.timeout, control.remaining())
                            if self.transport is None:
                                response = BoundedTransport(control, transport=TelegramRequest(self.config, text))(
                                    'https://api.telegram.org/', timeout, self.config.max_response_bytes)
                            else:
                                response = self.transport(self.config, text, timeout, self.config.max_response_bytes)
                            status, error, not_before = _classify(response, self.config.max_response_bytes, time.time())
                        except Exception as caught:  # noqa: BLE001 - never expose a transport's private exception
                            status, not_before = 'uncertain', 0
                            code = getattr(caught, 'code', None)
                            if code in ('run_cancelled', 'run_deadline'):
                                metrics['status'] = code
                            error = 'telegram_delivery_uncertain'
                        status = self._finish(connection, row, status, error, not_before)
                        if status in ('sent', 'failed', 'uncertain'):
                            metrics[status] += 1
                        if status == 'pending':
                            metrics['status'] = 'deferred'
                            break
                        if metrics['status'] in ('run_cancelled', 'run_deadline'):
                            break
                    else:
                        metrics['status'] = 'limited'
                except SourceError as error:
                    metrics['status'] = error.code if error.code in ('run_deadline', 'run_cancelled') else 'notification_error'
                finally:
                    metrics['pending'] = self._pending(connection)
        except WorkflowError as error:
            metrics['status'] = 'notification_locked' if error.code == 'run_locked' else 'notification_error'
        except SourceError as error:
            metrics['status'] = error.code if error.code in ('run_deadline', 'run_cancelled') else 'notification_error'
        except (sqlite3.Error, OSError):
            metrics['status'] = 'notification_storage_error'
        return metrics
