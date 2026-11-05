"""Finite cooperative runs, a local OS mutex and terminable HTTP calls."""
from __future__ import annotations

import math
import errno
import multiprocessing
import os
import stat
import json
import threading
import time
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError

from .sources.models import HttpResponse, SourceError
from .workflow_contracts import WorkflowError
from .private_storage import private_fd, private_parents, private_path


LOCAL_CONTROL_CODES = frozenset({
    'run_cancelled', 'run_deadline', 'worker_failed', 'worker_cleanup_failed',
})


class LocalControlError(SourceError):
    """A local interruption, optionally after a real provider failure arrived."""

    def __init__(self, code, *, provider_issue=None, rejected=0,
                 response=None, worker_pid=None):
        super().__init__(code, rejected=rejected)
        self.provider_issue = provider_issue
        self.response = response
        self.worker_pid = worker_pid


class RunControl:
    def __init__(self, seconds, cancelled=None, monotonic=time.monotonic):
        if (type(seconds) not in (int, float) or not math.isfinite(seconds)
                or seconds < 0):
            raise ValueError('invalid run budget')
        self._monotonic = monotonic
        self._deadline = monotonic() + seconds
        self._cancelled = cancelled or (lambda: False)

    def remaining(self) -> float:
        return max(0.0, self._deadline - self._monotonic())

    def check(self) -> None:
        cancelled = self._cancelled
        if (cancelled() if callable(cancelled) else cancelled.is_set()):
            raise LocalControlError('run_cancelled')
        if not self.remaining():
            raise LocalControlError('run_deadline')

    def sleep(self, delay) -> None:
        if (type(delay) not in (int, float) or not math.isfinite(delay)
                or delay < 0):
            raise ValueError('invalid sleep delay')
        until = self._monotonic() + delay
        while True:
            self.check()
            remaining = until - self._monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, self.remaining(), 0.05))


class RunLock:
    """Nonblocking advisory lock on a stable file, released by the kernel."""

    def __init__(self, path, *, budget_seconds=None):
        self.path = Path(path)
        self._file = None
        if budget_seconds is not None and (type(budget_seconds) not in (int, float)
                or not math.isfinite(budget_seconds) or not 0 < budget_seconds <= 86400):
            raise WorkflowError('invalid_run_budget')
        self.budget_seconds = budget_seconds

    def __enter__(self):
        if self._file is not None:
            raise WorkflowError('run_locked')
        try:
            self.path = private_path(self.path)
            private_parents(self.path.parent)
            descriptor = private_fd(self.path, create=True, writable=True)
        except OSError:
            raise WorkflowError('invalid_run_lock') from None
        file = os.fdopen(descriptor, 'r+b', buffering=0)
        acquired = False
        try:
            opened, current = os.fstat(descriptor), self.path.lstat()
            if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(current.st_mode)
                    or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)):
                raise WorkflowError('invalid_run_lock')
            if os.name == 'nt':
                import msvcrt
                if os.fstat(descriptor).st_size == 0:
                    file.write(b'\0')
                file.seek(0)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            # Diagnostic metadata is useful only while this same inode is
            # locked. The kernel lock, never a PID or timestamp alone, proves
            # activity. No private paths or configuration cross this boundary.
            payload = json.dumps({'version': 1,
                                  'acquired_at': datetime.now(timezone.utc).isoformat(),
                                  'budget_seconds': self.budget_seconds}).encode('ascii')
            file.seek(0)
            file.write(b'\0' + payload)
            file.truncate()
            file.flush()
        except OSError:
            file.close()
            raise WorkflowError('invalid_run_lock' if acquired else 'run_locked') from None
        except BaseException:
            file.close()
            raise
        self._file = file
        return self

    def __exit__(self, exc_type, exc, traceback):
        file, self._file = self._file, None
        if file is not None:
            try:
                if os.name == 'nt':
                    import msvcrt
                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)
            finally:
                file.close()


def probe_run_lock(path):
    """Observe an existing OS mutex without creating, chmodding or rewriting it.

    A stale file is harmless: only a lock held by the kernel counts. Windows
    needs a writable descriptor for its byte-range API; no bytes are written.
    """
    try:
        descriptor = private_fd(path, harden=False, writable=os.name == 'nt')
    except FileNotFoundError:
        return {'state': 'free', 'metadata': None}
    except OSError:
        return {'state': 'unknown', 'metadata': None}
    with os.fdopen(descriptor, 'r+b' if os.name == 'nt' else 'rb', buffering=0) as file:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            return {'state': 'free', 'metadata': None}
        except OSError as error:
            # Windows reports a byte-range conflict as EACCES/EDEADLK. Other
            # failures cannot establish that a legitimate holder exists.
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return {'state': 'unknown', 'metadata': None}
        try:
            # Byte zero is the Windows mutex range; its mandatory lock also
            # blocks reads from another descriptor. Metadata starts after it.
            file.seek(1)
            raw = file.read(4097)
            metadata = json.loads(raw) if len(raw) <= 4096 else None
        except (OSError, ValueError, UnicodeError):
            metadata = None
        return {'state': 'held', 'metadata': metadata}


def _transport_worker(connection, transport, url, timeout, max_bytes):
    """Only public result data/codes cross the process boundary."""
    finished = threading.Event()
    parent = multiprocessing.parent_process()
    deadline = time.monotonic() + timeout

    def watch_parent():
        # multiprocessing daemon cleanup does not run after a parent SIGKILL.
        # An orphan must stop even if urllib is stuck in a slow read or DNS.
        while not finished.wait(0.05):
            if time.monotonic() >= deadline or (parent is not None and not parent.is_alive()):
                os._exit(1)

    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        if transport is None:
            from .sources.http import UrllibTransport
            transport = UrllibTransport()
        response = transport(url, timeout, max_bytes)
        if not isinstance(response, HttpResponse):
            connection.send(('source_error', 'worker_failed'))
        else:
            connection.send(('response', response))
    except SourceError as error:
        connection.send(('source_error', error.code))
    except (URLError, OSError, TimeoutError, HTTPException):
        connection.send(('network_error', None))
    except Exception:  # noqa: BLE001 - Never expose arbitrary transport exceptions across IPC.
        connection.send(('source_error', 'worker_failed'))
    finally:
        finished.set()
        connection.close()


class BoundedTransport:
    """Run blocking transport work in a spawned, terminable subprocess.

    An injected transport must be pickleable; the default constructs urllib
    inside the worker to preserve normal proxy and certificate behavior.
    """

    def __init__(self, control, transport=None):
        self.control = control
        self.transport = transport

    def __call__(self, url, timeout, max_bytes) -> HttpResponse:
        self.control.check()
        started = time.monotonic()
        context = multiprocessing.get_context('spawn')
        reader, writer = context.Pipe(duplex=False)
        process = context.Process(target=_transport_worker,
                                  args=(writer, self.transport, url, timeout, max_bytes),
                                  daemon=True)
        completed_response = None
        try:
            process.start()
            writer.close()
            while True:
                # Hand off a completed response before cancellation. Its caller
                # must checkpoint server cooldowns before doing further work.
                ready = reader.poll(0)
                if not ready:
                    self.control.check()
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise TimeoutError('request_timeout')
                    ready = reader.poll(min(remaining, self.control.remaining(), 0.05))
                if ready:
                    try:
                        kind, value = reader.recv()
                    except (EOFError, OSError):
                        raise LocalControlError('worker_failed') from None
                    if kind == 'response':
                        completed_response = value
                        return value
                    if kind == 'source_error':
                        if value in LOCAL_CONTROL_CODES:
                            raise LocalControlError(value)
                        raise SourceError(value)
                    raise OSError('network_error')
                if not process.is_alive():
                    raise LocalControlError('worker_failed')
        finally:
            writer.close()
            reader.close()
            if process.pid is not None:
                if process.is_alive():
                    try:
                        process.terminate()
                    except OSError:
                        pass  # Still attempt the bounded kill escalation below.
                process.join(timeout=0.2)
                if process.is_alive():
                    try:
                        process.kill()
                    except OSError:
                        pass
                    process.join(timeout=0.2)
                if process.is_alive():
                    raise LocalControlError('worker_cleanup_failed', response=completed_response,
                                            worker_pid=process.pid)
                process.close()
