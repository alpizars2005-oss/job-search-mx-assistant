"""Synthetic regressions for local controls and durable server constraints."""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from jobsearch_assistant.runtime_control import RunControl
from jobsearch_assistant.sources.discovery import DiscoveryEngine
from jobsearch_assistant.sources.http import SafeHttpClient
from jobsearch_assistant.sources.models import HttpResponse, RequestPolicy, SourceConfig, SourceError

URL = 'https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true'
CONFIGS = [SourceConfig('greenhouse', 'example', 'Synthetic', True),
           SourceConfig('lever', 'example', 'Synthetic', True)]


class Clock:
    def __init__(self, seconds=0):
        self.seconds = seconds

    def monotonic(self):
        return self.seconds

    def now(self):
        return datetime(2026, 11, 5, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)

    def sleep(self, delay):
        self.seconds += delay


def response(status=200, headers=None):
    return HttpResponse(status, headers or {'Content-Type': 'application/json'}, b'{"jobs":[]}')


class SourceHardeningTests(unittest.TestCase):
    def client(self, clock, transport, **kwargs):
        return SafeHttpClient(RequestPolicy(max_retries=0, min_interval=0), transport=transport,
                              now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep, **kwargs)

    def assert_code(self, code, call):
        with self.assertRaises(SourceError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_control_after_200_is_neutral_and_stops_later_providers(self):
        for trigger in ('cancelled', 'deadline'):
            with self.subTest(trigger=trigger):
                clock, cancelled, calls, reports, saved = Clock(), [False], [], [], []
                control = RunControl(1, monotonic=clock.monotonic, cancelled=lambda: cancelled[0])
                def transport(url, *args):
                    calls.append(url)
                    if trigger == 'cancelled':
                        cancelled[0] = True
                    else:
                        clock.seconds = 2
                    return response()
                client = self.client(clock, transport, control=control,
                                     state_callback=lambda value: saved.append(copy.deepcopy(value)))
                self.assert_code('run_' + trigger, lambda: DiscoveryEngine(client).run(CONFIGS, on_report=reports.append))
                self.assertEqual(len(calls), 1)
                self.assertEqual([r.status for r in reports], ['interrupted', 'not_attempted'])
                self.assertEqual([r.requests for r in reports], [1, 0])
                self.assertEqual(saved[-1]['providers']['greenhouse']['failures'], 0)
                self.assertIsNone(saved[-1]['providers']['greenhouse']['paused_until'])
                self.assertNotIn('lever', saved[-1]['providers'])

    def test_five_200_deadlines_never_accumulate_provider_failures(self):
        clock, state = Clock(), None
        for _ in range(5):
            control = RunControl(1, monotonic=clock.monotonic)
            def transport(*args):
                clock.seconds += 2
                return response()
            client = self.client(clock, transport, control=control)
            if state is not None:
                client.import_state(state)
            self.assert_code('run_deadline', lambda: client.get_json('greenhouse', URL))
            state = client.export_state()
            self.assertEqual(state['providers']['greenhouse']['failures'], 0)
            self.assertIsNone(state['providers']['greenhouse']['paused_until'])

    def test_cancel_before_network_marks_all_enabled_sources_not_attempted(self):
        clock, reports = Clock(), []
        client = self.client(clock, lambda *args: self.fail('network after cancellation'),
                             control=RunControl(10, cancelled=lambda: True))
        self.assert_code('run_cancelled', lambda: DiscoveryEngine(client).run(CONFIGS, on_report=reports.append))
        self.assertEqual([r.status for r in reports], ['not_attempted', 'not_attempted'])
        self.assertEqual([r.requests for r in reports], [0, 0])

    def test_real_http_failure_is_retained_when_control_fires_after_response(self):
        clock, cancelled, reports = Clock(), [False], []
        control = RunControl(10, monotonic=clock.monotonic, cancelled=lambda: cancelled[0])
        def transport(*args):
            cancelled[0] = True
            return response(429, {'Retry-After': '3600'})
        client = self.client(clock, transport, control=control)
        self.assert_code('run_cancelled', lambda: DiscoveryEngine(client).run(CONFIGS, on_report=reports.append))
        self.assertEqual(reports[0].status, 'interrupted')
        self.assertEqual(reports[0].issues, ['http_429', 'run_cancelled'])
        state = client.export_state()['providers']['greenhouse']
        self.assertEqual(state['failures'], 1)
        self.assertEqual(state['not_before'], '2026-11-05T01:00:00+00:00')

    def test_reservation_is_durable_without_inventing_provider_failure(self):
        clock, snapshots = Clock(), []
        def crash(*args):
            raise RuntimeError('synthetic process interruption')
        client = self.client(clock, crash, state_callback=lambda value: snapshots.append(copy.deepcopy(value)))
        with self.assertRaises(RuntimeError):
            client.get_json('greenhouse', URL)
        self.assertEqual(snapshots[-1]['providers']['greenhouse']['failures'], 0)
        self.assertEqual(snapshots[-1]['providers']['greenhouse']['not_before'], '2026-11-05T00:00:15+00:00')

    def test_received_200_checkpoint_clears_unfinished_request_reservation(self):
        clock, cancelled, snapshots = Clock(), [False], []
        def transport(*args):
            cancelled[0] = True
            return response()
        client = self.client(clock, transport,
                             control=RunControl(10, cancelled=lambda: cancelled[0]),
                             state_callback=lambda value: snapshots.append(copy.deepcopy(value)))
        self.assert_code('run_cancelled', lambda: client.get_json('greenhouse', URL))
        self.assertIsNone(snapshots[-1]['providers']['greenhouse']['not_before'])


    def test_retry_after_beyond_horizon_is_suspended_with_exact_constraint(self):
        for value, kind, deadline in (
                ('86401', 'seconds', '2026-11-06T00:00:01+00:00'),
                ('99999999999', 'seconds', '5195-09-20T09:46:39+00:00'),
                ('Fri, 31 Dec 9999 23:59:59 GMT', 'http_date', '9999-12-31T23:59:59+00:00'),
                ('9' * 5000, 'seconds', None)):
            with self.subTest(value=value[:30]):
                clock, calls, saved = Clock(), [], []
                def transport(*args):
                    calls.append(1)
                    return response(429, {'Retry-After': value})
                client = self.client(clock, transport, state_callback=lambda state: saved.append(copy.deepcopy(state)))
                self.assert_code('source_suspended', lambda: client.get_json('greenhouse', URL))
                state = saved[-1]
                self.assertEqual(state['version'], 2)
                provider = state['providers']['greenhouse']
                self.assertEqual(provider['failures'], 1)
                self.assertEqual(provider['suspension'], {
                    'reason': 'retry_after_horizon', 'kind': kind,
                    'value': value if kind == 'seconds' else deadline,
                    'observed_at': '2026-11-05T00:00:00+00:00', 'not_before': deadline})
                restarted = self.client(Clock(1000), lambda *args: self.fail('suspended restart contacted provider'))
                restarted.import_state(json.loads(json.dumps(state)))
                self.assert_code('source_suspended', lambda: restarted.get_json('greenhouse', URL))
                self.assert_code('retry_after_active' if deadline else 'retry_after_unbounded',
                                 lambda: restarted.resume_provider('greenhouse'))
                self.assertEqual(len(calls), 1)

    def test_suspension_requires_explicit_resume_even_after_deadline(self):
        clock = Clock()
        client = self.client(clock, lambda *args: response(429, {'Retry-After': '86401'}))
        self.assert_code('source_suspended', lambda: client.get_json('greenhouse', URL))
        clock.seconds = 86402
        restarted = self.client(clock, lambda *args: response())
        restarted.import_state(client.export_state())
        self.assert_code('source_suspended', lambda: restarted.get_json('greenhouse', URL))
        restarted.resume_provider('greenhouse')
        self.assertEqual(restarted.get_json('greenhouse', URL), {'jobs': []})
        self.assertIsNone(restarted.export_state()['providers']['greenhouse']['suspension'])

    def test_suspension_survives_control_after_extreme_retry_after(self):
        clock, cancelled = Clock(), [False]
        def transport(*args):
            cancelled[0] = True
            return response(503, {'Retry-After': '999999999999999999999999'})
        client = self.client(clock, transport, control=RunControl(10, cancelled=lambda: cancelled[0]))
        self.assert_code('run_cancelled', lambda: client.get_json('greenhouse', URL))
        saved = client.export_state()['providers']['greenhouse']
        self.assertEqual(saved['failures'], 1)
        self.assertEqual(saved['suspension']['value'], '999999999999999999999999')
        self.assertIsNone(saved['suspension']['not_before'])

    def test_import_rejects_suspension_with_forged_earlier_deadline(self):
        client = self.client(Clock(), lambda *args: response())
        forged = {'version': 2, 'providers': {'greenhouse': {
            'failures': 1, 'paused_until': None, 'not_before': '2026-11-05T00:00:01+00:00',
            'suspension': {'reason': 'retry_after_horizon', 'kind': 'seconds', 'value': '999999',
                           'observed_at': '2026-11-05T00:00:00+00:00',
                           'not_before': '2026-11-05T00:00:01+00:00'}}}}
        self.assert_code('invalid_http_state', lambda: client.import_state(forged))
        self.assertEqual(client.export_state()['providers'], {})



    def test_worker_failure_is_neutral_and_retains_request_reservation(self):
        from jobsearch_assistant.runtime_control import LocalControlError
        clock, reports = Clock(), []
        def transport(*args):
            raise LocalControlError('worker_failed')
        client = self.client(clock, transport)
        self.assert_code('worker_failed', lambda: DiscoveryEngine(client).run(CONFIGS, on_report=reports.append))
        self.assertEqual([report.status for report in reports], ['interrupted', 'not_attempted'])
        state = client.export_state()['providers']['greenhouse']
        self.assertEqual(state['failures'], 0)
        self.assertEqual(state['not_before'], '2026-11-05T00:00:15+00:00')

    def test_cleanup_failure_preserves_completed_response_constraint(self):
        from jobsearch_assistant.runtime_control import LocalControlError
        clock, reports = Clock(), []
        def transport(*args):
            error = LocalControlError('worker_cleanup_failed')
            error.response = response(429, {'Retry-After': '3600'})
            error.worker_pid = 12345
            raise error
        client = self.client(clock, transport)
        self.assert_code('worker_cleanup_failed', lambda: DiscoveryEngine(client).run(CONFIGS, on_report=reports.append))
        state = client.export_state()['providers']['greenhouse']
        self.assertEqual(state['failures'], 1)
        self.assertEqual(state['not_before'], '2026-11-05T01:00:00+00:00')
        self.assertEqual(reports[0].issues, ['http_429', 'worker_cleanup_failed'])



    def test_cancellation_after_reservation_before_transport_is_not_attempted(self):
        clock, cancelled, reports, snapshots = Clock(), [False], [], []
        def persisted(state):
            snapshots.append(copy.deepcopy(state))
            cancelled[0] = True
        client = self.client(clock, lambda *args: self.fail('cancelled reservation started transport'),
                             control=RunControl(10, cancelled=lambda: cancelled[0]), state_callback=persisted)
        self.assert_code('run_cancelled', lambda: DiscoveryEngine(client).run(CONFIGS, on_report=reports.append))
        self.assertEqual([report.status for report in reports], ['not_attempted', 'not_attempted'])
        self.assertEqual([report.requests for report in reports], [0, 0])
        self.assertEqual(snapshots[-1]['providers']['greenhouse']['failures'], 0)
        self.assertEqual(snapshots[-1]['providers']['greenhouse']['not_before'], '2026-11-05T00:00:15+00:00')

    def test_cancellation_between_providers_preserves_completed_provider_report(self):
        clock, cancelled, reports, calls = Clock(), [False], [], []
        def transport(*args):
            calls.append(1)
            return response()
        def reported(report):
            reports.append(report)
            cancelled[0] = True
        client = self.client(clock, transport, control=RunControl(10, cancelled=lambda: cancelled[0]))
        self.assert_code('run_cancelled', lambda: DiscoveryEngine(client).run(CONFIGS, on_report=reported))
        self.assertEqual([report.status for report in reports], ['ok', 'not_attempted'])
        self.assertEqual([report.requests for report in reports], [1, 0])
        self.assertEqual(len(calls), 1)

    def test_deadline_while_waiting_for_known_cooldown_is_neutral(self):
        clock, reports = Clock(), []
        client = self.client(clock, lambda *args: self.fail('cooldown was bypassed'),
                             control=RunControl(1, monotonic=clock.monotonic))
        client.import_state({'version': 1, 'providers': {'greenhouse': {
            'failures': 2, 'paused_until': None, 'not_before': '2026-11-05T00:00:02+00:00'}}})
        with patch('jobsearch_assistant.runtime_control.time.sleep', side_effect=clock.sleep):
            self.assert_code('run_deadline', lambda: DiscoveryEngine(client).run(CONFIGS, on_report=reports.append))
        self.assertEqual([report.status for report in reports], ['not_attempted', 'not_attempted'])
        self.assertEqual(client.export_state()['providers']['greenhouse']['failures'], 2)
        self.assertEqual(client.export_state()['providers']['greenhouse']['not_before'], '2026-11-05T00:00:02+00:00')



    def test_known_external_deadline_is_not_shortened_by_clock_drift(self):
        for seconds, expected in (('3600', '2026-11-05T01:00:00+00:00'),
                                  ('86401', '2026-11-06T00:00:01+00:00')):
            with self.subTest(seconds=seconds):
                clock = Clock()
                client = self.client(clock, lambda *args: response(429, {'Retry-After': seconds}))
                self.assert_code('source_paused' if seconds == '3600' else 'source_suspended',
                                 lambda: client.get_json('greenhouse', URL))
                # UTC moves backward relative to monotonic, as with a clock adjustment.
                client.monotonic = lambda: 10.0
                saved = client.export_state()
                self.assertEqual(saved['providers']['greenhouse']['not_before'], expected)
                restarted = self.client(Clock(), lambda *args: self.fail('known deadline bypassed'))
                restarted.import_state(saved)
                self.assert_code('source_paused' if seconds == '3600' else 'source_suspended',
                                 lambda: restarted.get_json('greenhouse', URL))



    def test_real_failure_before_a_cancelled_200_retry_remains_in_report(self):
        clock, cancelled, calls, reports = Clock(), [False], [], []
        def transport(*args):
            calls.append(1)
            if len(calls) == 1:
                return response(503)
            cancelled[0] = True
            return response()
        client = SafeHttpClient(RequestPolicy(max_retries=1, min_interval=0), transport=transport,
                                now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep,
                                control=RunControl(10, monotonic=clock.monotonic,
                                                   cancelled=lambda: cancelled[0]))
        with patch('jobsearch_assistant.runtime_control.time.sleep', side_effect=clock.sleep):
            self.assert_code('run_cancelled', lambda: DiscoveryEngine(client).run(CONFIGS, on_report=reports.append))
        self.assertEqual(reports[0].issues, ['http_503', 'run_cancelled'])
        self.assertEqual(client.export_state()['providers']['greenhouse']['failures'], 1)
        self.assertEqual([report.requests for report in reports], [2, 0])


if __name__ == '__main__':
    unittest.main()
