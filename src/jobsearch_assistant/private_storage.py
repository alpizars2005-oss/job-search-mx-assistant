"""Private local storage boundaries; imported external inputs are never chmodded."""
from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
from pathlib import Path


class PrivateStorageError(PermissionError):
    def __init__(self, code='unsafe_private_storage'):
        self.code = code
        super().__init__(code)


def _owned(info):
    return os.name != 'posix' or info.st_uid == os.geteuid()


def _identity(info):
    return info.st_dev, info.st_ino


def private_path(value) -> Path:
    """Inspect original components before abspath can collapse link/../ escapes."""
    raw = os.fspath(value)
    if not isinstance(raw, str) or '://' in raw or '\0' in raw:
        raise PrivateStorageError()
    original = Path(raw).expanduser().absolute()
    for component in reversed((original, *original.parents)):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_reparse_tag', 0):
            raise PrivateStorageError('private_storage_symlink')
        if component != original and not stat.S_ISDIR(info.st_mode):
            raise PrivateStorageError()
        if os.name == 'posix' and stat.S_ISDIR(info.st_mode):
            # Shared sticky /tmp may contain an owned private directory. Other
            # users must not be able to replace any non-sticky ancestor.
            if info.st_uid not in (0, os.geteuid()):
                raise PrivateStorageError('private_storage_owner')
            if (component != original and info.st_mode & 0o022
                    and not (info.st_mode & stat.S_ISVTX)):
                raise PrivateStorageError('private_storage_parent_writable')
    return Path(os.path.abspath(original))


def private_directory(value, *, harden=True) -> Path:
    path = private_path(value)
    if not path.exists():
        if not harden:
            raise FileNotFoundError()
        private_parents(path.parent)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or not _owned(info):
        raise PrivateStorageError('private_storage_owner')
    if path == path.parent or info.st_mode & stat.S_ISVTX:
        raise PrivateStorageError('private_storage_shared_directory')
    if os.name == 'posix':
        if harden:
            # A restrictive umask can create 000. The validated parent cannot
            # be replaced by another UID; restore owner access before opening.
            os.chmod(path, 0o700, follow_symlinks=False)
        elif stat.S_IMODE(info.st_mode) != 0o700:
            raise PrivateStorageError('private_storage_permissions')
        flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        descriptor = os.open(path, flags)
        try:
            if _identity(os.fstat(descriptor)) != _identity(info):
                raise PrivateStorageError('private_storage_replaced')
            if harden:
                os.fchmod(descriptor, 0o700)
        finally:
            os.close(descriptor)
    return path


def private_parents(value) -> Path:
    """Create only missing parents privately; never chmod general existing dirs."""
    path = private_path(value)
    if not path.exists():
        private_parents(path.parent)
        return private_directory(path)
    if not path.is_dir():
        raise PrivateStorageError()
    info = path.lstat()
    if os.name == 'posix' and info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
        raise PrivateStorageError('private_storage_parent_writable')
    return path


def _regular(info, *, immutable=False):
    if not stat.S_ISREG(info.st_mode) or not _owned(info):
        raise PrivateStorageError('private_storage_owner_or_type')
    if info.st_nlink != 1 and not (
            immutable and (os.name != 'posix' or stat.S_IMODE(info.st_mode) == 0o600)):
        raise PrivateStorageError('private_storage_hardlink')


def private_fd(value, *, create=False, harden=True, immutable=False, writable=False) -> int:
    path = private_path(value)
    created = False
    try:
        before = path.lstat()
    except FileNotFoundError:
        if not create:
            raise
        private_parents(path.parent)
        try:
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL
                                 | getattr(os, 'O_BINARY', 0), 0o600)
        except FileExistsError:
            return private_fd(path, create=False, harden=harden, immutable=immutable, writable=writable)
        before, created = os.fstat(descriptor), True
    else:
        _regular(before, immutable=immutable)
        if os.name == 'posix':
            if harden and before.st_nlink == 1:
                os.chmod(path, 0o600, follow_symlinks=False)
            elif stat.S_IMODE(before.st_mode) != 0o600:
                raise PrivateStorageError('private_storage_permissions')
        descriptor = os.open(path, (os.O_RDWR if writable else os.O_RDONLY) | getattr(os, 'O_BINARY', 0)
                             | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        current = os.fstat(descriptor)
        _regular(current, immutable=immutable)
        if (_identity(current) != _identity(before)
                or _identity(path.lstat()) != _identity(current)):
            raise PrivateStorageError('private_storage_replaced')
        if os.name == 'posix' and harden and current.st_nlink == 1:
            os.fchmod(descriptor, 0o600)
        return descriptor
    except BaseException:
        os.close(descriptor)
        if created:
            try:
                if _identity(path.lstat()) == _identity(before):
                    path.unlink()
            except FileNotFoundError:
                pass
        raise


def protect_private_file(value, *, create=False, harden=True) -> Path:
    path = private_path(value)
    descriptor = private_fd(path, create=create, harden=harden)
    os.close(descriptor)
    return path


def read_private(value, maximum, *, harden=True, immutable=False) -> bytes:
    descriptor = private_fd(value, harden=harden, immutable=immutable)
    with os.fdopen(descriptor, 'rb') as handle:
        raw = handle.read() if maximum is None else handle.read(maximum + 1)
    if maximum is not None and len(raw) > maximum:
        raise ValueError('private_input_too_large')
    return raw


def write_private(value, payload: bytes, *, overwrite=True) -> Path:
    path = private_path(value)
    private_parents(path.parent)
    previous = None
    if os.path.lexists(path):
        if not overwrite:
            raise FileExistsError()
        protect_private_file(path)
        previous = path.lstat()
    descriptor, temporary = tempfile.mkstemp(prefix='.private-', dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            if os.name == 'posix':
                os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if previous is not None:
            current = path.lstat()
            _regular(current)
            if _identity(current) != _identity(previous):
                raise PrivateStorageError('private_storage_replaced')
            os.replace(temporary, path)
        else:
            # No replacement of an object created concurrently or a dangling link.
            os.link(temporary, path)
        return path
    finally:
        temporary.unlink(missing_ok=True)


def _external_sqlite_file(path, *, sidecar=False):
    """Validate a read-only input without adopting its owner or permissions."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise PrivateStorageError('private_storage_owner_or_type')
    # SQLite may coordinate readers in SHM; never let that touch an alias or
    # another user's object. The main input is opened with SQL mode=ro.
    if sidecar and (not _owned(before) or before.st_nlink != 1):
        raise PrivateStorageError('private_storage_unsafe_sidecar')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0)
                         | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        current = os.fstat(descriptor)
        if (not stat.S_ISREG(current.st_mode) or _identity(current) != _identity(before)
                or _identity(path.lstat()) != _identity(current)):
            raise PrivateStorageError('private_storage_replaced')
    finally:
        os.close(descriptor)



def _check_sqlite_sidecars(path, *, external_source, harden):
    for suffix in ('-wal', '-shm', '-journal'):
        sidecar = Path(str(path) + suffix)
        if os.path.lexists(sidecar):
            try:
                if external_source:
                    _external_sqlite_file(sidecar, sidecar=True)
                else:
                    protect_private_file(sidecar, harden=harden)
            except FileNotFoundError:
                # A concurrent SQLite writer may legitimately close/remove its
                # auxiliary file. Other validation failures still fail closed.
                continue

def sqlite_private(value, *, timeout=30, read_only=False, harden=None, external_source=False, **options):
    if external_source and not read_only:
        raise PrivateStorageError('external_sqlite_requires_readonly')
    if harden is None:
        harden = not read_only
    path = private_path(value)
    if not read_only:
        private_parents(path.parent)
    parent = path.parent.stat()
    if os.name == 'posix' and parent.st_mode & 0o022:
        raise PrivateStorageError('sqlite_parent_writable')
    if external_source:
        _external_sqlite_file(path)
    else:
        path = protect_private_file(path, create=not read_only, harden=harden)
    before = path.lstat()
    _check_sqlite_sidecars(path, external_source=external_source, harden=harden)
    target = path.as_uri() + '?mode=ro' if read_only else path
    connection = sqlite3.connect(target, timeout=timeout, uri=read_only, **options)
    try:
        if _identity(path.lstat()) != _identity(before):
            raise PrivateStorageError('private_storage_replaced')
        connection.execute('PRAGMA temp_store=MEMORY')
        _check_sqlite_sidecars(path, external_source=external_source, harden=harden)
        return connection
    except BaseException:
        connection.close()
        raise
