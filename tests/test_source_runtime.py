import copy
import importlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from jobsearch_assistant.sources.http import SafeHttpClient
from jobsearch_assistant.sources.models import HttpResponse, RequestPolicy, SourceError

URL = 'https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true'


class Clock:
    def __init__(self, seconds=0, monotonic_origin=0):
        self.seconds = seconds
        self.monotonic_origin = monotonic_origin
        self.sleeps = []

    def monotonic(self):
        return self.seconds + self.monotonic_origin

    def now(self):
        return datetime(2026, 11, 5, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.seconds += delay


class Responses:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, url, timeout, max_bytes):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def response(status=200, headers=None):
    return HttpResponse(status, headers or {'Content-Type': 'application/json'}, b'{"jobs":[]}')


class SourceRuntimeTests(unittest.TestCase):
    def client(self, clock, transport, **options):
        policy = options.pop('policy', RequestPolicy(max_retries=0, min_interval=0))
        return SafeHttpClient(policy, transport=transport, monotonic=clock.monotonic,
                              sleep=clock.sleep, now=clock.now, **options)

    def assert_code(self, code, function):
        with self.assertRaises(SourceError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)

    def test_received_retry_after_is_durable_before_deadline_or_cancellation(self):
        from jobsearch_assistant.runtime_control import RunControl
        for trigger in ('deadline', 'cancelled'):
            for status in (429, 503):
                with self.subTest(trigger=trigger, status=status):
                    clock, cancelled, persisted = Clock(), [False], []
                    control = RunControl(1, cancelled=lambda: cancelled[0], monotonic=clock.monotonic)
                    def transport(*args):
                        if trigger == 'deadline':
                            clock.seconds = 1.1
                        else:
                            cancelled[0] = True
                        return response(status, {'Retry-After': '3600'})
                    client = self.client(clock, transport, control=control, state_callback=persisted.append)
                    self.assert_code('run_deadline' if trigger == 'deadline' else 'run_cancelled',
                                     lambda: client.get_json('greenhouse', URL))
                    saved = persisted[-1]['providers']['greenhouse']
                    self.assertEqual(saved['failures'], 1)
                    self.assertGreaterEqual(datetime.fromisoformat(saved['not_before']),
                                            clock.now() + timedelta(seconds=3600))
                    transport_after_restart = Responses(response())
                    restarted = self.client(Clock(20), transport_after_restart,
                                            policy=RequestPolicy(max_retries=0, min_interval=0, max_wait=0))
                    restarted.import_state(persisted[-1])
                    self.assert_code('source_paused', lambda: restarted.get_json('greenhouse', URL))
                    self.assertEqual(transport_after_restart.calls, 0)

    def test_retry_after_survives_restart_without_restoring_run_quota(self):
        first_clock = Clock()
        first = self.client(first_clock, Responses(response(429, {'Retry-After': '10'})))
        self.assert_code('http_429', lambda: first.get_json('greenhouse', URL))
        payload = json.loads(json.dumps(first.export_state()))
        second_clock = Clock(3)
        transport = Responses(response())
        second = self.client(second_clock, transport)
        second.import_state(payload)
        self.assertEqual(second.request_counts['greenhouse'], 0)
        self.assertEqual(second.get_json('greenhouse', URL), {'jobs': []})
        self.assertEqual(second_clock.sleeps, [7])

    def test_error_threshold_cooldown_and_failures_survive_restart(self):
        clock = Clock()
        policy = RequestPolicy(max_retries=0, error_threshold=2, pause_seconds=20, min_interval=0)
        first = self.client(clock, Responses(response(503)), policy=policy)
        self.assert_code('http_503', lambda: first.get_json('greenhouse', URL))
        second = self.client(clock, Responses(response(503)), policy=policy)
        second.import_state(first.export_state())
        self.assert_code('http_503', lambda: second.get_json('greenhouse', URL))
        third = self.client(clock, Responses(response()), policy=policy)
        third.import_state(second.export_state())
        self.assert_code('source_paused', lambda: third.get_json('greenhouse', URL))
        clock.seconds = 21
        third.get_json('greenhouse', URL)
        self.assertEqual(third.export_state()['providers']['greenhouse']['failures'], 0)

    def test_minimum_interval_survives_process_clock_origin_change(self):
        first_clock = Clock(100)
        policy = RequestPolicy(max_retries=0, min_interval=5)
        first = self.client(first_clock, Responses(response()), policy=policy)
        first.get_json('greenhouse', URL)
        second_clock = Clock(102, monotonic_origin=-100)
        second = self.client(second_clock, Responses(response()), policy=policy)
        second.import_state(first.export_state())
        second.get_json('greenhouse', URL)
        self.assertEqual(second_clock.sleeps, [3])

    def test_reservation_persists_before_network_and_crash_delays_restart(self):
        clock = Clock()
        persisted = []

        def crash(url, timeout, max_bytes):
            self.assertEqual(len(persisted), 1)
            raise RuntimeError('synthetic crash')

        first = self.client(clock, crash, state_callback=lambda state: persisted.append(copy.deepcopy(state)))
        with self.assertRaisesRegex(RuntimeError, 'synthetic crash'):
            first.get_json('greenhouse', URL)
        self.assertEqual(persisted[0]['providers']['greenhouse']['failures'], 1)
        second_clock = Clock(1)
        second = self.client(second_clock, Responses(response()))
        second.import_state(persisted[0])
        second.get_json('greenhouse', URL)
        self.assertEqual(second_clock.sleeps, [14])

    def test_callback_failure_prevents_request(self):
        transport = Responses(response())

        def persist(_):
            raise RuntimeError('storage unavailable')

        client = self.client(Clock(), transport, state_callback=persist)
        with self.assertRaisesRegex(RuntimeError, 'storage unavailable'):
            client.get_json('greenhouse', URL)
        self.assertEqual(transport.calls, 0)

    def test_callbacks_capture_reservation_failure_retry_after_and_success(self):
        snapshots = []
        clock = Clock()
        client = self.client(clock, Responses(response(429, {'Retry-After': '3'}), response()),
                             state_callback=lambda state: snapshots.append(copy.deepcopy(state)),
                             policy=RequestPolicy(max_retries=1, min_interval=0))
        client.get_json('greenhouse', URL)
        self.assertGreaterEqual(len(snapshots), 4)
        self.assertTrue(any(item['providers']['greenhouse']['not_before'] == '2026-11-05T00:00:03+00:00'
                            for item in snapshots))
        self.assertEqual(snapshots[-1]['providers']['greenhouse']['failures'], 0)
        serialized = json.dumps(snapshots)
        self.assertNotIn(URL, serialized)
        self.assertNotIn('jobs', serialized)
        self.assertNotIn('requests', serialized)

    def test_invalid_retry_after_pause_is_persisted(self):
        snapshots = []
        client = self.client(Clock(), Responses(response(429, {'Retry-After': 'private-value'})),
                             state_callback=lambda state: snapshots.append(copy.deepcopy(state)))
        self.assert_code('invalid_retry_after', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(snapshots[-1]['providers']['greenhouse']['paused_until'], '2026-11-05T00:05:00+00:00')
        self.assertNotIn('private-value', json.dumps(snapshots))

    def test_quota_prevents_reservation_or_transport_on_next_board(self):
        snapshots = []
        transport = Responses(response(), response())
        client = self.client(Clock(), transport, state_callback=lambda state: snapshots.append(state),
                             policy=RequestPolicy(max_requests=1, max_retries=0, min_interval=0))
        client.get_json('greenhouse', URL)
        count = len(snapshots)
        self.assert_code('request_limit', lambda: client.get_json('greenhouse', URL.replace('/example/', '/other/')))
        self.assertEqual(transport.calls, 1)
        self.assertEqual(len(snapshots), count)

    def test_deadline_interrupts_backoff_before_retry(self):
        runtime = importlib.import_module('jobsearch_assistant.runtime_control')
        clock = Clock()
        control = runtime.RunControl(0.2, monotonic=clock.monotonic)
        transport = Responses(response(503), response())
        client = self.client(clock, transport, control=control,
                             policy=RequestPolicy(max_retries=1, min_interval=0))
        with patch.object(runtime.time, 'sleep', side_effect=clock.sleep):
            self.assert_code('run_deadline', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(transport.calls, 1)
        self.assertAlmostEqual(clock.seconds, 0.2)

    def test_cancelled_control_prevents_request_reservation(self):
        runtime = importlib.import_module('jobsearch_assistant.runtime_control')
        snapshots = []
        transport = Responses(response())
        client = self.client(Clock(), transport, control=runtime.RunControl(10, cancelled=lambda: True),
                             state_callback=lambda state: snapshots.append(state))
        self.assert_code('run_cancelled', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(transport.calls, 0)
        self.assertEqual(snapshots, [])

    def test_invalid_import_is_atomic_and_redacted(self):
        client = self.client(Clock(), Responses(response()))
        client.get_json('greenhouse', URL)
        previous = client.export_state()
        for payload in ({'version': 2, 'providers': {}}, {'version': 1, 'providers': {'private-value': {}}},
                        {'version': 1, 'providers': {'greenhouse': {'failures': True, 'paused_until': None, 'not_before': None}}}):
            with self.subTest(payload=payload):
                self.assert_code('invalid_http_state', lambda payload=payload: client.import_state(payload))
                self.assertEqual(client.export_state(), previous)

    def test_backoff_reservation_survives_restart_during_sleep(self):
        clock = Clock()
        snapshots = []

        def crash(delay):
            raise RuntimeError('crash during backoff')

        first = self.client(clock, Responses(response(503)),
                            policy=RequestPolicy(max_retries=1, min_interval=0, backoff_base=10),
                            state_callback=lambda state: snapshots.append(copy.deepcopy(state)),
                            random=lambda: 1)
        first.sleep = crash
        with self.assertRaisesRegex(RuntimeError, 'crash during backoff'):
            first.get_json('greenhouse', URL)
        second_clock = Clock(3)
        second = self.client(second_clock, Responses(response()))
        second.import_state(snapshots[-1])
        second.get_json('greenhouse', URL)
        self.assertEqual(second_clock.sleeps, [7])

    def test_failure_callback_never_temporarily_discards_retry_after(self):
        snapshots = []
        first = self.client(Clock(), Responses(response(429, {'Retry-After': '30'})),
                            state_callback=lambda state: snapshots.append(copy.deepcopy(state)))
        self.assert_code('http_429', lambda: first.get_json('greenhouse', URL))
        # Every committed post-response state must already include Retry-After.
        for snapshot in snapshots[1:]:
            self.assertEqual(snapshot['providers']['greenhouse']['not_before'],
                             '2026-11-05T00:00:30+00:00')

    def test_import_does_not_replenish_an_active_run_request_budget(self):
        clock = Clock()
        client = self.client(clock, Responses(response(), response()),
                             policy=RequestPolicy(max_requests=1, max_retries=0, min_interval=0))
        client.get_json('greenhouse', URL)
        client.import_state(client.export_state())
        self.assert_code('request_limit', lambda: client.get_json('greenhouse', URL))

    def test_expired_pause_resets_failure_streak_with_new_clock_origin(self):
        payload = {'version': 1, 'providers': {'greenhouse': {
            'failures': 2, 'paused_until': '2026-11-05T00:00:20+00:00', 'not_before': None}}}
        clock = Clock(21, monotonic_origin=-21)
        client = self.client(clock, Responses(response(503), response()),
                             policy=RequestPolicy(max_retries=0, error_threshold=2, min_interval=0))
        client.import_state(payload)
        self.assert_code('http_503', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(client.get_json('greenhouse', URL), {'jobs': []})
