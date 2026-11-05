#!/usr/bin/env python3
"""Offline pinned releases for a future Debian 12 LXC; no resident scheduler.

No command enables timers or contacts a package index. `install`/`activate` are
explicit administration commands, never invoked by the application at startup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

DEFAULT_LAYOUT = {
    'code': '/opt/jobsearch-assistant',
    'state': '/var/lib/jobsearch-assistant',
    'config': '/etc/jobsearch-assistant',
    'logs': '/var/log/jobsearch-assistant',
    'backups': '/var/backups/jobsearch-assistant',
    'units': '/etc/systemd/system',
}
SHA = re.compile(r'[a-f0-9]{40}')
NAME = re.compile(r'[a-z][a-z0-9-]{0,30}')


class DeploymentError(ValueError):
    """Code-only error: never echo private paths or subprocess output."""


def _run(argv, *, env=None):
    # Never hand the administrator's credentials, Python import overrides or
    # pip install redirections to staged code or to the service account.
    clean = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8',
             'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
             'PIP_CONFIG_FILE': os.devnull, 'PIP_NO_INDEX': '1',
             'PIP_DISABLE_PIP_VERSION_CHECK': '1'}
    for key in ('HOME', 'USER', 'LOGNAME', 'JOB_SEARCH_ASSISTANT_HOME',
                'JOB_SEARCH_ASSISTANT_BACKUPS', 'JOB_SEARCH_ASSISTANT_LOGS',
                'DRY_RUN', 'AUTO_SUBMIT'):
        if env is not None and key in env:
            clean[key] = env[key]
    try:
        completed = subprocess.run(list(map(str, argv)), check=True, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=180, env=clean)
    except (OSError, subprocess.SubprocessError):
        raise DeploymentError('production_command_failed') from None
    return completed.stdout


def _read_regular(path, maximum=1024 * 1024):
    path = Path(path)
    _path_chain(path)
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or (hasattr(os, 'getuid') and before.st_uid not in (0, os.getuid()))
                or before.st_mode & 0o022):
            raise DeploymentError('unsafe_artifact')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise DeploymentError('unsafe_artifact')
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise DeploymentError('artifact_too_large')
        return data
    except OSError:
        raise DeploymentError('artifact_unavailable') from None


def _object(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise DeploymentError('invalid_manifest')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs)
    except (ValueError, TypeError, UnicodeError):
        raise DeploymentError('invalid_manifest') from None


def read_manifest(path, wheel, expected_commit):
    manifest = _object(_read_regular(path))
    wheel = Path(wheel)
    if (not isinstance(expected_commit, str) or SHA.fullmatch(expected_commit) is None
            or not isinstance(manifest, dict)
            or set(manifest) != {'format', 'project', 'commit', 'wheel', 'sha256', 'schema_version', 'python'}
            or type(manifest['format']) is not int or manifest['format'] != 1
            or manifest['project'] != 'job-search-assistant'
            or manifest['commit'] != expected_commit
            or manifest['python'] != '3.11'
            or type(manifest['schema_version']) is not int or not 1 <= manifest['schema_version'] <= 1000
            or not isinstance(manifest['wheel'], str)
            or re.fullmatch(r'job_search_assistant-[A-Za-z0-9._+-]+\.whl', manifest['wheel']) is None
            or manifest['wheel'] != wheel.name
            or not isinstance(manifest['sha256'], str)
            or re.fullmatch(r'[a-f0-9]{64}', manifest['sha256']) is None):
        raise DeploymentError('invalid_manifest')
    # Read from a verified no-follow fd, not a symlink-following hash API.
    if hashlib.sha256(_read_regular(wheel, 64 * 1024 * 1024)).hexdigest() != manifest['sha256']:
        raise DeploymentError('artifact_hash_mismatch')
    return manifest


def validate_platform(*, os_release, python_version, architecture, effective_uid, systemd_version):
    if os_release.get('ID') != 'debian' or os_release.get('VERSION_ID') != '12':
        raise DeploymentError('debian_12_required')
    if tuple(python_version[:2]) != (3, 11):
        raise DeploymentError('python_311_required')
    if architecture not in ('x86_64', 'aarch64'):
        raise DeploymentError('unverified_architecture')
    if effective_uid != 0:
        raise DeploymentError('administrative_root_required')
    if systemd_version < 252:
        raise DeploymentError('systemd_252_required')
    return {'os': 'debian12', 'python': '3.11', 'architecture': architecture,
            'systemd_version': systemd_version}


def preflight(python='/usr/bin/python3.11', runner=_run):
    if os.name != 'posix' or not hasattr(os, 'geteuid'):
        raise DeploymentError('debian_12_required')
    os_release = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            os_release[key] = value.strip('"')
    if os_release.get('ID') != 'debian' or os_release.get('VERSION_ID') != '12':
        raise DeploymentError('debian_12_required')
    version = runner([python, '-c', 'import sys,venv,sqlite3,ssl,zoneinfo; print(sys.version_info.major,sys.version_info.minor); zoneinfo.ZoneInfo("America/Mexico_City")'])
    try:
        python_version = tuple(map(int, version.strip().split()))
        systemd_version = int(runner(['systemd-analyze', '--version']).split()[1])
    except (ValueError, IndexError):
        raise DeploymentError('unrecognized_runtime') from None
    if not Path('/run/systemd/system').is_dir():
        raise DeploymentError('systemd_pid1_required')
    for name in ('getent', 'useradd', 'groupadd', 'runuser'):
        if shutil.which(name) is None:
            raise DeploymentError('missing_system_dependency')
    return validate_platform(os_release=os_release, python_version=python_version,
                             architecture=platform.machine(), effective_uid=os.geteuid(),
                             systemd_version=systemd_version)


def _path_chain(path, managed_uid=None):
    if not path.is_absolute() or '..' in path.parts or re.fullmatch(r'[A-Za-z0-9_./-]+', str(path)) is None:
        raise DeploymentError('unsafe_layout')
    for component in reversed((path, *path.parents)):
        if os.path.lexists(component):
            item = component.lstat()
            if stat.S_ISLNK(item.st_mode):
                raise DeploymentError('unsafe_layout')
            if component != path and (not stat.S_ISDIR(item.st_mode) or
                    (hasattr(os, 'getuid') and item.st_uid not in {0, os.getuid(), managed_uid}) or
                    (item.st_mode & 0o022 and not item.st_mode & stat.S_ISVTX)):
                raise DeploymentError('unsafe_layout')


def validate_layout(layout):
    if set(layout) != set(DEFAULT_LAYOUT):
        raise DeploymentError('invalid_layout')
    values = [Path(value) for value in layout.values()]
    for value in values:
        _path_chain(value)
        if value in (Path('/'), Path('/etc'), Path('/var'), Path('/opt'), Path('/home')):
            raise DeploymentError('unsafe_layout')
    for index, left in enumerate(values):
        for right in values[index + 1:]:
            if left == right or left in right.parents or right in left.parents:
                raise DeploymentError('overlapping_layout')
    return {key: Path(value) for key, value in layout.items()}


def _directory(path, *, uid=None, gid=None, mode=0o755):
    path = Path(path)
    _path_chain(path, managed_uid=uid)
    if not path.exists():
        if not path.parent.exists():
            _directory(path.parent)
        path.mkdir(mode=mode)
    before = path.lstat()
    current_uid = os.getuid() if hasattr(os, 'getuid') else 0
    allowed = {current_uid, current_uid if uid is None else uid}
    if not stat.S_ISDIR(before.st_mode) or before.st_uid not in allowed:
        raise DeploymentError('unsafe_managed_directory')
    # An administrator may repair only the exact managed directory, never its
    # general existing ancestors. Parent lookup above never chmods existing dirs.
    os.chmod(path, mode)
    if uid is not None and hasattr(os, 'chown'):
        os.chown(path, uid, gid)
    return path


def prepare_directories(layout, uid, gid):
    layout = validate_layout(layout)
    for key in ('code', 'config'):
        _directory(layout[key], mode=0o755 if key == 'code' else 0o750)
    for key in ('state', 'logs', 'backups'):
        _directory(layout[key], uid=uid, gid=gid, mode=0o700)
    if layout['units'].exists():
        _path_chain(layout['units'])
        info = layout['units'].stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise DeploymentError('unsafe_system_unit_directory')
    else:
        _directory(layout['units'], mode=0o755)
    for name in ('reports', 'resumes'):
        _directory(layout['state'] / name, uid=uid, gid=gid, mode=0o700)
    if hasattr(os, 'chown'):
        os.chown(layout['config'], os.getuid(), gid)


def _write_exclusive(path, data, mode=0o600, gid=None):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), mode)
    with os.fdopen(descriptor, 'wb') as stream:
        if os.name == 'posix':
            os.fchmod(stream.fileno(), mode)
            if gid is not None:
                os.fchown(stream.fileno(), os.getuid(), gid)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def write_environment(layout, gid):
    path = Path(layout['config']) / 'runtime.env'
    content = ('# Sin secretos; permisos root:grupo 0640. No habilita fuentes.\n'
               f'JOB_SEARCH_ASSISTANT_HOME={layout["state"]}\n'
               f'JOB_SEARCH_ASSISTANT_BACKUPS={layout["backups"]}\n'
               f'JOB_SEARCH_ASSISTANT_LOGS={layout["logs"]}\n'
               'DRY_RUN=true\nAUTO_SUBMIT=false\nPYTHONDONTWRITEBYTECODE=1\n')
    if os.path.lexists(path):
        existing = _read_regular(path).decode('utf-8')
        # Exact managed policy avoids accepting duplicate/overriding keys.
        if existing != content:
            raise DeploymentError('existing_environment_requires_manual_review')
        info = path.stat()
        if info.st_mode & 0o777 != 0o640 or info.st_gid != gid:
            raise DeploymentError('existing_environment_permissions_require_review')
        return
    _write_exclusive(path, content.encode(), 0o640, gid)



def _protect_release_tree(release):
    """Root-owned code must be readable/executable by the unprivileged service."""
    for directory, dirs, files in os.walk(release, followlinks=False):
        current = Path(directory)
        details = current.lstat()
        if details.st_uid != os.getuid() or not stat.S_ISDIR(details.st_mode):
            raise DeploymentError('unsafe_release_contents')
        current.chmod(0o755)
        for name in dirs + files:
            item = current / name
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode):
                # CPython venv on Debian aliases lib64; --copies avoids all
                # executable links so no chmod ever follows a symlink.
                if item != Path(release) / 'venv/lib64' or os.readlink(item) != 'lib':
                    raise DeploymentError('unsafe_release_contents')
                continue
            if info.st_uid != os.getuid() or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                raise DeploymentError('unsafe_release_contents')
            if stat.S_ISREG(info.st_mode):
                item.chmod(0o755 if info.st_mode & 0o111 else 0o644)
            elif not stat.S_ISDIR(info.st_mode):
                raise DeploymentError('unsafe_release_contents')


def stage_release(code, manifest_path, wheel, expected_commit, *, python='/usr/bin/python3.11', runner=_run):
    manifest = read_manifest(manifest_path, wheel, expected_commit)
    code = Path(code)
    _path_chain(code)
    releases = _directory(code / 'releases')
    release = releases / expected_commit
    if os.path.lexists(release):
        _path_chain(release)
        if _object(_read_regular(release / 'manifest.json')) != manifest:
            raise DeploymentError('existing_release_mismatch')
        read_manifest(release / 'manifest.json', release / manifest['wheel'], expected_commit)
        if not (release / 'venv' / 'bin' / 'python').is_file():
            raise DeploymentError('incomplete_release')
        return release
    # venv has absolute interpreter/script paths: create at its final immutable
    # pathname. A failed unactivated release is retained for diagnosis, never used.
    _directory(release, mode=0o755)
    venv = release / 'venv'
    runner([python, '-m', 'venv', '--copies', str(venv)])
    interpreter = str(venv / 'bin' / 'python')
    copied_wheel = release / manifest['wheel']
    artifact_bytes = _read_regular(wheel, 64 * 1024 * 1024)
    if hashlib.sha256(artifact_bytes).hexdigest() != manifest['sha256']:
        raise DeploymentError('artifact_hash_mismatch')
    _write_exclusive(copied_wheel, artifact_bytes, 0o644)
    runner([interpreter, '-m', 'pip', 'install', '--no-index', '--no-deps', '--disable-pip-version-check', str(copied_wheel)])
    runner([interpreter, '-m', 'pip', 'check'])
    runner([interpreter, '-c', 'from jobsearch_assistant.migrations import SCHEMA_VERSION; assert SCHEMA_VERSION == ' + str(manifest['schema_version'])])
    runner([interpreter, '-m', 'jobsearch_assistant', '--help'])
    # Smoke test uses no productive profile or network; synthesized defaults have
    # no verified professional assertions and all sources are disabled.
    with tempfile.TemporaryDirectory(prefix='jobsearch-install-smoke-') as smoke:
        os.chmod(smoke, 0o700)
        env = {**os.environ, 'JOB_SEARCH_ASSISTANT_HOME': str(Path(smoke) / 'state'),
               'DRY_RUN': 'true', 'AUTO_SUBMIT': 'false', 'PYTHONDONTWRITEBYTECODE': '1'}
        runner([interpreter, '-m', 'jobsearch_assistant', 'init'], env=env)
        runner([interpreter, '-m', 'jobsearch_assistant', 'automation', 'run', '--budget-seconds', '10'], env=env)
    _protect_release_tree(release)
    _write_exclusive(release / 'manifest.json', (json.dumps(manifest, sort_keys=True) + '\n').encode(), 0o644)
    return release


@contextmanager
def _runtime_lock(database):
    import fcntl  # Linux deployment only; desktop imports remain cross-platform.
    path = database.parent / 'automation.lock'
    db_stat = database.lstat() if database.exists() else database.parent.stat()
    before = path.lstat() if os.path.lexists(path) else None
    if before is not None and (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != db_stat.st_uid):
        raise DeploymentError('unsafe_runtime_lock')
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
                (before is not None and (opened.st_ino, opened.st_dev) != (before.st_ino, before.st_dev))):
            raise DeploymentError('unsafe_runtime_lock')
        if before is None:
            os.fchmod(descriptor, 0o600)
            os.fchown(descriptor, db_stat.st_uid, db_stat.st_gid)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeploymentError('runtime_busy_stop_timers_and_retry') from None
        yield
    finally:
        os.close(descriptor)


def _schema(database, service_uid, service_user=None, runner=_run):
    _path_chain(database, managed_uid=service_uid)
    if not database.exists():
        return None
    details = database.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_uid != service_uid:
        raise DeploymentError('unsafe_database')
    if os.getuid() != service_uid:
        if service_user is None or NAME.fullmatch(service_user) is None:
            raise DeploymentError('service_identity_required_for_database_read')
        program = ('import sqlite3,sys; from urllib.parse import quote; '
                   'c=sqlite3.connect("file:"+quote(sys.argv[1],safe="/")+"?mode=ro",uri=True,timeout=.1); '
                   'r=c.execute("SELECT value FROM meta WHERE key=\'schema_version\'").fetchone(); '
                   'c.close(); print(r[0] if r else "invalid")')
        result = runner(['runuser', '-u', service_user, '--', '/usr/bin/python3.11', '-c', program, str(database)]).strip()
        if not result.isdigit():
            raise DeploymentError('invalid_live_schema')
        return int(result)
    try:
        uri = 'file:' + quote(str(database), safe='/') + '?mode=ro'
        connection = sqlite3.connect(uri, uri=True, timeout=0.1)
        try:
            row = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if not row or not row[0].isdigit():
                raise DeploymentError('invalid_live_schema')
            return int(row[0])
        finally:
            connection.close()
    except sqlite3.Error:
        raise DeploymentError('invalid_live_schema') from None



def _verified_release(code, commit):
    release = Path(code) / 'releases' / commit
    _path_chain(release)
    raw = _object(_read_regular(release / 'manifest.json'))
    if not isinstance(raw, dict) or not isinstance(raw.get('wheel'), str):
        raise DeploymentError('invalid_release')
    manifest = read_manifest(release / 'manifest.json', release / raw['wheel'], commit)
    executable = release / 'venv/bin/jobsearch'
    _path_chain(executable)
    try:
        info = executable.lstat()
    except OSError:
        raise DeploymentError('incomplete_release') from None
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
            or not info.st_mode & 0o111 or info.st_mode & 0o022):
        raise DeploymentError('incomplete_release')
    return release, manifest


def activate_release(code, commit, database, *, service_uid=None, service_user=None):
    service_uid = os.getuid() if service_uid is None else service_uid
    if not isinstance(commit, str) or SHA.fullmatch(commit) is None:
        raise DeploymentError('invalid_commit')
    code, database = Path(code), Path(database)
    _path_chain(code)
    release, manifest = _verified_release(code, commit)
    current = code / 'current'
    if os.path.lexists(current):
        if not current.is_symlink():
            raise DeploymentError('unmanaged_current')
        old = Path(os.readlink(current))
        if not old.is_absolute():
            old = current.parent / old
        if old.parent != code / 'releases' or SHA.fullmatch(old.name) is None:
            raise DeploymentError('unmanaged_current')
    _path_chain(database, managed_uid=service_uid)
    if database.parent.stat().st_uid != service_uid:
        raise DeploymentError('unsafe_state_owner')
    with _runtime_lock(database):
        schema = _schema(database, service_uid, service_user)
        if schema is not None and manifest['schema_version'] != schema:
            raise DeploymentError('schema_change_requires_backup_restore_review')
        temporary = code / ('.current-' + uuid.uuid4().hex)
        try:
            temporary.symlink_to(release)
            os.replace(temporary, current)
            directory_fd = os.open(code, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
    return release



def verify_backup_for_activation(code, backup, database, service_user, *, service_uid, runner=_run):
    """Require a checked private complete bundle before switching existing data.

    The current approved release verifies bytes/SQLite. This guard additionally
    binds schema and age; it cannot establish freshness of a manually copied or
    forged backup. Stop timers and avoid all manual writers during maintenance.
    """
    if not database.exists():
        return
    if backup is None:
        raise DeploymentError('verified_backup_required')
    backup = Path(backup)
    _path_chain(backup, managed_uid=service_uid)
    descriptor = os.open(backup / 'manifest.json', os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        details = os.fstat(descriptor)
        if (not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
                or details.st_uid != service_uid or details.st_mode & 0o077):
            raise DeploymentError('unsafe_backup_manifest')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(1024 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(data) > 1024 * 1024:
        raise DeploymentError('invalid_backup_manifest')
    manifest = _object(data)
    try:
        if (not isinstance(manifest, dict) or manifest.get('format_version') != 1
                or type(manifest.get('schema_version')) is not int
                or manifest['schema_version'] != _schema(database, service_uid, service_user, runner)
                or not isinstance(manifest.get('files'), dict)
                or 'applications.sqlite3' not in manifest['files']):
            raise DeploymentError('invalid_backup_manifest')
        created = datetime.fromisoformat(manifest['created_at'])
        if created.tzinfo is None:
            raise ValueError()
        age = (datetime.now(timezone.utc) - created).total_seconds()
        if not 0 <= age <= 86400:
            raise DeploymentError('backup_stale_or_future')
    except (KeyError, TypeError, ValueError):
        raise DeploymentError('invalid_backup_manifest') from None
    current = Path(code) / 'current'
    if not current.is_symlink():
        raise DeploymentError('current_release_required_for_backup_verification')
    target = Path(os.readlink(current))
    if not target.is_absolute():
        target = current.parent / target
    if target.parent != Path(code) / 'releases' or SHA.fullmatch(target.name) is None:
        raise DeploymentError('unmanaged_current')
    _verified_release(code, target.name)
    if NAME.fullmatch(service_user) is None:
        raise DeploymentError('invalid_service_account')
    env = {**os.environ, 'JOB_SEARCH_ASSISTANT_HOME': str(database.parent),
           'DRY_RUN': 'true', 'AUTO_SUBMIT': 'false', 'PYTHONDONTWRITEBYTECODE': '1'}
    runner(['runuser', '-u', service_user, '--', str(target / 'venv' / 'bin' / 'jobsearch'),
            'storage', 'verify-backup', str(backup)], env=env)


def render_units(layout, user):
    layout = validate_layout(layout)
    if NAME.fullmatch(user) is None:
        raise DeploymentError('invalid_service_account')
    code, config = layout['code'], layout['config']
    environment = config / 'runtime.env'
    shared = (f'User={user}\nGroup={user}\nUMask=0077\n'
              'StateDirectory=jobsearch-assistant\nStateDirectoryMode=0700\n'
              f'WorkingDirectory={code}/current\nEnvironmentFile={environment}\n'
              f'Environment=DRY_RUN=true AUTO_SUBMIT=false JOB_SEARCH_ASSISTANT_HOME={layout["state"]}\n'
              'Environment=PYTHONDONTWRITEBYTECODE=1\n'
              'NoNewPrivileges=true\nCapabilityBoundingSet=\nAmbientCapabilities=\n'
              'LimitCORE=0\nTasksMax=16\nMemoryMax=512M\nCPUQuota=100%\n'
              'TimeoutStopSec=30\nKillMode=control-group\nRestart=no\n'
              'StandardOutput=journal\nStandardError=journal\nSyslogIdentifier=jobsearch-assistant\n')
    executable = f'{code}/current/venv/bin/jobsearch'
    search = ('[Unit]\nDescription=Job search finite discovery (no submissions)\n'
              'Wants=network-online.target\nAfter=network-online.target\n\n[Service]\nType=oneshot\n' + shared +
              'TimeoutStartSec=660\n' +
              f'ExecStart={executable} automation run --config {config}/sources.json --budget-seconds 600\n')
    report = ('[Unit]\nDescription=Private daily job search reports (no delivery)\n'
              'After=jobsearch-search.service\n\n[Service]\nType=oneshot\n' + shared +
              'TimeoutStartSec=120\n' +
              f'ExecStart={executable} reports generate --config {config}/sources.json --timezone America/Mexico_City --at 14:00 --max-reports 31\n')
    def timer(description, calendar, delay, unit):
        return (f'[Unit]\nDescription={description}\n\n[Timer]\nOnCalendar={calendar}\n'
                f'Persistent=true\nRandomizedDelaySec={delay}\nAccuracySec=1s\nUnit={unit}\n\n'
                '[Install]\nWantedBy=timers.target\n')
    return {'jobsearch-search.service': search,
            'jobsearch-search.timer': timer('Hourly finite job discovery', '*-*-* *:00:00 America/Mexico_City', 120, 'jobsearch-search.service'),
            'jobsearch-report.service': report,
            'jobsearch-report.timer': timer('Daily private report at 14:00 Mexico City', '*-*-* 14:00:00 America/Mexico_City', 0, 'jobsearch-report.service')}


def prepare_account(user, state, runner=_run):
    import grp
    import pwd
    if NAME.fullmatch(user) is None:
        raise DeploymentError('invalid_service_account')
    try:
        group = grp.getgrnam(user)
    except KeyError:
        runner(['groupadd', '--system', user])
        group = grp.getgrnam(user)
    try:
        account = pwd.getpwnam(user)
    except KeyError:
        runner(['useradd', '--system', '--gid', user, '--home-dir', str(state), '--shell', '/usr/sbin/nologin', user])
        account = pwd.getpwnam(user)
    if (account.pw_uid == 0 or account.pw_gid != group.gr_gid
            or account.pw_shell not in ('/usr/sbin/nologin', '/sbin/nologin', '/bin/false')
            or account.pw_dir != str(state)
            or set(os.getgrouplist(user, group.gr_gid)) != {group.gr_gid}):
        raise DeploymentError('existing_service_account_requires_review')
    return account.pw_uid, group.gr_gid


def write_units(layout, user):
    for name, text in render_units(layout, user).items():
        destination = Path(layout['units']) / name
        if os.path.lexists(destination):
            if _read_regular(destination).decode() != text:
                raise DeploymentError('existing_unit_requires_manual_review')
        else:
            _write_exclusive(destination, text.encode(), 0o644)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout', type=Path, help='Root-owned JSON of absolute managed paths')
    parser.add_argument('--python', default='/usr/bin/python3.11')
    parser.add_argument('--user', default='jobsearch-assistant')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('preflight')
    for name in ('install', 'activate', 'rollback'):
        command = sub.add_parser(name)
        command.add_argument('--commit', required=True)
        command.add_argument('--apply', action='store_true', help='Required for explicit administrative changes')
        if name != 'install':
            command.add_argument('--backup', type=Path, help='Verified whole-store bundle, required if SQLite exists')
        if name == 'install':
            command.add_argument('--manifest', type=Path, required=True)
            command.add_argument('--wheel', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = preflight(args.python)
        layout = validate_layout(_object(_read_regular(args.layout)) if args.layout else DEFAULT_LAYOUT)
        if args.command == 'preflight':
            print(json.dumps({'status': 'ok', **result, 'timers_enabled': False}))
            return 0
        if not args.apply:
            raise DeploymentError('explicit_apply_required')
        if args.command == 'install':
            read_manifest(args.manifest, args.wheel, args.commit)
        elif SHA.fullmatch(args.commit) is None:
            raise DeploymentError('invalid_commit')
        uid, gid = prepare_account(args.user, layout['state'])
        prepare_directories(layout, uid, gid)
        write_environment(layout, gid)
        if args.command == 'install':
            stage_release(layout['code'], args.manifest, args.wheel, args.commit, python=args.python)
            write_units(layout, args.user)
            sources = layout['config'] / 'sources.json'
            if not os.path.lexists(sources):
                _write_exclusive(sources, b'{"schema_version":1,"sources":[]}\n', 0o640, gid)
            else:
                _read_regular(sources)
            # Do not create a production profile, activate code, reload or start timers.
            print(json.dumps({'status': 'staged', 'commit': args.commit, 'timers_enabled': False,
                              'requires_profile_review': True}))
        else:
            verify_backup_for_activation(layout['code'], args.backup, layout['state'] / 'applications.sqlite3',
                                         args.user, service_uid=uid)
            activate_release(layout['code'], args.commit, layout['state'] / 'applications.sqlite3', service_uid=uid, service_user=args.user)
            print(json.dumps({'status': 'activated', 'commit': args.commit, 'timers_enabled': False,
                              'requires_systemd_reload_and_pilot': True}))
        return 0
    except (DeploymentError, OSError, ValueError, KeyError) as error:
        code = str(error) if isinstance(error, DeploymentError) else 'production_storage_or_configuration_error'
        print(json.dumps({'status': 'error', 'code': code}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
