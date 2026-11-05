from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from .http import _invalid_constant, _unique_object
from .models import RequestPolicy, SourceConfig

MAX_CONFIG_BYTES = 65536


def load_source_config(path: Path | None) -> tuple[list[SourceConfig], RequestPolicy]:
    """Read an explicit bounded JSON config, independently of private profiles."""
    if path is None:
        return [], RequestPolicy()
    try:
        path = Path(path)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as handle:
            current = os.fstat(handle.fileno())
            if (not stat.S_ISREG(current.st_mode)
                    or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)):
                raise ValueError
            raw = handle.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            raise ValueError
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
        if (not isinstance(data, dict) or set(data) - {'schema_version', 'sources', 'limits'}
                or type(data.get('schema_version')) is not int or data['schema_version'] != 1
                or not isinstance(data.get('sources'), list) or len(data['sources']) > 100):
            raise ValueError
        limits = data.get('limits', {})
        if not isinstance(limits, dict) or set(limits) - set(RequestPolicy.__dataclass_fields__):
            raise ValueError
        policy = RequestPolicy(**limits)
        configs, seen = [], set()
        for row in data['sources']:
            if not isinstance(row, dict) or set(row) - set(SourceConfig.__dataclass_fields__):
                raise ValueError
            config = SourceConfig(**row)
            key = (config.provider, config.board)
            if key in seen:
                raise ValueError
            seen.add(key)
            configs.append(config)
        return configs, policy
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('invalid_source_configuration') from None
