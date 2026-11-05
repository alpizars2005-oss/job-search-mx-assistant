import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant import migrations
from jobsearch_assistant.database import ApplicationDatabase
from test_migrations import make_legacy, contents, version


def make_three(path):
    make_legacy(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        migrations._migrate_v1_to_v2(connection)
        migrations._migrate_v2_to_v3(connection)
        connection.execute("UPDATE meta SET value='3' WHERE key='schema_version'")


class AutomationMigrationTests(unittest.TestCase):
    def test_schema_three_upgrade_has_original_backup_and_unchanged_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'db.sqlite3'
            make_three(path)
            before = contents(path)
            ApplicationDatabase(path)
            self.assertEqual(version(path), '4')
            self.assertEqual(contents(path), before)
            backup = list(Path(tmp).glob('*.schema3-*.bak'))
            self.assertEqual(len(backup), 1)
            self.assertEqual(version(backup[0]), '3')
            self.assertEqual(contents(backup[0]), before)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
                connection.execute('SELECT * FROM automation_runs')
                connection.execute('SELECT * FROM notification_outbox')

    def test_restore_schema_three_keeps_version_and_all_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'old.sqlite3'
            make_three(path)
            restored = Path(tmp) / 'restored.sqlite3'
            migrations.restore_backup(path, restored)
            self.assertEqual(version(restored), '3')
            self.assertEqual(contents(restored), contents(path))

    def test_upgrade_failure_rolls_back_new_tables_and_preserves_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'old.sqlite3'
            make_three(path)
            before = path.read_bytes()
            migrate = getattr(migrations, '_migrate_v3_to_v4', None)
            self.assertIsNotNone(migrate, 'Phase-five migration missing')
            def fail(connection):
                migrate(connection)
                raise RuntimeError('synthetic failure')
            with patch.object(migrations, '_migrate_v3_to_v4', fail), self.assertRaises(RuntimeError):
                ApplicationDatabase(path)
            self.assertEqual(version(path), '3')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(version(next(Path(tmp).glob('*.schema3-*.bak'))), '3')

    def test_process_dies_during_schema_four_upgrade_then_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'old.sqlite3'
            make_three(path)
            original = contents(path)
            script = '''
import os, sys
from pathlib import Path
from jobsearch_assistant import migrations
original=migrations._migrate_v3_to_v4
def interrupted(connection):
    original(connection)
    os._exit(39)
migrations._migrate_v3_to_v4=interrupted
migrations.initialize_database(Path(sys.argv[1]))
'''
            result = subprocess.run([sys.executable, '-c', script, str(path)], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 39)
            self.assertEqual(version(path), '3')
            self.assertEqual(contents(path), original)
            ApplicationDatabase(path)
            self.assertEqual(version(path), '4')
            self.assertEqual(contents(path), original)


if __name__ == '__main__':
    unittest.main()
