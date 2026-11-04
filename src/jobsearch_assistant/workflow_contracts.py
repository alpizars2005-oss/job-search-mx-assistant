"""Shared content bindings and fail-closed policy for the local-only workflow."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from .sources.models import NormalizedJob


class WorkflowError(ValueError):
    """A stable code; never interpolate private inputs into a diagnostic."""

    def __init__(self, code: str):
        self.code = code if isinstance(code, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}', code) else 'workflow_error'
        super().__init__(self.code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def vacancy_key(job: NormalizedJob) -> list[str]:
    return [job.source, job.source_board, job.source_job_id]


def vacancy_digest(job: NormalizedJob) -> str:
    """Bind content, including evidence, independently of a repeated observation."""
    payload = asdict(job)
    payload.pop('retrieved_at')
    return content_digest(payload)


def require_dry_run(environ: Mapping | None = None) -> dict[str, bool]:
    settings = os.environ if environ is None else environ
    for name, expected in (('DRY_RUN', 'true'), ('AUTO_SUBMIT', 'false')):
        value = settings.get(name, expected)
        if not isinstance(value, str) or value.strip().casefold() != expected:
            raise WorkflowError('unsafe_runtime_policy')
    return {'dry_run': True, 'auto_submit': False}
