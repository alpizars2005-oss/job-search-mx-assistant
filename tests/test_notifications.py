import json
import multiprocessing
import sqlite3
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jobsearch_assistant.notifications import (
    NotificationDispatcher,
    create_notification_tables,
    invalidate_restored_notifications,
    queue_event,
)
from jobsearch_assistant.sources.models import HttpResponse
from jobsearch_assistant.telegram import TelegramConfig

CONFIG = TelegramConfig(enabled=True, token='123456:' + 'A' * 35, chat_id='-123456')


def response(status=200, payload=None, headers=None):
    if payload is None:
        payload = {'ok': True, 'result': {'message_id': 7}}
    return HttpResponse(status, headers or {'Content-Type': 'application/json'},
                        json.dumps(payload).encode())


class FakeControl:
    def __init__(self, remaining=60):
        self.seconds = remaining
        self.sleeps = []

    def check(self):
        if self.seconds <= 0:
            from jobsearch_assistant.sources.models import SourceError
            raise SourceError('run_deadline')

    def remaining(self):
        return self.seconds

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.seconds -= delay
        self.check()


class QueueTransport:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = []

    def __call__(self, config, text, timeout, max_bytes):
        self.calls.append((config, text, timeout, max_bytes))
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _blocked_dispatch(path, entered, released):
    def blocked(*args):
        entered.set()
        released.wait(15)
        return response()
    NotificationDispatcher(SimpleNamespace(path=Path(path)), CONFIG,
                           transport=blocked).drain(authorized=True)


def _queue_same_event(path, start, output):
    start.wait(8)
    connection = sqlite3.connect(path, timeout=2)
    try:
        with connection:
            result = queue_event(connection, 'same-event', 'priority', entity_id=42)
        output.put(result)
    finally:
        connection.close()


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'test.sqlite3'
        self.database = SimpleNamespace(path=self.path)
        with self.connection() as connection:
            create_notification_tables(connection)

    def connection(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        return connection

    def queue(self, key='event-1', kind='priority', **kwargs):
        with self.connection() as connection:
            return queue_event(connection, key, kind, **kwargs)

    def rows(self):
        return self.connection().execute('SELECT * FROM notification_outbox ORDER BY id').fetchall()

    def dispatch(self, transport, config=CONFIG, control=None, authorized=True):
        return NotificationDispatcher(self.database, config, transport=transport,
                                      control=control).drain(authorized=authorized)

    def test_queue_is_transactional_unique_and_private(self):
        self.assertTrue(self.queue('private-cv@example.invalid', entity_id=4))
        self.assertFalse(self.queue('private-cv@example.invalid', entity_id=4))
        self.assertEqual(len(self.rows()), 1)
        self.assertNotIn('private-cv', repr(dict(self.rows()[0])))
        with self.assertRaises(RuntimeError), self.connection() as connection:
            queue_event(connection, 'rollback', 'run_summary', count=0)
            raise RuntimeError()
        self.assertEqual(len(self.rows()), 1)

    def test_only_static_kinds_integer_ids_and_counts_are_accepted(self):
        for kwargs in ({'kind': 'private-cv'}, {'entity_id': 'private-cv'},
                       {'entity_id': True}, {'entity_id': -1}, {'count': True},
                       {'count': -1}, {'language': 'private-cv'}):
            options = {'kind': 'priority', **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError) as caught:
                self.queue(**options)
            self.assertNotIn('private-cv', str(caught.exception))
        self.assertEqual(self.rows(), [])

    def test_authorization_enabled_and_configuration_are_all_required(self):
        self.queue()
        transport = QueueTransport()
        cases = [(CONFIG, False, 'unauthorized'),
                 (replace(CONFIG, enabled=False), True, 'disabled'),
                 (replace(CONFIG, token=''), True, 'unconfigured'),
                 (replace(CONFIG, chat_id=''), True, 'unconfigured')]
        for config, authorized, status in cases:
            with self.subTest(status=status):
                self.assertEqual(self.dispatch(transport, config, authorized=authorized)['status'], status)
        self.assertEqual(transport.calls, [])
        self.assertEqual(self.rows()[0]['attempts'], 0)

    def test_success_persists_and_restart_does_not_send_twice(self):
        self.queue(entity_id=17)
        transport = QueueTransport(response())
        metrics = self.dispatch(transport)
        self.assertEqual((metrics['attempted'], metrics['sent'], metrics['pending']), (1, 1, 0))
        self.dispatch(transport)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(self.rows()[0]['status'], 'sent')
        self.assertIn('17', transport.calls[0][1])
        self.assertNotIn(CONFIG.token, repr(metrics))
        self.assertNotIn(CONFIG.chat_id, repr(metrics))

    def test_intent_and_interval_are_committed_before_network(self):
        self.queue()
        def inspect(*args):
            row = self.rows()[0]
            self.assertEqual((row['status'], row['attempts']), ('sending', 1))
            state = self.connection().execute('SELECT next_allowed_at FROM notification_delivery_state').fetchone()
            self.assertGreater(state[0], time.time() + 2.5)
            return response()
        self.assertEqual(self.dispatch(inspect)['sent'], 1)

    def test_timeout_5xx_malformed_and_redirect_are_ambiguous_without_retry(self):
        cases = [TimeoutError('private-cv token'), response(503), response(302),
                 response(200, {'ok': True}), response(200, {'ok': 1, 'result': {}}),
                 response(200, {'ok': True, 'result': {'message_id': True}}),
                 HttpResponse(200, {'Content-Type': 'application/json'}, b'private-cv')]
        for index, item in enumerate(cases):
            self.queue(f'event-{index}')
            transport = QueueTransport(item)
            with patch('jobsearch_assistant.notifications.time.time', return_value=10000 + index * 10):
                metrics = self.dispatch(transport)
                self.dispatch(transport)
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(metrics['uncertain'], 1)
            self.assertEqual(self.rows()[-1]['status'], 'uncertain')
            self.assertNotIn('private-cv', repr(dict(self.rows()[-1])))

    def test_429_retry_after_is_durable_and_never_shortened(self):
        self.queue()
        transport = QueueTransport(response(429, {'ok': False, 'error_code': 429,
                                                 'parameters': {'retry_after': 7200}},
                                           {'Content-Type': 'application/json', 'Retry-After': '8000'}))
        with patch('jobsearch_assistant.notifications.time.time', return_value=10000):
            metrics = self.dispatch(transport, replace(CONFIG, budget_seconds=1))
        self.assertEqual(metrics['pending'], 1)
        row = self.rows()[0]
        self.assertGreaterEqual(row['not_before'], 18000)
        with patch('jobsearch_assistant.notifications.time.time', return_value=17000):
            self.assertEqual(self.dispatch(transport, replace(CONFIG, budget_seconds=1))['status'], 'deferred')
        self.assertEqual(len(transport.calls), 1)
        success = QueueTransport(response())
        with patch('jobsearch_assistant.notifications.time.time', return_value=18001):
            self.assertEqual(self.dispatch(success)['sent'], 1)

    def test_retry_after_http_date_and_invalid_rate_limit_remain_safe(self):
        self.queue()
        transport = QueueTransport(response(429, {'ok': False, 'error_code': 429},
                                           {'Content-Type': 'application/json',
                                            'Retry-After': 'Thu, 01 Jan 1970 05:00:00 GMT'}))
        with patch('jobsearch_assistant.notifications.time.time', return_value=10000):
            self.dispatch(transport, replace(CONFIG, budget_seconds=1))
        self.assertGreaterEqual(self.rows()[0]['not_before'], 18000)
        self.queue('invalid-retry')
        with patch('jobsearch_assistant.notifications.time.time', return_value=20000):
            invalid = QueueTransport(response(429, {'ok': False, 'error_code': 429,
                                                   'parameters': {'retry_after': 'private-cv'}}))
            self.dispatch(invalid, replace(CONFIG, max_messages=1))
        self.assertEqual(self.rows()[0]['status'], 'failed')
        self.assertNotIn('private-cv', repr([dict(row) for row in self.rows()]))

    def test_per_chat_spacing_survives_restart_and_budget_defers(self):
        self.queue('one')
        self.queue('two')
        first = QueueTransport(response())
        with patch('jobsearch_assistant.notifications.time.time', return_value=10000):
            metrics = self.dispatch(first, replace(CONFIG, budget_seconds=1))
            self.assertEqual(metrics['status'], 'deferred')
            self.assertEqual(metrics['pending'], 1)
            second = QueueTransport()
            self.assertEqual(self.dispatch(second, replace(CONFIG, budget_seconds=1))['attempted'], 0)
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(second.calls, [])

    def test_max_messages_and_max_attempts_are_finite(self):
        self.queue('one')
        self.queue('two')
        transport = QueueTransport(response(429, {'ok': False, 'error_code': 429,
                                                 'parameters': {'retry_after': 4}}))
        with patch('jobsearch_assistant.notifications.time.time', return_value=10000):
            metrics = self.dispatch(transport, replace(CONFIG, max_messages=1, max_attempts=1))
        self.assertEqual((metrics['attempted'], metrics['failed'], metrics['pending']), (1, 1, 1))
        self.assertEqual(self.rows()[0]['status'], 'failed')
        self.assertEqual(self.rows()[1]['status'], 'pending')
        with patch('jobsearch_assistant.notifications.time.time', return_value=10002):
            next_transport = QueueTransport()
            self.assertEqual(self.dispatch(next_transport, replace(CONFIG, budget_seconds=1))['attempted'], 0)
            self.assertEqual(next_transport.calls, [])

    def test_definitive_permanent_rejection_is_failed_without_retry(self):
        self.queue()
        transport = QueueTransport(response(403, {'ok': False, 'error_code': 403,
                                                 'description': 'private-cv'}))
        metrics = self.dispatch(transport)
        self.assertEqual((metrics['failed'], len(transport.calls)), (1, 1))
        self.assertEqual(self.rows()[0]['last_error'], 'telegram_rejected')

    def test_definitive_rate_limit_retries_stop_at_durable_attempt_limit(self):
        self.queue()
        transport = QueueTransport(*[response(429, {'ok': False, 'error_code': 429,
                                                  'parameters': {'retry_after': 4}})] * 3)
        for attempt in range(3):
            with patch('jobsearch_assistant.notifications.time.time', return_value=10000 + attempt * 10):
                metrics = self.dispatch(transport)
            self.assertEqual(self.rows()[0]['attempts'], attempt + 1)
            self.assertEqual(metrics['attempted'], 1)
        self.assertEqual(self.rows()[0]['status'], 'failed')
        self.dispatch(transport)
        self.assertEqual(len(transport.calls), 3)

    def test_restoration_guard_is_compatible_with_older_schema(self):
        connection = sqlite3.connect(':memory:')
        try:
            invalidate_restored_notifications(connection)
            self.assertEqual(connection.execute('SELECT name FROM sqlite_master').fetchall(), [])
        finally:
            connection.close()

    def test_prior_crash_and_restore_never_replay_ambiguous_intents(self):
        self.queue('sending')
        with self.connection() as connection:
            connection.execute("UPDATE notification_outbox SET status='sending',attempts=1")
        transport = QueueTransport()
        self.assertEqual(self.dispatch(transport)['uncertain'], 1)
        self.queue('pending')
        with self.connection() as connection:
            invalidate_restored_notifications(connection)
        self.dispatch(transport)
        self.assertTrue(all(row['status'] == 'uncertain' for row in self.rows()))
        self.assertEqual(transport.calls, [])

    def test_cancellation_before_claim_has_no_attempt(self):
        self.queue()
        metrics = self.dispatch(QueueTransport(), control=FakeControl(0))
        self.assertEqual(metrics['status'], 'run_deadline')
        self.assertEqual(self.rows()[0]['attempts'], 0)

    def test_production_transport_is_bounded_and_deadline_after_intent_is_uncertain(self):
        from jobsearch_assistant.sources.models import SourceError
        from jobsearch_assistant.telegram import TelegramRequest
        self.queue(entity_id=12)
        with patch('jobsearch_assistant.notifications.BoundedTransport') as bounded:
            bounded.return_value.side_effect = SourceError('run_deadline')
            metrics = NotificationDispatcher(self.database, CONFIG).drain(authorized=True)
        request = bounded.call_args.kwargs['transport']
        self.assertIsInstance(request, TelegramRequest)
        self.assertEqual(request.config, CONFIG)
        self.assertEqual(metrics['status'], 'run_deadline')
        self.assertEqual(metrics['uncertain'], 1)
        self.assertEqual(self.rows()[0]['status'], 'uncertain')
        self.assertEqual(self.rows()[0]['attempts'], 1)
        self.assertNotIn(CONFIG.token, repr(request))
        self.dispatch(QueueTransport())

    def test_cancelled_and_busy_storage_are_redacted(self):
        from jobsearch_assistant.sources.models import SourceError
        self.queue()
        control = FakeControl()
        control.check = lambda: (_ for _ in ()).throw(SourceError('run_cancelled'))
        self.assertEqual(self.dispatch(QueueTransport(), control=control)['status'], 'run_cancelled')
        connection = self.connection()
        connection.execute('BEGIN IMMEDIATE')
        started = time.monotonic()
        metrics = self.dispatch(QueueTransport())
        self.assertEqual(metrics['status'], 'notification_storage_error')
        self.assertLess(time.monotonic() - started, 0.5)
        connection.rollback()

    def test_spacing_is_enforced_between_two_deliveries(self):
        self.queue('first')
        self.queue('second')
        starts = []
        def transport(*args):
            starts.append(time.monotonic())
            return response()
        metrics = self.dispatch(transport, replace(CONFIG, budget_seconds=8, max_messages=2))
        self.assertEqual(metrics['sent'], 2)
        self.assertGreaterEqual(starts[1] - starts[0], 3.09)

    def test_two_processes_queue_same_event_once(self):
        context = multiprocessing.get_context('spawn')
        start, output = context.Event(), context.Queue()
        processes = [context.Process(target=_queue_same_event,
                                     args=(str(self.path), start, output)) for _ in range(2)]
        for process in processes:
            process.start()
        try:
            start.set()
            results = [output.get(timeout=8), output.get(timeout=8)]
            self.assertEqual(sorted(results), [False, True])
        finally:
            for process in processes:
                process.join(5)
                if process.is_alive():
                    process.terminate()
                    process.join(5)
            output.close()
            output.join_thread()
        self.assertTrue(all(process.exitcode == 0 for process in processes))
        self.assertEqual(len(self.rows()), 1)

    def test_two_processes_cannot_send_same_event_and_kill_is_recovered(self):
        self.queue()
        context = multiprocessing.get_context('spawn')
        entered, released = context.Event(), context.Event()
        process = context.Process(target=_blocked_dispatch, args=(str(self.path), entered, released))
        process.start()
        try:
            self.assertTrue(entered.wait(8))
            transport = QueueTransport()
            self.assertEqual(self.dispatch(transport)['status'], 'notification_locked')
            self.assertEqual(transport.calls, [])
            self.assertEqual(self.rows()[0]['status'], 'sending')
        finally:
            process.terminate()
            process.join(5)
        metrics = self.dispatch(QueueTransport())
        self.assertEqual(metrics['uncertain'], 1)
        self.assertEqual(self.rows()[0]['status'], 'uncertain')


if __name__ == '__main__':
    unittest.main()
