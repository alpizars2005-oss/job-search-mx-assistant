from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Mapping

PROVIDERS = ('greenhouse', 'lever', 'ashby')
BOARD_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')


class SourceError(Exception):
    """A stable diagnostic code; never includes remote bodies, URLs or exceptions."""

    def __init__(self, code: str, *, rejected: int = 0):
        self.code = code
        self.rejected = rejected
        super().__init__(code)


@dataclass(frozen=True)
class SourceConfig:
    provider: str
    board: str
    company: str
    enabled: bool = False

    def __post_init__(self):
        if not isinstance(self.provider, str) or self.provider not in PROVIDERS:
            raise ValueError('invalid provider')
        if not isinstance(self.board, str) or not BOARD_PATTERN.fullmatch(self.board):
            raise ValueError('invalid board')
        if (not isinstance(self.company, str) or not self.company.strip()
                or len(self.company) > 200 or any(ord(c) < 32 for c in self.company)):
            raise ValueError('invalid company')
        if type(self.enabled) is not bool:
            raise ValueError('enabled must be a boolean')


@dataclass(frozen=True)
class RequestPolicy:
    timeout: float = 15.0
    max_requests: int = 20
    max_retries: int = 3
    backoff_base: float = 1.0
    max_backoff: float = 30.0
    max_wait: float = 30.0
    error_threshold: int = 5
    pause_seconds: float = 300.0
    min_interval: float = 1.0
    max_response_bytes: int = 5 * 1024 * 1024
    max_pages: int = 10
    page_size: int = 100

    def __post_init__(self):
        integer_bounds = {
            'max_requests': (1, 1000), 'max_retries': (0, 10),
            'error_threshold': (1, 100), 'max_response_bytes': (1, 20 * 1024 * 1024),
            'max_pages': (1, 100), 'page_size': (1, 1000),
        }
        for name, (minimum, maximum) in integer_bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f'invalid {name}')
        for name in ('timeout', 'backoff_base', 'max_backoff', 'max_wait',
                     'pause_seconds', 'min_interval'):
            value = getattr(self, name)
            minimum = 0 if name in ('max_wait', 'min_interval') else 0.001
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not minimum <= value <= 3600):
                raise ValueError(f'invalid {name}')


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class NormalizedJob:
    source: str
    source_board: str
    source_job_id: str
    company: str
    title: str | None
    locations: list[str]
    work_mode: str
    url: str | None
    description: str | None
    published_at: str | None
    retrieved_at: str
    verification_status: str
    eligibility_evidence: dict
    provenance: dict[str, list[str]]


@dataclass
class SourceReport:
    source: str
    board: str
    status: str = 'disabled'
    requests: int = 0
    rejected: int = 0
    duplicates: int = 0
    issues: list[str] = field(default_factory=list)


@dataclass
class DiscoveryResult:
    jobs: list[NormalizedJob]
    reports: list[SourceReport]

    def to_dict(self) -> dict:
        return asdict(self)
