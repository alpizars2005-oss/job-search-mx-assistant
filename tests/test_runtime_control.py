import importlib
import multiprocessing
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.sources.models import HttpResponse, SourceError
from jobsearch_assistant.workflow_contracts import WorkflowError


class SlowTransport:
    def __init__(self, marker):
        self.marker = marker

    def __call__(self, url, timeout, max_bytes):
        Path(self.marker).write_text(str(os.getpid()), encoding='ascii')
        time.sleep(60)
        return HttpResponse(200, {}, b'{}')


class SmallTransport:
    def __call__(self, url, timeout, max_bytes):
        return HttpResponse(200, {'Content-Type': 'application/json'}, b'{"ok":true}')


class RateLimitedTransport:
    def __call__(self, url, timeout, max_bytes):
        return HttpResponse(429, {'Retry-After': '3600'}, b'')


class SlowBodyTransport:
    """Exercise the stdlib body's read boundary without a real endpoint."""

    def __call__(self, url, timeout, max_bytes):
        from jobsearch_assistant.sources.http import UrllibTransport

        class SlowBody:
            status = 200

            def __init__(self):
                self.headers = {'Content-Type': 'application/json'}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, amount):
                time.sleep(60)
                return b'{}'

        transport = UrllibTransport()
        with patch.object(transport.opener, 'open', return_value=SlowBody()):
            return transport(url, timeout, max_bytes)


class RunControlTests(unittest.TestCase):
    def runtime(self):
        return importlib.import_module('jobsearch_assistant.runtime_control')

    def assert_code(self, code, function, error_type=SourceError):
        with self.assertRaises(error_type) as caught:
            function()
        self.assertEqual(caught.exception.code, code)

    def test_deadline_uses_monotonic_and_remaining_never_negative(self):
        clock = [10.0]
        control = self.runtime().RunControl(3, monotonic=lambda: clock[0])
        self.assertEqual(control.remaining(), 3)
        clock[0] = 13
        self.assertEqual(control.remaining(), 0)
        self.assert_code('run_deadline', control.check)
        clock[0] = 20
        self.assertEqual(control.remaining(), 0)

    def test_cancellation_interrupts_check_and_sleep(self):
        cancelled = [False]
        control = self.runtime().RunControl(10, cancelled=lambda: cancelled[0])
        cancelled[0] = True
        self.assert_code('run_cancelled', control.check)
        self.assert_code('run_cancelled', lambda: control.sleep(5))

    def test_completed_response_handoff_survives_cancellation_during_ipc_receive(self):
        runtime = self.runtime()
        cancelled = threading.Event()
        control = runtime.RunControl(10, cancelled=cancelled)
        context = multiprocessing.get_context('spawn')
        original_pipe = context.Pipe
        class Received:
            def __init__(self, reader):
                self.reader = reader
            def poll(self, *args):
                return self.reader.poll(*args)
            def recv(self):
                result = self.reader.recv()
                cancelled.set()
                return result
            def close(self):
                self.reader.close()
        def pipe(*args, **kwargs):
            reader, writer = original_pipe(*args, **kwargs)
            return Received(reader), writer
        with patch.object(context, 'Pipe', side_effect=pipe):
            result = runtime.BoundedTransport(control, RateLimitedTransport())('https://example.test', 5, 1024)
        self.assertEqual(result.status, 429)
        self.assertEqual(result.headers['Retry-After'], '3600')
        self.assert_code('run_cancelled', control.check)

    def test_sleep_cannot_cross_run_budget(self):
        runtime = self.runtime()
        clock = [0.0]
        control = runtime.RunControl(0.2, monotonic=lambda: clock[0])
        with patch.object(runtime.time, 'sleep', side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)):
            self.assert_code('run_deadline', lambda: control.sleep(10))
        self.assertAlmostEqual(clock[0], 0.2)

    def test_invalid_budget_is_rejected_without_waiting(self):
        for value in (-1, True, float('nan'), float('inf'), '10'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.runtime().RunControl(value)

    def start_holder(self, path):
        script = ('from jobsearch_assistant.runtime_control import RunLock; '
                  'import sys; '
                  'lock = RunLock(sys.argv[1]); lock.__enter__(); '
                  'print("locked", flush=True); sys.stdin.read()')
        process = subprocess.Popen([sys.executable, '-c', script, str(path)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_holder, process)
        self.assertEqual(process.stdout.readline().strip(), 'locked')
        return process

    @staticmethod
    def stop_holder(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    @staticmethod
    def stop_orphan(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def test_lock_excludes_other_process_and_survives_as_same_file(self):
        runtime = self.runtime()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'automation.lock'
            process = self.start_holder(path)
            inode = path.stat().st_ino
            self.assert_code('run_locked', lambda: runtime.RunLock(path).__enter__(), WorkflowError)
            process.stdin.close()
            process.stdin = None
            process.wait(timeout=5)
            with runtime.RunLock(path):
                self.assertEqual(path.stat().st_ino, inode)
            self.assertTrue(path.exists())

    def test_kernel_releases_lock_when_owner_is_killed(self):
        runtime = self.runtime()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'automation.lock'
            process = self.start_holder(path)
            process.kill()
            process.wait(timeout=5)
            with runtime.RunLock(path):
                self.assertTrue(path.exists())

    def test_lock_excludes_second_owner_in_same_process(self):
        runtime = self.runtime()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'automation.lock'
            with runtime.RunLock(path):
                self.assert_code('run_locked', lambda: runtime.RunLock(path).__enter__(), WorkflowError)

    def test_lock_rejects_symlink_without_modifying_target(self):
        runtime = self.runtime()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'private-file'
            target.write_bytes(b'private-value')
            path = Path(directory) / 'automation.lock'
            try:
                path.symlink_to(target)
            except OSError:
                self.skipTest('symlinks unavailable for this account')
            self.assert_code('invalid_run_lock', lambda: runtime.RunLock(path).__enter__(), WorkflowError)
            self.assertEqual(target.read_bytes(), b'private-value')

    def test_lock_rejects_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assert_code('invalid_run_lock', lambda: self.runtime().RunLock(directory).__enter__(), WorkflowError)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO requires POSIX')
    def test_lock_rejects_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'automation.lock'
            os.mkfifo(path)
            self.assert_code('invalid_run_lock', lambda: self.runtime().RunLock(path).__enter__(), WorkflowError)

    def test_bounded_transport_returns_response(self):
        runtime = self.runtime()
        transport = runtime.BoundedTransport(runtime.RunControl(5), SmallTransport())
        response = transport('synthetic', 3, 100)
        self.assertEqual(response.body, b'{"ok":true}')

    def test_hanging_transport_is_terminated_at_run_deadline(self):
        runtime = self.runtime()
        with tempfile.TemporaryDirectory() as directory:
            marker = str(Path(directory) / 'child.pid')
            transport = runtime.BoundedTransport(runtime.RunControl(1), SlowTransport(marker))
            started = time.monotonic()
            self.assert_code('run_deadline', lambda: transport('synthetic', 15, 100))
            self.assertLess(time.monotonic() - started, 3)
            self.assertTrue(Path(marker).exists())
            pid = int(Path(marker).read_text(encoding='ascii'))
            self.assertNotIn(pid, [child.pid for child in multiprocessing.active_children()])

    def test_slow_stdlib_body_is_terminated_at_request_timeout(self):
        runtime = self.runtime()
        transport = runtime.BoundedTransport(runtime.RunControl(5), SlowBodyTransport())
        url = 'https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true'
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            transport(url, 0.5, 100)
        self.assertLess(time.monotonic() - started, 2)

    def test_cancellation_terminates_hanging_transport(self):
        runtime = self.runtime()
        started = time.monotonic()
        control = runtime.RunControl(5, cancelled=lambda: time.monotonic() - started > 0.5)
        with tempfile.TemporaryDirectory() as directory:
            transport = runtime.BoundedTransport(control, SlowTransport(str(Path(directory) / 'child.pid')))
            self.assert_code('run_cancelled', lambda: transport('synthetic', 10, 100))
        self.assertLess(time.monotonic() - started, 2)

    def test_worker_exits_when_parent_is_killed(self):
        self.runtime()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'worker.pid'
            script = ('import sys; from jobsearch_assistant.runtime_control import BoundedTransport, RunControl; '
                      'from test_runtime_control import SlowTransport; '
                      'BoundedTransport(RunControl(30), SlowTransport(sys.argv[1]))("synthetic", 20, 100)')
            environment = dict(os.environ)
            environment['PYTHONPATH'] = str(Path(__file__).parent) + os.pathsep + environment.get('PYTHONPATH', '')
            process = subprocess.Popen([sys.executable, '-c', script, str(marker)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
            self.addCleanup(self.stop_holder, process)
            until = time.monotonic() + 5
            while not marker.exists() and process.poll() is None and time.monotonic() < until:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), 'worker did not start')
            worker_pid = int(marker.read_text(encoding='ascii'))
            process.kill()
            # A surviving spawned worker retains these inherited standard pipes.
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                self.stop_orphan(worker_pid)
                raise
            if os.name != 'nt' and Path('/proc').exists():
                stat = Path('/proc') / str(worker_pid) / 'stat'
                if stat.exists():
                    self.assertEqual(stat.read_text(encoding='ascii').split()[2], 'Z')
