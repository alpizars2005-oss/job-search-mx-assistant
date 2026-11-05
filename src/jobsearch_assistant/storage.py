"""Private whole-store snapshots and retention simulation; never sends or prunes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path, PurePosixPath

from .migrations import SCHEMA_VERSION, backup_database, restore_backup
from .private_storage import private_directory, private_fd, private_parents, private_path, read_private, sqlite_private, write_private
from .runtime_control import RunLock
from .workflow_contracts import WorkflowError, canonical_json, require_dry_run

_FILES = ('profile.json', 'settings.json', 'sources.json')
_TREES = ('resumes', 'reports', 'logs')



def backup_root(home):
    return private_path(os.getenv('JOB_SEARCH_ASSISTANT_BACKUPS', str(Path(home) / 'backups')))


def log_root(home):
    return private_path(os.getenv('JOB_SEARCH_ASSISTANT_LOGS', str(Path(home) / 'logs')))

def _hash(path, *, harden=False):
    descriptor = private_fd(path, harden=harden)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _walk(root, *, harden=False):
    root = private_directory(root, harden=harden)
    result = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in dirs:
            private_directory(parent / name, harden=harden)
        for name in names:
            path = parent / name
            descriptor = private_fd(path, harden=harden)
            os.close(descriptor)
            result[path.relative_to(root).as_posix()] = path
    return result


def _payload(home):
    files = {name: home / name for name in _FILES if os.path.lexists(home / name)}
    for name in _TREES:
        root = log_root(home) if name == 'logs' else home / name
        if os.path.lexists(root):
            for relative, path in _walk(root, harden=True).items():
                # Only completed immutable reports belong in a durable bundle.
                if name == 'reports' and any(part.startswith('.') for part in PurePosixPath(relative).parts):
                    continue
                files[name + '/' + relative] = path
    return files


def _copy_file(source, destination):
    private_parents(destination.parent)
    source_fd = private_fd(source)
    try:
        target_fd = private_fd(destination, create=True, writable=True)
    except BaseException:
        os.close(source_fd)
        raise
    with os.fdopen(source_fd, 'rb') as reader, os.fdopen(target_fd, 'wb') as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())


def _marker(path):
    connection = sqlite_private(path, read_only=True, timeout=0.1)
    try:
        if (connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                or connection.execute('PRAGMA foreign_key_check').fetchall()):
            raise WorkflowError('backup_integrity_failed')
        row = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not row or row[0] not in ('1', '2', '3', '4', str(SCHEMA_VERSION)):
            raise WorkflowError('backup_schema_unsupported')
        return int(row[0])
    finally:
        connection.close()


def _sync_directory(path):
    if os.name == 'posix':
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _publish(staging, destination):
    # The shared RunLock serializes cooperating writers. Reject an existing path,
    # including an empty directory; a completed manifest is the commit marker.
    if os.path.lexists(destination):
        raise FileExistsError()
    os.rename(staging, destination)
    _sync_directory(destination.parent)


def backup_bundle(home, destination, *, config=None):
    require_dry_run()
    home = private_directory(home)
    destination = private_path(destination)
    if os.path.lexists(destination):
        raise FileExistsError()
    if home == destination or (home in destination.parents and not (
            home / 'backups' in destination.parents)):
        raise WorkflowError('unsafe_backup_destination')
    private_parents(destination.parent)
    with RunLock(home / 'automation.lock'):
        files = _payload(home)
        before = {name: _hash(path, harden=True) for name, path in files.items()}
        # Config outside home is an import, not an adopted managed file.
        config_bytes = None
        if config is not None:
            from .sources.config import load_source_config
            from .workflow_cli import _read_text
            load_source_config(config)
            config_bytes = _read_text(Path(config), 65536).encode('utf-8')
        needed = sum(path.stat().st_size for path in files.values())
        needed += (home / 'applications.sqlite3').stat().st_size
        free = shutil.disk_usage(destination.parent)[2]
        if free < needed * 2 + 16 * 1024 * 1024:
            raise OSError('insufficient_backup_space')
        staging = Path(tempfile.mkdtemp(prefix='.bundle-', dir=destination.parent))
        private_directory(staging)
        try:
            backup_database(home / 'applications.sqlite3', staging / 'applications.sqlite3')
            for name, source in files.items():
                _copy_file(source, staging / name)
            if config_bytes is not None:
                write_private(staging / 'sources.json', config_bytes)
            after_files = _payload(home)
            after = {name: _hash(path, harden=True) for name, path in after_files.items()}
            if before != after:
                raise WorkflowError('backup_source_changed')
            if config is not None:
                from .workflow_cli import _read_text
                if _read_text(Path(config), 65536).encode('utf-8') != config_bytes:
                    raise WorkflowError('backup_source_changed')
            payload = _walk(staging)
            manifest = {'format_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                        'schema_version': _marker(staging / 'applications.sqlite3'),
                        'files': {name: _hash(path) for name, path in sorted(payload.items())}}
            write_private(staging / 'manifest.json', canonical_json(manifest).encode('utf-8'), overwrite=False)
            verify_bundle(staging)
            _sync_directory(staging)
            _publish(staging, destination)
            return manifest
        finally:
            if staging.exists():
                shutil.rmtree(staging)  # Only this invocation's exclusive temporary tree.


def verify_bundle(directory):
    """Verify exact inventory, content SHA and SQLite integrity, without mutation."""
    try:
        directory = private_directory(directory, harden=False)
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        manifest = json.loads(read_private(directory / 'manifest.json', 16 * 1024 * 1024,
                                           harden=False), object_pairs_hook=unique)
        if (not isinstance(manifest, dict) or set(manifest) != {
                'format_version', 'created_at', 'schema_version', 'files'}
                or type(manifest['format_version']) is not int or manifest['format_version'] != 1
                or type(manifest['schema_version']) is not int
                or not isinstance(manifest['files'], dict)):
            raise ValueError()
        observed = datetime.fromisoformat(manifest['created_at'])
        if observed.tzinfo is None or observed > datetime.now(timezone.utc) + timedelta(seconds=60):
            raise ValueError()
        for name, digest in manifest['files'].items():
            parts = PurePosixPath(name)
            if (not isinstance(name, str) or not name or '\\' in name or ':' in name
                    or parts.is_absolute() or any(p in ('', '.', '..') for p in name.split('/'))
                    or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
                raise ValueError()
        files = _walk(directory)
        files.pop('manifest.json', None)
        if set(files) != set(manifest['files']) or 'applications.sqlite3' not in files:
            raise ValueError()
        if any(_hash(files[name]) != digest for name, digest in manifest['files'].items()):
            raise ValueError()
        if _marker(directory / 'applications.sqlite3') != manifest['schema_version']:
            raise ValueError()
        return manifest
    except WorkflowError:
        raise
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        raise WorkflowError('backup_integrity_failed') from None


def restore_bundle(source, destination):
    require_dry_run()
    destination = private_path(destination)
    if os.path.lexists(destination):
        raise FileExistsError()
    manifest = verify_bundle(source)
    source = private_path(source)
    if source == destination or source in destination.parents:
        raise WorkflowError('unsafe_restore_destination')
    private_directory(destination.parent)
    staging = Path(tempfile.mkdtemp(prefix='.bundle-restore-', dir=destination.parent))
    private_directory(staging)
    try:
        for name in manifest['files']:
            if name != 'applications.sqlite3':
                _copy_file(source / name, staging / name)
        restore_backup(source / 'applications.sqlite3', staging / 'applications.sqlite3')
        # Detect a changed backup during copying, before exposing a usable home.
        if verify_bundle(source) != manifest or any(
                _hash(staging / name) != digest for name, digest in manifest['files'].items()
                if name != 'applications.sqlite3'):
            raise WorkflowError('backup_source_changed')
        _marker(staging / 'applications.sqlite3')
        write_private(staging / 'restore.json', canonical_json({
            'format_version': 1, 'restored_at': datetime.now(timezone.utc).isoformat(),
            'source_created_at': manifest['created_at'], 'source_review_required': True,
            'authorizations_revoked': True, 'submitted': False}).encode(), overwrite=False)
        _sync_directory(staging)
        _publish(staging, destination)
        return {'restored': True, 'source_review_required': True, 'submitted': False}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def inventory(home, *, retention_days=90, keep_backups=7, now=None):
    """Read-only age/size estimate; candidates are suggestions, never deletion."""
    if (type(retention_days) is not int or not 1 <= retention_days <= 36500
            or type(keep_backups) is not int or not 1 <= keep_backups <= 10000):
        raise WorkflowError('invalid_retention_policy')
    home = private_directory(home, harden=False)
    now = now or datetime.now(timezone.utc)
    categories = {'database': 0, 'resumes': 0, 'reports': 0, 'logs': 0, 'backups': 0, 'other': 0}
    total = 0
    for name, path in _walk(home).items():
        size = path.stat().st_size
        total += size
        first = name.split('/')[0]
        category = (first if first in ('resumes', 'reports', 'logs', 'backups') else
                    'database' if first.startswith('applications.sqlite3') else 'other')
        categories[category] += size
    candidates, retained, backups = [], [], []
    root = backup_root(home)
    if root.exists():
        if home not in root.parents:
            extra = _walk(root)
            extra_bytes = sum(path.stat().st_size for path in extra.values())
            total += extra_bytes
            categories['backups'] += extra_bytes
        for child in root.iterdir():
            if child.is_dir():
                manifest = verify_bundle(child)
                backups.append((manifest['created_at'], child.name))
    for index, (created, name) in enumerate(sorted(backups, reverse=True)):
        age = (now - datetime.fromisoformat(created)).total_seconds() / 86400
        item = {'backup': name, 'age_days': max(0, int(age))}
        (candidates if index >= keep_backups and age > retention_days else retained).append(item)
    return {'dry_run': True, 'deleted': 0, 'total_bytes': total, 'bytes_by_category': categories,
            'counts': {'backups': len(backups)}, 'retention_days': retention_days,
            'keep_backups': keep_backups, 'backup_candidates': candidates,
            'retained_backups': retained,
            'protected': ['active_database', 'resumes', 'evidence', 'candidacy_history', 'daily_reports'],
            'growth_estimate': 'unknown_until_repeated_measurements'}
