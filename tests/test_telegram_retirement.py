"""Retired transport: retain historical bytes, prevent all new delivery intents."""
import importlib.util
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant import migrations
from jobsearch_assistant.automation_store import AutomationStore
from jobsearch_assistant.config import default_profile
from jobsearch_assistant.database import ApplicationDatabase
from test_automation_migrations import make_three


def make_four(path):
    make_three(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        migrations._migrate_v3_to_v4(connection)
        connection.execute('INSERT INTO notification_delivery_state(id) VALUES(1)')
        connection.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
        connection.execute("INSERT INTO notification_outbox(event_key,kind,event_count,language,created_at,updated_at) VALUES ('historical','priority',1,'es','old','old')")
        connection.execute("INSERT INTO automation_runs(id,started_at,status,config_digest,profile_digest,notifications_json) VALUES('old','old','success','c','p','{\"sent\":1}')")
        connection.execute("INSERT INTO automation_notification_health VALUES(1,'old','{\"status\":\"delivery_failed\"}','old')")


def history(path):
    with closing(sqlite3.connect(path)) as connection:
        return {table: connection.execute('SELECT * FROM ' + table).fetchall() for table in
                ('notification_outbox', 'notification_delivery_state', 'automation_notification_health')}


class TelegramRetirementTests(unittest.TestCase):
    def test_schema_five_failure_rolls_back_and_preserves_backup_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite3'
            make_four(path)
            before = path.read_bytes()
            migrate = migrations._migrate_v4_to_v5
            def fail(connection):
                migrate(connection)
                raise RuntimeError('synthetic interruption')
            with patch.object(migrations, '_migrate_v4_to_v5', fail), self.assertRaises(RuntimeError):
                ApplicationDatabase(path)
            self.assertEqual(path.read_bytes(), before)
            backup = next(path.parent.glob('*.schema4-*.bak'))
            self.assertEqual(history(backup), history(path))
            ApplicationDatabase(path)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_no_importable_delivery_runtime(self):
        for module in ('telegram', 'notifications'):
            self.assertIsNone(importlib.util.find_spec('jobsearch_assistant.' + module))

    def test_upgrade_keeps_history_and_blocks_legacy_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite3'
            make_four(path)
            before = history(path)
            database = ApplicationDatabase(path)
            self.assertEqual(history(path), before)
            backups = list(path.parent.glob('*.schema4-*.bak'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(history(backups[0]), before)
            with database._connection() as connection:
                for table in before:
                    for sql in ('DELETE FROM ' + table, 'UPDATE ' + table + ' SET id=id',
                                'INSERT INTO ' + table + ' SELECT * FROM ' + table):
                        with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                            connection.execute(sql)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("UPDATE automation_runs SET notifications_json='{}' WHERE id='old'")
                self.assertEqual(connection.execute("SELECT notifications_json FROM automation_runs WHERE id='old'").fetchone()[0], '{"sent":1}')

    def test_new_runs_create_no_delivery_intents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite3'
            database = ApplicationDatabase(path)
            before = history(path)
            store = AutomationStore(database)
            run = store.start('c', 'p')
            # A high priority result used to create a Telegram event.
            from test_candidacies import synthetic_job
            store.observe(run, synthetic_job(), default_profile())
            store.finish(run, 'success', [])
            self.assertEqual(history(path), before)
            self.assertFalse(hasattr(store, 'record_notifications'))
            self.assertNotIn('notifications', store.show(run))

    def test_restore_never_rewrites_retired_history_and_quarantines_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite3'
            make_four(path)
            before = history(path)
            for name in ('four', 'five'):
                if name == 'five':
                    ApplicationDatabase(path)
                restored = path.parent / (name + '.sqlite3')
                migrations.restore_backup(path, restored)
                self.assertEqual(history(restored), before)
                with closing(sqlite3.connect(restored)) as connection:
                    self.assertEqual(connection.execute("SELECT value FROM meta WHERE key='source_review_required'").fetchone()[0], '1')
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute('DELETE FROM notification_outbox')


if __name__ == '__main__':
    unittest.main()
