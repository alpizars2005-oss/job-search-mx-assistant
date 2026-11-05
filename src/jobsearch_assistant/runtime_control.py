"""Finite cooperative runs, a local OS mutex and terminable HTTP calls."""
from __future__ import annotations

import math
import multiprocessing
import os
import stat
import threading
import time
from pathlib import Path

from .sources.models import HttpResponse, SourceError
from .workflow_contracts import WorkflowError


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
            raise SourceError('run_cancelled')
        if not self.remaining():
            raise SourceError('run_deadline')

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

    def __init__(self, path):
        self.path = Path(path)
        self._file = None

    def __enter__(self):
        if self._file is not None:
            raise WorkflowError('run_locked')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            try:
                existing = self.path.lstat()
            except FileNotFoundError:
                existing = None
            if existing is not None and not stat.S_ISREG(existing.st_mode):
                raise WorkflowError('invalid_run_lock')
            flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            descriptor = os.open(self.path, flags, 0o600)
        except OSError:
            raise WorkflowError('invalid_run_lock') from None
        file = os.fdopen(descriptor, 'r+b', buffering=0)
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
        except OSError:
            file.close()
            raise WorkflowError('run_locked') from None
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
            connection.send(('network_error', None))
        else:
            connection.send(('response', response))
    except SourceError as error:
        connection.send(('source_error', error.code))
    except Exception:  # noqa: BLE001 - Never expose arbitrary transport exceptions across IPC.
        connection.send(('network_error', None))
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
        try:
            process.start()
            writer.close()
            while True:
                self.control.check()
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError('request_timeout')
                if reader.poll(min(remaining, self.control.remaining(), 0.05)):
                    self.control.check()
                    try:
                        kind, value = reader.recv()
                    except (EOFError, OSError):
                        raise OSError('network_error') from None
                    self.control.check()
                    if kind == 'response':
                        return value
                    if kind == 'source_error':
                        raise SourceError(value)
                    raise OSError('network_error')
                if not process.is_alive():
                    raise OSError('network_error')
        finally:
            writer.close()
            reader.close()
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=0.2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=0.2)
                process.close()
