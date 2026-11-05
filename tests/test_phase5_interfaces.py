import json
import os
import subprocess
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.cli import main
from jobsearch_assistant.config import default_profile
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.notifications import NotificationDispatcher
from jobsearch_assistant.sources.models import HttpResponse, SourceError


class AutomationInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {
            'JOB_SEARCH_ASSISTANT_HOME': str(self.home), 'DRY_RUN': 'true', 'AUTO_SUBMIT': 'false',
            'JOBSEARCH_TELEGRAM_ENABLED': 'false', 'JOBSEARCH_TELEGRAM_TOKEN': '',
            'JOBSEARCH_TELEGRAM_CHAT_ID': '',
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        (self.home / 'profile.json').write_text(json.dumps(default_profile().to_dict()), encoding='utf-8')

    def cli(self, *args):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch.object(sys, 'argv', ['jobsearch', *args]):
            try:
                main()
            except SystemExit as exit:
                code = exit.code
            else:
                code = 0
        return code, out.getvalue(), err.getvalue()

    def test_one_shot_empty_run_history_and_health_are_redacted_json(self):
        code, out, err = self.cli('automation', 'run')
        self.assertEqual(code, 0, err)
        run = json.loads(out)
        self.assertEqual(run['status'], 'success')
        self.assertEqual(run['counts']['total'], 0)
        self.assertIs(run['submitted'], False)
        code, history, err = self.cli('automation', 'runs')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(history)[0]['run_id'], run['run_id'])
        code, shown, err = self.cli('automation', 'show', run['run_id'])
        self.assertEqual(json.loads(shown)['run_id'], run['run_id'])
        code, health, err = self.cli('automation', 'health')
        self.assertEqual(code, 0, err)
        self.assertIs(json.loads(health)['healthy'], True)
        self.assertNotIn(str(self.home), out + history + shown + health)

    def test_unsafe_policy_fails_before_database_or_network(self):
        with patch.dict(os.environ, {'AUTO_SUBMIT': 'true'}):
            code, out, err = self.cli('automation', 'run')
        self.assertEqual(code, 2)
        self.assertIn('unsafe_runtime_policy', err)
        self.assertFalse((self.home / 'applications.sqlite3').exists())

    def test_invalid_profile_never_falls_back_or_rewrites_input(self):
        path = self.home / 'profile.json'
        path.write_text('{"headline":"PRIVATE SECRET", "skills":false}', encoding='utf-8')
        before = path.read_bytes()
        code, out, err = self.cli('automation', 'run')
        self.assertEqual(code, 2)
        self.assertIn('invalid_automation_profile', err)
        self.assertNotIn('PRIVATE', out + err)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.home / 'applications.sqlite3').exists())

    def test_health_is_read_only_and_missing_database_not_created(self):
        code, out, err = self.cli('automation', 'health')
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)['code'], 'database_unavailable')
        self.assertFalse((self.home / 'applications.sqlite3').exists())

    def test_zero_budget_is_rejected_and_no_run_started(self):
        code, out, err = self.cli('automation', 'run', '--budget-seconds', '0')
        self.assertEqual(code, 2)
        self.assertIn('invalid_run_budget', err)
        self.assertFalse((self.home / 'applications.sqlite3').exists())

    def test_notify_without_configuration_is_disabled_without_network(self):
        code, out, err = self.cli('automation', 'run', '--notify')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['notifications']['status'], 'disabled')

    def delivery(self, transport):
        def dispatcher(database, config, *, control):
            return NotificationDispatcher(database, config, transport=transport, control=control)
        return patch('jobsearch_assistant.automation_cli.NotificationDispatcher', side_effect=dispatcher)

    def telegram_env(self):
        return patch.dict(os.environ, {'JOBSEARCH_TELEGRAM_ENABLED': 'true',
                                      'JOBSEARCH_TELEGRAM_TOKEN': '123:' + 'X' * 25,
                                      'JOBSEARCH_TELEGRAM_CHAT_ID': '123456'})

    def test_delivery_failure_or_uncertainty_is_durable_and_degrades_exit_and_health(self):
        for status, expected in ((403, 'delivery_failed'), (503, 'delivery_uncertain')):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                (home / 'profile.json').write_text(json.dumps(default_profile().to_dict()))
                fake = lambda *args: HttpResponse(status, {'Content-Type': 'application/json'},
                                                 b'{"ok":false,"error_code":403,"description":"PRIVATE"}')
                with patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': tmp}), self.telegram_env(), self.delivery(fake):
                    code, out, err = self.cli('automation', 'run', '--notify')
                    self.assertEqual(code, 1, err)
                    result = json.loads(out)
                    self.assertEqual(result['status'], 'success')  # Search succeeded, delivery did not.
                    self.assertEqual(result['notifications']['status'], expected)
                    shown = json.loads(self.cli('automation', 'show', result['run_id'])[1])
                    self.assertEqual(shown['notifications'], result['notifications'])
                    history = json.loads(self.cli('automation', 'runs')[1])
                    self.assertEqual(history[0]['notifications'], result['notifications'])
                    health = self.cli('automation', 'health')
                    self.assertEqual(health[0], 1)
                    self.assertEqual(json.loads(health[1])['code'], 'notification_unhealthy')
                    self.assertNotIn('PRIVATE', out + err + health[1])
                    self.assertEqual(self.cli('automation', 'run')[0], 0)
                    # An unrelated search without a drain cannot erase the delivery diagnostic.
                    self.assertEqual(self.cli('automation', 'health')[0], 1)

    def test_notification_storage_failure_remains_visible_after_restart(self):
        database = ApplicationDatabase(self.home / 'applications.sqlite3')
        with database._connection() as connection:
            connection.execute('''CREATE TRIGGER synthetic_delivery_failure BEFORE UPDATE ON notification_outbox
                WHEN NEW.status='sending' BEGIN SELECT RAISE(ABORT,'PRIVATE DB failure'); END''')
        def no_transport(*args):
            self.fail('Failed SQLite claim must never send')
        with self.telegram_env(), self.delivery(no_transport):
            code, out, err = self.cli('automation', 'run', '--notify')
        self.assertEqual(code, 1, err)
        result = json.loads(out)
        self.assertEqual(result['notifications']['status'], 'notification_storage_error')
        self.assertEqual(self.cli('automation', 'health')[0], 1)
        self.assertEqual(json.loads(self.cli('automation', 'show', result['run_id'])[1])['notifications']['status'],
                         'notification_storage_error')
        self.assertNotIn('PRIVATE', out + err)

    def test_notification_deadline_and_cancel_preserve_specific_exit_codes(self):
        for error, expected in (('run_deadline', 4), ('run_cancelled', 130)):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / 'profile.json').write_text(json.dumps(default_profile().to_dict()))
                def interrupted(*args):
                    raise SourceError(error)
                with patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': tmp}), self.telegram_env(), self.delivery(interrupted):
                    code, out, err = self.cli('automation', 'run', '--notify')
                self.assertEqual(code, expected, err)
                self.assertEqual(json.loads(out)['notifications']['status'], error)

    def test_sqlite_writer_cannot_block_past_total_run_budget(self):
        self.assertEqual(self.cli('automation', 'run')[0], 0)
        connection = sqlite3.connect(self.home / 'applications.sqlite3')
        try:
            connection.execute('BEGIN IMMEDIATE')
            started = time.monotonic()
            result = subprocess.run([sys.executable, '-m', 'jobsearch_assistant', 'automation', 'run',
                                     '--budget-seconds', '0.05'],
                                    capture_output=True, text=True, timeout=2)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertIn(result.returncode, (2, 4), result.stderr)
        finally:
            connection.rollback()
            connection.close()

    @unittest.skipIf(os.name == 'nt', 'POSIX FIFO input')
    def test_nonregular_source_config_is_rejected_without_blocking(self):
        fifo = self.home / 'sources.json'
        os.mkfifo(fifo)
        result = subprocess.run([sys.executable, '-m', 'jobsearch_assistant', 'automation', 'run',
                                 '--config', str(fifo)], capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(str(fifo), result.stderr)

    def test_two_cli_processes_exclude_then_recover_after_kill(self):
        marker = self.home / 'in-transport'
        config = self.home / 'sources.json'
        config.write_text(json.dumps({'schema_version': 1, 'sources': [
            {'provider': 'greenhouse', 'board': 'synthetic', 'company': 'Synthetic', 'enabled': True}
        ], 'limits': {'max_retries': 0}}), encoding='utf-8')
        script = '''
import sys, time
from pathlib import Path
from unittest.mock import patch
from jobsearch_assistant.sources.http import SafeHttpClient
from jobsearch_assistant.runtime_control import RunControl
from jobsearch_assistant.cli import main
marker=Path(sys.argv[1])
config=sys.argv[2]
def blocked(*args):
    marker.write_text('ready')
    time.sleep(60)
client=SafeHttpClient(transport=blocked,control=RunControl(30))
sys.argv=['jobsearch','automation','run','--config',config]
with patch('jobsearch_assistant.automation.SafeHttpClient',return_value=client):
    main()
'''
        worker = subprocess.Popen([sys.executable, '-c', script, str(marker), str(config)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            until = time.monotonic() + 10
            while not marker.exists() and worker.poll() is None and time.monotonic() < until:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), 'Worker did not acquire lock/start HTTP')
            second = subprocess.run([sys.executable, '-m', 'jobsearch_assistant', 'automation', 'run'],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(second.returncode, 3, second.stderr)
            self.assertIn('run_locked', second.stderr)
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=5)
        code, out, err = self.cli('automation', 'run')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['recovered_runs'], 1)
        history = json.loads(self.cli('automation', 'runs')[1])
        self.assertEqual({r['status'] for r in history}, {'success', 'interrupted'})


if __name__ == '__main__':
    unittest.main()
