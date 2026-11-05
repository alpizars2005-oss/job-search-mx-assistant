import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.automation_cli import health
from jobsearch_assistant.automation_store import AutomationStore
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.runtime_control import RunLock, probe_run_lock


class OperationalHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.database = ApplicationDatabase(self.home / 'applications.sqlite3')
        self.store = AutomationStore(self.database)

    def started(self):
        return self.store.start('synthetic-config', 'synthetic-profile')

    def test_active_run_with_legitimate_mutex_is_healthy(self):
        with RunLock(self.home / 'automation.lock', budget_seconds=120):
            run_id = self.started()
            result = health(self.database.path)
        self.assertTrue(result['healthy'])
        self.assertEqual(result['code'], 'active')
        self.assertEqual(result['last_run_id'], run_id)
        self.assertEqual(result['execution']['state'], 'active')
        self.assertIsNone(result['last_success'])

    def test_running_without_mutex_is_abandoned_and_health_creates_no_lock(self):
        self.started()
        result = health(self.database.path)
        self.assertFalse(result['healthy'])
        self.assertEqual(result['code'], 'abandoned')
        self.assertFalse((self.home / 'automation.lock').exists())

    def test_overdue_mutex_is_delayed_not_healthy(self):
        with RunLock(self.home / 'automation.lock', budget_seconds=0.05):
            self.started()
            now = datetime.now(timezone.utc) + timedelta(seconds=31)
            result = health(self.database.path, now=now)
        self.assertFalse(result['healthy'])
        self.assertEqual(result['code'], 'delayed')

    def test_success_failure_recovery_and_staleness_have_separate_diagnostics(self):
        first = self.started()
        self.store.finish(first, 'success', [])
        second = self.started()
        self.store.finish(second, 'interrupted', [])
        result = health(self.database.path)
        self.assertFalse(result['healthy'])
        self.assertEqual(result['code'], 'run_unhealthy')
        self.assertEqual(result['last_success']['run_id'], first)
        self.assertEqual(result['last_failure']['run_id'], second)
        third = self.started()
        self.store.finish(third, 'success', [])
        self.assertEqual(health(self.database.path)['code'], 'ok')
        result = health(self.database.path, 1, now=datetime.now(timezone.utc) + timedelta(seconds=2))
        self.assertEqual(result['code'], 'stale')

    def test_source_failure_remains_visible_during_active_run(self):
        with self.database._connection() as connection:
            connection.execute('''INSERT INTO automation_source_health VALUES
                ('greenhouse',2,'synthetic',NULL,?,'error')''',
                (datetime.now(timezone.utc).isoformat(),))
        with RunLock(self.home / 'automation.lock', budget_seconds=120):
            self.started()
            result = health(self.database.path)
        self.assertFalse(result['healthy'])
        self.assertEqual(result['code'], 'source_degraded')
        self.assertEqual(result['execution']['state'], 'active')
        self.assertEqual(result['sources'][0]['failures'], 2)

    def test_old_telegram_faults_are_history_and_health_is_read_only(self):
        run_id = self.started()
        self.store.finish(run_id, 'success', [])
        paths = [self.database.path]
        before = [(path.stat().st_mode, path.stat().st_mtime_ns) for path in paths]
        result = health(self.database.path)
        after = [(path.stat().st_mode, path.stat().st_mtime_ns) for path in paths]
        self.assertTrue(result['healthy'])
        self.assertNotIn('notifications', result)
        self.assertNotIn('last_delivery', result)
        self.assertEqual(before, after)

    def test_probe_existing_mutex_does_not_write_or_change_permissions(self):
        with RunLock(self.home / 'automation.lock', budget_seconds=120) as lock:
            self.started()
            path = self.home / 'automation.lock'
            lock._file.seek(0)
            before = (lock._file.read(), path.stat().st_mode, path.stat().st_mtime_ns)
            result = health(self.database.path)
            lock._file.seek(0)
            after = (lock._file.read(), path.stat().st_mode, path.stat().st_mtime_ns)
        self.assertEqual(result['code'], 'active')
        self.assertEqual(before, after)

    def test_malformed_mutex_metadata_does_not_prove_active_run(self):
        with RunLock(self.home / 'automation.lock', budget_seconds=120) as lock:
            self.started()
            lock._file.seek(1)
            lock._file.write(json.dumps({'budget_seconds': 'private'}).encode())
            lock._file.truncate()
            result = health(self.database.path)
        self.assertFalse(result['healthy'])
        self.assertEqual(result['code'], 'lock_unknown')
        self.assertNotIn('private', json.dumps(result))

    def test_corrupt_metadata_date_or_future_clock_is_unknown_not_database_failure(self):
        for value in (None, 12, 'PRIVATE', '2026-11-04T14:00:00'):
            with self.subTest(value=value), RunLock(self.home / 'automation.lock', budget_seconds=120) as lock:
                self.started()
                lock._file.seek(1)
                lock._file.write(json.dumps({
                    'version': 1, 'acquired_at': value, 'budget_seconds': 120}).encode())
                lock._file.truncate()
                result = health(self.database.path)
            self.assertEqual(result['code'], 'lock_unknown')
            self.assertFalse(result['healthy'])
            self.assertNotIn('PRIVATE', json.dumps(result))

    def test_recovered_run_no_longer_appears_active_or_abandoned(self):
        abandoned = self.started()
        with RunLock(self.home / 'automation.lock', budget_seconds=120):
            current = self.started()
            self.assertEqual(health(self.database.path)['code'], 'active')
            self.store.finish(current, 'success', [])
        result = health(self.database.path)
        self.assertEqual(result['code'], 'ok')
        self.assertEqual(result['last_failure']['run_id'], abandoned)
        self.assertEqual(result['last_failure']['status'], 'interrupted')

    def test_completion_during_health_does_not_create_abandoned_alarm(self):
        lock = RunLock(self.home / 'automation.lock', budget_seconds=120)
        lock.__enter__()
        self.addCleanup(lock.__exit__, None, None, None)
        run_id = self.started()
        calls = []
        def completing_probe(path):
            calls.append(path)
            if len(calls) == 1:
                self.store.finish(run_id, 'success', [])
                lock.__exit__(None, None, None)
            return probe_run_lock(path)
        with patch('jobsearch_assistant.automation_cli.probe_run_lock', side_effect=completing_probe):
            result = health(self.database.path)
        self.assertTrue(result['healthy'])
        self.assertIn(result['code'], ('active', 'ok'))


if __name__ == '__main__':
    unittest.main()
