from __future__ import annotations

import json
import random as random_module
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .models import HttpResponse, RequestPolicy, SourceError

API_HOSTS = {
    'greenhouse': 'boards-api.greenhouse.io',
    'lever': 'api.lever.co',
    'ashby': 'api.ashbyhq.com',
}
_PATHS = {
    'greenhouse': r'/v1/boards/[A-Za-z0-9][A-Za-z0-9_-]{0,99}/jobs',
    'lever': r'/v0/postings/[A-Za-z0-9][A-Za-z0-9_-]{0,99}',
    'ashby': r'/posting-api/job-board/[A-Za-z0-9][A-Za-z0-9_-]{0,99}',
}
T = TypeVar('T')


def strict_url(url: str, hosts: set[str]):
    """Reject URL parser ambiguities before allowing any network request."""
    if (not isinstance(url, str) or len(url) > 2048 or not url.isascii()
            or any(ord(c) <= 32 or ord(c) == 127 for c in url) or '\\' in url):
        raise SourceError('unsafe_url')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc not in hosts
                or parsed.username is not None or parsed.password is not None
                or parsed.port is not None or parsed.fragment):
            raise SourceError('unsafe_url')
    except ValueError:
        raise SourceError('unsafe_url') from None
    return parsed


def validate_api_url(provider: str, url: str) -> None:
    if provider not in API_HOSTS:
        raise SourceError('unsafe_url')
    parsed = strict_url(url, {API_HOSTS[provider]})
    if not re.fullmatch(_PATHS[provider], parsed.path):
        raise SourceError('unsafe_url')
    try:
        pairs = parse_qsl(parsed.query, strict_parsing=True)
        query = dict(pairs)
        if len(pairs) != len(query):
            raise ValueError
        if provider == 'greenhouse':
            valid = query == {'content': 'true'}
        elif provider == 'lever':
            valid = (set(query) == {'mode', 'skip', 'limit'} and query['mode'] == 'json'
                     and re.fullmatch(r'[0-9]{1,7}', query['skip'])
                     and re.fullmatch(r'[0-9]{1,4}', query['limit'])
                     and 1 <= int(query['limit']) <= 1000)
        else:
            valid = not query
        if not valid:
            raise ValueError
    except ValueError:
        raise SourceError('unsafe_url') from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    """GET only, normal proxy/CA trust, no cookies, no automatic redirects."""

    def __init__(self):
        self.opener = build_opener(_NoRedirect())

    def __call__(self, url: str, timeout: float, max_bytes: int) -> HttpResponse:
        host = urlsplit(url).netloc
        provider = next((p for p, h in API_HOSTS.items() if h == host), '')
        validate_api_url(provider, url)
        request = Request(url, method='GET', headers={
            'Accept': 'application/json', 'Accept-Encoding': 'identity',
            'User-Agent': 'job-search-assistant/1.0 (public job board reader)',
        })
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return HttpResponse(response.status, dict(response.headers),
                                    response.read(max_bytes + 1))
        except HTTPError as error:
            # Do not read an error page, or follow its Location header.
            try:
                return HttpResponse(error.code, dict(error.headers), b'')
            finally:
                error.close()


@dataclass
class _State:
    requests: int = 0
    failures: int = 0
    wait_used: float = 0.0
    paused_until: float = 0.0
    not_before: float = 0.0
    last_request: float | None = None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError('non-finite JSON number')


class SafeHttpClient:
    def __init__(self, policy: RequestPolicy | None = None, *, transport=None,
                 sleep: Callable = time.sleep, monotonic: Callable = time.monotonic,
                 now: Callable = lambda: datetime.now(timezone.utc),
                 random: Callable = random_module.random):
        self.policy = policy or RequestPolicy()
        self.transport = transport or UrllibTransport()
        self.sleep, self.monotonic, self.now, self.random = sleep, monotonic, now, random
        self._states: dict[str, _State] = {}

    @property
    def request_counts(self) -> dict[str, int]:
        return {name: state.requests for name, state in self._states.items()}

    def begin_run(self) -> None:
        # Preserve cooldowns between runs on this client, but reset run budgets.
        for state in self._states.values():
            state.requests = 0
            state.wait_used = 0.0

    def _failure(self, state: _State) -> None:
        state.failures += 1
        if state.failures >= self.policy.error_threshold:
            state.paused_until = max(state.paused_until,
                                     self.monotonic() + self.policy.pause_seconds)

    def _guard(self, state: _State) -> None:
        current = self.monotonic()
        if state.paused_until > current:
            raise SourceError('source_paused')
        if state.paused_until:
            state.paused_until = 0
            state.failures = 0
        if state.requests >= self.policy.max_requests:
            raise SourceError('request_limit')

    def _wait(self, state: _State, delay: float) -> None:
        if delay > self.policy.max_wait - state.wait_used:
            state.paused_until = max(state.paused_until, state.not_before,
                                     self.monotonic() + self.policy.pause_seconds)
            raise SourceError('source_paused')
        if delay > 0:
            self.sleep(delay)
            state.wait_used += delay

    def _retry_after(self, value: str, state: _State) -> float:
        try:
            if re.fullmatch(r'[0-9]{1,10}', value.strip()):
                delay = float(value.strip())
            else:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    raise ValueError
                delay = max(0.0, (date - self.now()).total_seconds())
        except (TypeError, ValueError, OverflowError):
            state.paused_until = self.monotonic() + self.policy.pause_seconds
            raise SourceError('invalid_retry_after') from None
        state.not_before = max(state.not_before, self.monotonic() + delay)
        return delay

    def get_json(self, provider: str, url: str, validator: Callable = lambda data: data) -> T:
        validate_api_url(provider, url)
        state = self._states.setdefault(provider, _State())
        for attempt in range(self.policy.max_retries + 1):
            self._guard(state)
            current = self.monotonic()
            interval = 0 if state.last_request is None else (
                state.last_request + self.policy.min_interval - current)
            self._wait(state, max(0, interval, state.not_before - current))
            state.requests += 1
            state.last_request = self.monotonic()
            headers = {}
            try:
                response = self.transport(url, self.policy.timeout, self.policy.max_response_bytes)
                headers = {key.lower(): value for key, value in response.headers.items()}
                status = response.status
            except (URLError, OSError, TimeoutError):
                status = 0
            if status == 200:
                try:
                    if len(response.body) > self.policy.max_response_bytes:
                        raise SourceError('response_too_large')
                    if headers.get('content-encoding', 'identity').lower() != 'identity':
                        raise SourceError('unexpected_encoding')
                    kind = headers.get('content-type', '').split(';')[0].strip().lower()
                    if kind != 'application/json' and not (
                            kind.startswith('application/') and kind.endswith('+json')):
                        raise SourceError('unexpected_content_type')
                    try:
                        payload = json.loads(response.body.decode('utf-8'),
                                             object_pairs_hook=_unique_object,
                                             parse_constant=_invalid_constant)
                    except (ValueError, UnicodeError, RecursionError):
                        raise SourceError('invalid_json') from None
                    result = validator(payload)
                except SourceError:
                    self._failure(state)
                    raise
                state.failures = 0
                return result
            self._failure(state)
            retryable = status == 0 or status == 429 or 500 <= status <= 599
            error = SourceError('network_error' if status == 0 else (
                'unsafe_redirect' if 300 <= status <= 399 else f'http_{status}'))
            retry_after = 0.0
            if retryable and 'retry-after' in headers:
                retry_after = self._retry_after(headers['retry-after'], state)
                if retry_after > self.policy.max_wait - state.wait_used:
                    self._wait(state, retry_after)
            if not retryable or attempt == self.policy.max_retries:
                raise error
            self._guard(state)
            delay = min(self.policy.max_backoff, self.policy.backoff_base * 2 ** attempt)
            delay *= 0.5 + 0.5 * self.random()
            self._wait(state, max(delay, retry_after))
        raise SourceError('retry_limit')  # Defensive: the finite loop always returns or raises.
