import io
import json
import socket
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError

from jobsearch_assistant.sources.http import SafeHttpClient, UrllibTransport, validate_api_url
from jobsearch_assistant.sources.models import HttpResponse, RequestPolicy, SourceConfig, SourceError

URL = 'https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true'


class Clock:
    def __init__(self):
        self.time = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.time

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.time += seconds


def response(status=200, payload=None, headers=None, body=None):
    return HttpResponse(status, headers or {'Content-Type': 'application/json'},
                        body if body is not None else json.dumps(payload or {}).encode())


class QueueTransport:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = []

    def __call__(self, url, timeout, max_bytes):
        self.calls.append((url, timeout, max_bytes))
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class HttpTests(unittest.TestCase):
    def client(self, items, **options):
        self.clock = Clock()
        self.transport = QueueTransport(*items)
        return SafeHttpClient(
            RequestPolicy(**options), transport=self.transport, sleep=self.clock.sleep,
            monotonic=self.clock.monotonic,
            now=lambda: datetime(2026, 11, 4, tzinfo=timezone.utc), random=lambda: 0.5,
        )

    def assert_code(self, code, function):
        with self.assertRaises(SourceError) as error:
            function()
        self.assertEqual(error.exception.code, code)
        self.assertNotIn('private-value', str(error.exception))

    def test_valid_json_timeout_size_and_safe_interval(self):
        client = self.client([response(payload={'jobs': []}), response()])
        self.assertEqual(client.get_json('greenhouse', URL), {'jobs': []})
        client.get_json('greenhouse', URL)
        self.assertEqual(self.transport.calls[0][1:], (15.0, 5 * 1024 * 1024))
        self.assertEqual(self.clock.sleeps, [1.0])
        self.assertEqual(client.request_counts['greenhouse'], 2)

    def test_hosts_paths_queries_and_config_are_strict(self):
        validate_api_url('greenhouse', URL)
        bad = [
            URL.replace('https:', 'http:'), URL.replace('boards-api.', 'evil.boards-api.'),
            URL.replace('greenhouse.io', 'greenhouse.io.evil.example'),
            URL.replace('https://', 'https://private-value@'),
            URL.replace('greenhouse.io/', 'greenhouse.io:444/'),
            URL + '#fragment', URL + '&next=https://evil.example',
            URL.replace('/example/', '/%2e%2e/'),
            URL.replace('/example/', '/example\\evil/'),
            URL.replace('/example/', '/example\n/'),
            URL.replace('/jobs?', '/jobs/123?'),
            URL.replace('boards-api.greenhouse.io', '127.0.0.1'),
            URL.replace('boards-api.greenhouse.io', '[::1]'),
        ]
        client = self.client([])
        for value in bad:
            with self.subTest(value=value):
                self.assert_code('unsafe_url', lambda: client.get_json('greenhouse', value))
        self.assertEqual(self.transport.calls, [])
        with self.assertRaises(ValueError):
            SourceConfig('greenhouse', '../private-value', 'Synthetic', True)
        with self.assertRaises(ValueError):
            SourceConfig('linkedin', 'example', 'Synthetic', True)
        self.assertFalse(SourceConfig('greenhouse', 'example', 'Synthetic').enabled)
        for value in (False, 0, -1, float('nan'), float('inf'), '15'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RequestPolicy(timeout=value)

    def test_content_type_encoding_invalid_json_and_size(self):
        cases = [
            (response(headers={'Content-Type': 'text/html'}, body=b'<html>private-value</html>'), 'unexpected_content_type'),
            (response(body=b'<html>private-value</html>'), 'invalid_json'),
            (response(body=b'{broken'), 'invalid_json'),
            (response(body=b'\xff'), 'invalid_json'),
            (response(body=b'{"a": NaN}'), 'invalid_json'),
            (response(body=b'{"jobs":[],"jobs":{}}'), 'invalid_json'),
            (response(body=b' ' * 101), 'response_too_large'),
            (response(headers={'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}), 'unexpected_encoding'),
        ]
        for item, code in cases:
            with self.subTest(code=code):
                client = self.client([item], max_response_bytes=100)
                self.assert_code(code, lambda: client.get_json('greenhouse', URL))
                self.assertEqual(len(self.transport.calls), 1)

    def test_timeout_and_5xx_retry_with_bounded_jitter(self):
        client = self.client([socket.timeout(), response(503), response()], min_interval=0)
        client.get_json('greenhouse', URL)
        self.assertEqual(self.clock.sleeps, [0.75, 1.5])
        self.assertEqual(len(self.transport.calls), 3)

    def test_retry_after_seconds_date_and_exhausted_retries(self):
        for header in ('7', 'Wed, 04 Nov 2026 00:00:07 GMT'):
            with self.subTest(header=header):
                client = self.client([response(429, headers={'Retry-After': header}), response()])
                client.get_json('greenhouse', URL)
                self.assertEqual(self.clock.sleeps, [7.0])
        client = self.client([response(503)] * 4, min_interval=0)
        self.assert_code('http_503', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(len(self.transport.calls), 4)

    def test_retry_after_does_not_get_shortened_or_lost_after_retries(self):
        client = self.client([response(429, headers={'Retry-After': '3600'})], max_wait=5)
        self.assert_code('source_paused', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(self.clock.sleeps, [])
        self.clock.time = 301
        client.begin_run()
        self.assert_code('source_paused', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(len(self.transport.calls), 1)
        client = self.client([response(429, headers={'Retry-After': '10'}), response()], max_retries=0)
        self.assert_code('http_429', lambda: client.get_json('greenhouse', URL))
        client.get_json('greenhouse', URL)
        self.assertEqual(self.clock.sleeps, [10.0])

    def test_invalid_retry_after_pauses_without_retry(self):
        client = self.client([response(429, headers={'Retry-After': 'private-value'})])
        self.assert_code('invalid_retry_after', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(len(self.transport.calls), 1)
        self.assert_code('source_paused', lambda: client.get_json('greenhouse', URL))

    def test_shared_request_budget_counts_attempts_and_resets_per_run(self):
        client = self.client([response(503), response(), response()], max_requests=2)
        client.get_json('greenhouse', URL)
        other_board = URL.replace('/example/', '/another/')
        self.assert_code('request_limit', lambda: client.get_json('greenhouse', other_board))
        client.begin_run()
        client.get_json('greenhouse', other_board)
        self.assertEqual(client.request_counts['greenhouse'], 1)

    def test_wait_budget_and_circuit_breaker_bound_work(self):
        client = self.client([response(500)] * 4, error_threshold=2, min_interval=0)
        self.assert_code('source_paused', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(len(self.transport.calls), 2)
        client.begin_run()
        self.assert_code('source_paused', lambda: client.get_json('greenhouse', URL))
        self.clock.time = 301
        self.assert_code('source_paused', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(len(self.transport.calls), 4)
        client = self.client([response(500)] * 4, max_wait=0.5, min_interval=0)
        self.assert_code('source_paused', lambda: client.get_json('greenhouse', URL))
        self.assertEqual(len(self.transport.calls), 1)

    def test_bad_payload_validation_counts_toward_breaker_and_success_resets(self):
        def reject(_):
            raise SourceError('invalid_payload')
        client = self.client([response()] * 4, error_threshold=2, min_interval=0)
        self.assert_code('invalid_payload', lambda: client.get_json('greenhouse', URL, reject))
        self.assert_code('invalid_payload', lambda: client.get_json('greenhouse', URL, reject))
        self.assert_code('source_paused', lambda: client.get_json('greenhouse', URL))
        client = self.client([response()] * 3, error_threshold=2, min_interval=0)
        self.assert_code('invalid_payload', lambda: client.get_json('greenhouse', URL, reject))
        client.get_json('greenhouse', URL)
        self.assert_code('invalid_payload', lambda: client.get_json('greenhouse', URL, reject))

    def test_redirects_and_nonretryable_http_errors_are_not_followed(self):
        for status in (301, 302, 303, 307, 308, 400, 401, 403, 404):
            client = self.client([response(status, headers={'Location': 'http://127.0.0.1/private-value'})])
            expected = 'unsafe_redirect' if status < 400 else f'http_{status}'
            with self.subTest(status=status):
                self.assert_code(expected, lambda: client.get_json('greenhouse', URL))
                self.assertEqual(len(self.transport.calls), 1)

    def test_real_transport_uses_get_and_disables_automatic_redirects(self):
        transport = UrllibTransport()
        request = transport.opener.handlers
        redirect = next(h for h in request if hasattr(h, 'redirect_request'))
        self.assertIsNone(redirect.redirect_request(None, None, 302, '', {}, 'https://evil.example'))
        error = HTTPError(URL, 302, 'redirect', {'Location': 'http://127.0.0.1'}, io.BytesIO(b''))
        with patch.object(transport.opener, 'open', side_effect=error) as opener:
            result = transport(URL, 3, 100)
        self.assertEqual(result.status, 302)
        self.assertEqual(opener.call_args.args[0].get_method(), 'GET')
        self.assertEqual(opener.call_args.kwargs['timeout'], 3)

    def test_transport_reads_only_size_limit_plus_one_and_closes(self):
        class FakeResponse(io.BytesIO):
            status = 200
            headers = {'Content-Type': 'application/json'}
        transport = UrllibTransport()
        body = FakeResponse(b' ' * 1000)
        with patch.object(transport.opener, 'open', return_value=body):
            result = transport(URL, 3, 100)
        self.assertEqual(len(result.body), 101)
        self.assertTrue(body.closed)
