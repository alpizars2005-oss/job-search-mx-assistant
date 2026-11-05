"""Opt-in Telegram configuration and the fixed sendMessage transport.

Only the dispatcher authorizes delivery. No endpoint, rich text, commands or
private profile/job fields can be supplied through notification events.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .sources.models import HttpResponse
from .workflow_contracts import WorkflowError

EVENT_LABELS = {
    'es': {
        'priority': 'Prioridad alta',
        'review_pending': 'Revisión pendiente',
        'eligibility_pending': 'Elegibilidad pendiente',
        'source_error': 'Error de fuente',
        'recovered': 'Ejecución recuperada',
        'run_summary': 'Resumen de ejecución',
    },
    'en': {
        'priority': 'High priority',
        'review_pending': 'Review pending',
        'eligibility_pending': 'Eligibility pending',
        'source_error': 'Source error',
        'recovered': 'Run recovered',
        'run_summary': 'Run summary',
    },
}
EVENT_KINDS = frozenset(EVENT_LABELS['en'])
_MAX_INTEGER = 2 ** 63 - 1


def validate_event(kind, entity_id, count, language) -> None:
    if (not isinstance(kind, str) or kind not in EVENT_KINDS
            or not isinstance(language, str) or language not in EVENT_LABELS
            or (entity_id is not None and
                (type(entity_id) is not int or not 1 <= entity_id <= _MAX_INTEGER))
            or type(count) is not int or not 0 <= count <= _MAX_INTEGER):
        raise WorkflowError('invalid_notification_event')


def format_event(kind: str, *, entity_id: int | None = None, count: int = 1,
                 language: str = 'es') -> str:
    """Render only static labels and validated internal integer IDs/counts."""
    validate_event(kind, entity_id, count, language)
    count_label = 'Cantidad' if language == 'es' else 'Count'
    text = f'{EVENT_LABELS[language][kind]}. {count_label}: {count}.'
    if entity_id is not None:
        text += f' ID: {entity_id}.'
    return text


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False
    token: str = field(default='', repr=False)
    chat_id: str = field(default='', repr=False)
    min_interval: float = 3.1
    max_messages: int = 10
    max_attempts: int = 3
    budget_seconds: float = 30.0
    timeout: float = 10.0
    max_response_bytes: int = 64 * 1024

    def __post_init__(self):
        valid = (type(self.enabled) is bool
                 and isinstance(self.token, str)
                 and (not self.token or re.fullmatch(r'[0-9]{1,20}:[A-Za-z0-9_-]{20,100}', self.token))
                 and isinstance(self.chat_id, str)
                 and (not self.chat_id or re.fullmatch(r'-?[1-9][0-9]{0,19}', self.chat_id)))
        for name, minimum, maximum in (
            ('max_messages', 1, 100), ('max_attempts', 1, 10),
            ('max_response_bytes', 1, 1024 * 1024),
        ):
            value = getattr(self, name)
            valid = valid and type(value) is int and minimum <= value <= maximum
        for name, minimum, maximum in (
            ('min_interval', 3.1, 3600), ('budget_seconds', 0.01, 3600),
            ('timeout', 0.01, 60),
        ):
            value = getattr(self, name)
            valid = (valid and type(value) in (int, float)
                     and minimum <= value <= maximum and math.isfinite(value))
        if not valid:
            raise WorkflowError('invalid_telegram_configuration')

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)


def load_telegram_config(environ=None) -> TelegramConfig:
    settings = os.environ if environ is None else environ
    value = settings.get('JOBSEARCH_TELEGRAM_ENABLED', 'false')
    if not isinstance(value, str) or value.strip().casefold() not in ('true', 'false'):
        raise WorkflowError('invalid_telegram_configuration')
    return TelegramConfig(enabled=value.strip().casefold() == 'true',
                          token=settings.get('JOBSEARCH_TELEGRAM_TOKEN', ''),
                          chat_id=settings.get('JOBSEARCH_TELEGRAM_CHAT_ID', ''))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TelegramTransport:
    """POST JSON to one fixed HTTPS host/method; no automatic retry/redirect.

    Construct the opener inside the call so a request can be isolated using the
    runtime's spawn-based BoundedTransport with normal proxy and CA trust.
    """

    def __call__(self, config: TelegramConfig, text: str, timeout: float,
                 max_bytes: int) -> HttpResponse:
        if not config.enabled or not config.configured:
            raise WorkflowError('telegram_not_configured')
        if not isinstance(text, str) or not 1 <= len(text) <= 4096:
            raise WorkflowError('invalid_notification_event')
        payload = json.dumps({
            'chat_id': config.chat_id, 'text': text,
            'link_preview_options': {'is_disabled': True},
            'allow_paid_broadcast': False,
        }, ensure_ascii=False, allow_nan=False).encode('utf-8')
        request = Request(f'https://api.telegram.org/bot{config.token}/sendMessage',
                          data=payload, method='POST', headers={
                              'Content-Type': 'application/json; charset=utf-8',
                              'Accept': 'application/json', 'Accept-Encoding': 'identity',
                              'User-Agent': 'job-search-assistant/1.0',
                          })
        try:
            opener = build_opener(_NoRedirect())
            try:
                with opener.open(request, timeout=timeout) as result:
                    return HttpResponse(result.status, dict(result.headers), result.read(max_bytes + 1))
            except HTTPError as error:
                try:
                    return HttpResponse(error.code, dict(error.headers), error.read(max_bytes + 1))
                finally:
                    error.close()
        except Exception:  # noqa: BLE001 - urllib/custom handlers may contain the token-bearing URL
            # urllib exceptions can contain the token-bearing URL or response.
            raise WorkflowError('telegram_transport_error') from None


@dataclass(frozen=True)
class TelegramRequest:
    """Pickleable adapter to the bounded runtime's three-argument protocol."""
    config: TelegramConfig
    text: str

    def __call__(self, _url: str, timeout: float, max_bytes: int) -> HttpResponse:
        return TelegramTransport()(self.config, self.text, timeout, max_bytes)
