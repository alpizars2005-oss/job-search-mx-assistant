from __future__ import annotations

import json
import random as random_module
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from typing import TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..runtime_control import BoundedTransport, LOCAL_CONTROL_CODES, LocalControlError
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
        # Python 3.10 treats an empty query as an invalid field in strict mode.
        pairs = parse_qsl(parsed.query, strict_parsing=True) if parsed.query else []
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
    # Reservations consume quota before the durable checkpoint. Only entry to
    # transport counts as an attempted request in source reports.
    requests: int = 0
    attempts: int = 0
    failures: int = 0
    wait_used: float = 0.0
    paused_until: float = 0.0
    not_before: float = 0.0
    last_request: float | None = None
    in_flight_until: float = 0.0
    suspension: dict | None = None
    external_deadline: datetime | None = None
    provider_issue: str | None = None


def _utc_date(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        raise ValueError
    return date.astimezone(timezone.utc)


def _seconds_deadline(value, observed):
    # Avoid Python's integer digit limit and float/timedelta overflow. A value
    # longer than twelve decimal digits cannot fit within datetime's range.
    if len(value) > 12:
        return None
    try:
        return observed + timedelta(seconds=int(value))
    except OverflowError:
        return None


def _validated_suspension(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {
            'reason', 'kind', 'value', 'observed_at', 'not_before'}
            or value['reason'] != 'retry_after_horizon'):
        raise ValueError
    observed = _utc_date(value['observed_at'])
    if observed.isoformat() != value['observed_at']:
        raise ValueError
    if value['kind'] == 'seconds':
        seconds = value['value']
        if (not isinstance(seconds, str) or not re.fullmatch(r'0|[1-9][0-9]*', seconds)):
            raise ValueError
        date = _seconds_deadline(seconds, observed)
    elif value['kind'] == 'http_date':
        date = _utc_date(value['value'])
        if date.isoformat() != value['value']:
            raise ValueError
    else:
        raise ValueError
    expected = date.isoformat() if date is not None else None
    if value['not_before'] != expected:
        raise ValueError
    return dict(value)


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
                 random: Callable = random_module.random, control=None,
                 state_callback: Callable | None = None):
        self.policy = policy or RequestPolicy()
        self.control, self.state_callback = control, state_callback
        self.transport = (transport if transport is not None else
                          BoundedTransport(control) if control is not None else UrllibTransport())
        self.sleep, self.monotonic, self.now, self.random = sleep, monotonic, now, random
        self._states: dict[str, _State] = {}

    def export_state(self) -> dict:
        """Export health and constraints, never bodies, URLs or run quotas."""
        current = self.monotonic()
        now = self.now().astimezone(timezone.utc)

        def deadline(value):
            if value <= current:
                return None
            try:
                return (now + timedelta(seconds=value - current)).isoformat()
            except OverflowError:
                return datetime.max.replace(tzinfo=timezone.utc).isoformat()

        providers = {}
        for provider, state in self._states.items():
            not_before = deadline(max(state.not_before, state.in_flight_until))
            if (state.external_deadline is not None and state.external_deadline > now
                    and (not_before is None or _utc_date(not_before) < state.external_deadline)):
                not_before = state.external_deadline.isoformat()
            providers[provider] = {
                'failures': state.failures,
                'paused_until': deadline(state.paused_until),
                'not_before': not_before,
                'suspension': dict(state.suspension) if state.suspension is not None else None,
            }
        return {'version': 2, 'providers': providers}

    def import_state(self, payload) -> None:
        """Atomically restore UTC deadlines against this process's clock."""
        current, now = self.monotonic(), self.now()
        restored = {}

        def deadline(value):
            if value is None:
                return 0.0
            date = _utc_date(value)
            return current + max(0.0, (date - now).total_seconds())

        try:
            if (not isinstance(payload, dict) or set(payload) != {'version', 'providers'}
                    or type(payload['version']) is not int or payload['version'] not in (1, 2)
                    or not isinstance(payload['providers'], dict)
                    or not set(payload['providers']).issubset(API_HOSTS)):
                raise ValueError
            for provider, values in payload['providers'].items():
                expected = {'failures', 'paused_until', 'not_before'}
                if payload['version'] == 2:
                    expected.add('suspension')
                if (not isinstance(values, dict) or set(values) != expected
                        or type(values['failures']) is not int
                        or not 0 <= values['failures'] <= 1000):
                    raise ValueError
                state = _State(
                    failures=values['failures'], paused_until=deadline(values['paused_until']),
                    not_before=deadline(values['not_before']),
                    suspension=_validated_suspension(values.get('suspension')),
                    external_deadline=_utc_date(values['not_before']) if values['not_before'] is not None else None)
                if state.suspension is not None and state.suspension['not_before'] is not None:
                    if (values['not_before'] is None and _utc_date(state.suspension['not_before']) > now
                            or values['not_before'] is not None
                            and _utc_date(values['not_before']) < _utc_date(state.suspension['not_before'])):
                        raise ValueError
                if values['paused_until'] is not None and state.paused_until <= current:
                    state.paused_until, state.failures = 0.0, 0
                restored[provider] = state
        except (TypeError, ValueError, OverflowError):
            raise SourceError('invalid_http_state') from None
        # Importing durable health cannot replenish this process's request quota.
        for provider, state in restored.items():
            previous = self._states.get(provider)
            if previous is not None:
                state.requests, state.wait_used = previous.requests, previous.wait_used
                state.attempts = previous.attempts
        self._states.update(restored)

    def resume_provider(self, provider: str) -> None:
        """Clear manual suspension only after its external deadline expires.

        The durable caller records operator authorization separately. An
        unrepresentable deadline cannot be cleared by this operation.
        """
        state = self._states.get(provider)
        if state is None or state.suspension is None:
            raise SourceError('source_not_suspended')
        not_before = state.suspension['not_before']
        if not_before is None:
            raise SourceError('retry_after_unbounded')
        if _utc_date(not_before) > self.now():
            raise SourceError('retry_after_active')
        state.suspension = None
        self._state_changed()

    def _state_changed(self) -> None:
        if self.state_callback is not None:
            self.state_callback(self.export_state())

    def _check(self, state: _State | None = None) -> None:
        if self.control is not None:
            try:
                self.control.check()
            except LocalControlError as error:
                if state is not None:
                    error.provider_issue = state.provider_issue
                raise

    @property
    def request_counts(self) -> dict[str, int]:
        return {name: state.attempts for name, state in self._states.items()}

    def begin_run(self) -> None:
        # Preserve cooldowns between runs on this client, but reset run budgets.
        for state in self._states.values():
            state.requests = 0
            state.attempts = 0
            state.wait_used = 0.0

    def _failure(self, state: _State, *, notify: bool = True) -> None:
        state.failures += 1
        if state.failures >= self.policy.error_threshold:
            state.paused_until = max(state.paused_until,
                                     self.monotonic() + self.policy.pause_seconds)
        if notify:
            self._state_changed()

    def _guard(self, state: _State) -> None:
        self._check(state)
        current = self.monotonic()
        if state.suspension is not None:
            raise SourceError('source_suspended')
        if state.paused_until > current:
            raise SourceError('source_paused')
        if state.paused_until:
            state.paused_until = 0
            state.failures = 0
            self._state_changed()
        if state.requests >= self.policy.max_requests:
            raise SourceError('request_limit')

    def _wait(self, state: _State, delay: float) -> None:
        self._check(state)
        if delay > self.policy.max_wait - state.wait_used:
            state.paused_until = max(state.paused_until, state.not_before,
                                     self.monotonic() + self.policy.pause_seconds)
            self._state_changed()
            raise SourceError('source_paused')
        if delay > 0:
            state.not_before = max(state.not_before, self.monotonic() + delay)
            self._state_changed()
            if self.control is None:
                self.sleep(delay)
            else:
                try:
                    self.control.sleep(delay)
                except LocalControlError as error:
                    error.provider_issue = state.provider_issue
                    raise
            state.wait_used += delay
        self._check(state)

    def _retry_after(self, value: str, state: _State) -> float:
        observed = self.now().astimezone(timezone.utc)
        try:
            if not isinstance(value, str):
                raise ValueError
            if re.fullmatch(r'[0-9]+', value.strip()):
                kind, canonical = 'seconds', value.strip().lstrip('0') or '0'
                date = _seconds_deadline(canonical, observed)
                delay = None if date is None else max(0.0, (date - observed).total_seconds())
            else:
                kind = 'http_date'
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    raise ValueError
                date = date.astimezone(timezone.utc)
                canonical = date.isoformat()
                delay = max(0.0, (date - observed).total_seconds())
        except (TypeError, ValueError, OverflowError):
            state.paused_until = self.monotonic() + self.policy.pause_seconds
            self._state_changed()
            raise SourceError('invalid_retry_after') from None
        if delay is not None:
            state.not_before = max(state.not_before, self.monotonic() + delay)
            if state.external_deadline is None or date > state.external_deadline:
                state.external_deadline = date
        if delay is None or delay > self.policy.retry_after_horizon:
            state.suspension = {
                'reason': 'retry_after_horizon', 'kind': kind, 'value': canonical,
                'observed_at': observed.isoformat(),
                'not_before': date.isoformat() if date is not None else None,
            }
        self._state_changed()
        return delay or 0.0

    def get_json(self, provider: str, url: str, validator: Callable = lambda data: data) -> T:
        validate_api_url(provider, url)
        state = self._states.setdefault(provider, _State())
        state.provider_issue = None
        for attempt in range(self.policy.max_retries + 1):
            self._guard(state)
            current = self.monotonic()
            interval = 0 if state.last_request is None else (
                state.last_request + self.policy.min_interval - current)
            self._wait(state, max(0, interval, state.not_before - current))
            self._check(state)
            state.requests += 1
            state.last_request = self.monotonic()
            state.not_before = max(state.not_before, state.last_request + self.policy.min_interval)
            state.in_flight_until = state.last_request + self.policy.timeout
            self._state_changed()
            self._check(state)
            headers = {}
            interruption = None
            status = 0
            try:
                timeout = (self.policy.timeout if self.control is None else
                           min(self.policy.timeout, self.control.remaining()))
                state.attempts += 1
                response = self.transport(url, timeout, self.policy.max_response_bytes)
            except LocalControlError as error:
                if error.response is None:
                    error.provider_issue = state.provider_issue
                    raise
                # Cleanup can fail after IPC already delivered a response. Keep
                # its external constraint before reporting the surviving child.
                response, interruption = error.response, error
            except (URLError, OSError, TimeoutError, HTTPException):
                pass
            else:
                status = response.status
            if interruption is not None:
                status = response.status
            if status:
                headers = {key.lower(): value for key, value in response.headers.items()}
            state.in_flight_until = 0.0
            if status == 200:
                # A completed response ends the crash reservation even if local
                # control forbids parsing its body. It is not a provider failure.
                self._state_changed()
                if interruption is not None:
                    interruption.provider_issue = state.provider_issue
                    raise interruption
                try:
                    self._check(state)
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
                    self._check(state)
                except SourceError as error:
                    if error.code not in LOCAL_CONTROL_CODES:
                        self._failure(state)
                    raise
                state.failures = 0
                state.provider_issue = None
                self._state_changed()
                return result
            # Commit failure and server cooldown together: an intermediate save
            # must never replace the pending reservation with an earlier deadline.
            self._failure(state, notify=False)
            retryable = status == 0 or status == 429 or 500 <= status <= 599
            error = SourceError('network_error' if status == 0 else (
                'unsafe_redirect' if 300 <= status <= 399 else f'http_{status}'))
            state.provider_issue = error.code
            try:
                retry_after = 0.0
                if retryable and 'retry-after' in headers:
                    retry_after = self._retry_after(headers['retry-after'], state)
                else:
                    self._state_changed()
                # Commit server metadata before checking cancellation/deadline.
                if interruption is not None:
                    raise interruption
                self._check(state)
                if state.suspension is not None:
                    raise SourceError('source_suspended')
                if retry_after > self.policy.max_wait - state.wait_used:
                    self._wait(state, retry_after)
                if not retryable or attempt == self.policy.max_retries:
                    raise error
                self._guard(state)
                delay = min(self.policy.max_backoff, self.policy.backoff_base * 2 ** attempt)
                delay *= 0.5 + 0.5 * self.random()
                self._wait(state, max(delay, retry_after))
            except SourceError as outcome:
                if isinstance(outcome, LocalControlError):
                    outcome.provider_issue = error.code
                    raise
                raise LocalControlError(outcome.code, provider_issue=error.code,
                                        rejected=outcome.rejected) from None
        raise SourceError('retry_limit')  # Defensive: the finite loop always returns or raises.
