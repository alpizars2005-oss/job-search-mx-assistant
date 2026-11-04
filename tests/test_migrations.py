import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant import migrations
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.models import ApplicationRecord, EvaluationResult, JobPosting

LEGACY_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta VALUES ('schema_version', '1');
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, company TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '', score INTEGER NOT NULL,
    recommendation TEXT NOT NULL, evaluation_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'saved', notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


def make_legacy(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        for record_id, status, notes in ((3, 'saved', 'Primera nota'), (8, 'applied', 'Second note')):
            connection.execute(
                'INSERT INTO applications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (record_id, 'Python Developer', 'Synthetic Co', 'Remote',
                 'https://example.test/Jobs/ABC', 'Synthetic description', 82, 'strong_fit',
                 '{ "score": 82, "recommendation": "strong_fit", "reasons": ["original"] }',
                 status, notes, '2024-02-03T04:05:06Z', '2024-03-04T05:06:07Z'),
            )


def contents(path):
    with sqlite3.connect(path) as connection:
        return connection.execute('SELECT * FROM applications ORDER BY id').fetchall()


def version(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]


class MigrationTests(unittest.TestCase):
    def test_migration_preserves_every_legacy_value_and_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            make_legacy(path)
            before = contents(path)
            database = ApplicationDatabase(path)
            self.assertEqual(version(path), '2')
            self.assertEqual(contents(path), before)
            self.assertEqual([item.id for item in database.list()], [8, 3])
            self.assertEqual(database.list()[0].evaluation.algorithm_version, 'legacy_v1')
            backups = list(Path(directory).glob('*.bak'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(contents(backups[0]), before)
            self.assertEqual(version(backups[0]), '1')
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)

    def test_new_database_initializes_schema_two(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'new.sqlite3'
            self.assertEqual(ApplicationDatabase(path).list(), [])
            self.assertEqual(version(path), '2')
            self.assertEqual(list(Path(directory).glob('*.bak')), [])

    def test_future_schema_is_rejected_without_changing_data_or_journal_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'future.sqlite3'
            make_legacy(path)
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
                self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                ApplicationDatabase(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).glob('*.bak')), [])
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'delete')

    def test_historical_duplicate_identity_reuses_first_id_without_removing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            make_legacy(path)
            before = contents(path)
            database = ApplicationDatabase(path)
            job = JobPosting(title='Python Developer', company='Synthetic Co',
                             url='https://example.test/Jobs/ABC')
            self.assertEqual(database.find_duplicate(job), 3)
            self.assertEqual(database.add(ApplicationRecord(
                id=None, job=job, evaluation=EvaluationResult(score=99, recommendation='strong_fit'),
                notes='Do not replace the historical notes',
            )), 3)
            self.assertEqual(contents(path), before)
            different = database.add(ApplicationRecord(
                id=None, job=JobPosting(title='Different', company='Other Synthetic Co'),
                evaluation=EvaluationResult(score=50, recommendation='review'),
            ))
            self.assertGreater(different, 8)

    def test_exception_after_schema_changes_rolls_back_every_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            make_legacy(path)
            before = contents(path)
            migrate = migrations._migrate_v1_to_v2

            def interrupted(connection):
                migrate(connection)
                raise RuntimeError('Synthetic interruption')

            with patch.object(migrations, '_migrate_v1_to_v2', interrupted), self.assertRaises(RuntimeError):
                ApplicationDatabase(path)
            self.assertEqual(version(path), '1')
            self.assertEqual(contents(path), before)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='vacancies'"
                ).fetchall(), [])
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            self.assertEqual(contents(next(Path(directory).glob('*.bak'))), before)
            ApplicationDatabase(path)
            self.assertEqual(version(path), '2')

    def test_abrupt_process_exit_during_migration_recovers_schema_one(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            make_legacy(path)
            before = contents(path)
            script = '''
import os
import sys
from pathlib import Path
from jobsearch_assistant import migrations
from jobsearch_assistant.database import ApplicationDatabase
original = migrations._migrate_v1_to_v2
def interrupted(connection):
    connection.execute('PRAGMA cache_size=5')
    original(connection)
    os._exit(37)
migrations._migrate_v1_to_v2 = interrupted
ApplicationDatabase(Path(sys.argv[1]))
'''
            process = subprocess.run([sys.executable, '-c', script, str(path)],
                                     check=False, capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 37, process.stderr)
            self.assertEqual(version(path), '1')
            self.assertEqual(contents(path), before)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='vacancies'"
                ).fetchall(), [])
            self.assertEqual(contents(next(Path(directory).glob('*.bak'))), before)
            ApplicationDatabase(path)
            self.assertEqual(version(path), '2')
            self.assertEqual(contents(path), before)

    def test_concurrent_migrations_create_one_backup_and_preserve_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            make_legacy(path)
            before = contents(path)
            barrier = threading.Barrier(2)

            def initialize(_):
                barrier.wait(timeout=10)
                return len(ApplicationDatabase(path).list())

            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertEqual(list(executor.map(initialize, range(2))), [2, 2])
            self.assertEqual(contents(path), before)
            self.assertEqual(version(path), '2')
            self.assertEqual(len(list(Path(directory).glob('*.bak'))), 1)

    def test_backup_includes_committed_wal_and_restore_uses_fresh_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.sqlite3'
            make_legacy(source)
            backup = Path(directory) / 'snapshot.sqlite3'
            restored = Path(directory) / 'restored.sqlite3'
            connection = sqlite3.connect(source)
            try:
                self.assertEqual(connection.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
                connection.execute('PRAGMA wal_autocheckpoint=0')
                connection.execute("UPDATE applications SET notes='Committed in WAL' WHERE id=8")
                connection.commit()
                self.assertGreater(Path(str(source) + '-wal').stat().st_size, 0)
                expected = contents(source)
                self.assertEqual(migrations.backup_database(source, backup), backup)
                self.assertEqual(contents(backup), expected)
                self.assertEqual(migrations.restore_backup(backup, restored), restored)
                self.assertEqual(contents(restored), expected)
                self.assertEqual(version(restored), '1')
                before = contents(source)
                for operation in (migrations.backup_database, migrations.restore_backup):
                    with self.assertRaises(FileExistsError):
                        operation(backup, source)
                self.assertEqual(contents(source), before)
                self.assertEqual(contents(backup), expected)
            finally:
                connection.close()

    def test_migration_backup_includes_committed_wal_before_schema_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            make_legacy(path)
            connection = sqlite3.connect(path)
            try:
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('PRAGMA wal_autocheckpoint=0')
                connection.execute("UPDATE applications SET notes='Migration WAL data' WHERE id=8")
                connection.commit()
                expected = contents(path)
                ApplicationDatabase(path)
                backup = next(Path(directory).glob('*.bak'))
                self.assertEqual(contents(backup), expected)
                self.assertEqual(version(backup), '1')
                self.assertEqual(contents(path), expected)
                self.assertEqual(version(path), '2')
            finally:
                connection.close()

    def test_failed_backup_removes_only_its_own_new_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / 'not-sqlite'
            invalid.write_text('Synthetic corrupt input', encoding='utf-8')
            destination = Path(directory) / 'snapshot.sqlite3'
            with self.assertRaises(sqlite3.DatabaseError):
                migrations.backup_database(invalid, destination)
            self.assertFalse(destination.exists())
            self.assertEqual(invalid.read_text(encoding='utf-8'), 'Synthetic corrupt input')

    def test_restore_rejects_existing_empty_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.sqlite3'
            make_legacy(source)
            existing = Path(directory) / 'existing.sqlite3'
            existing.touch()
            with self.assertRaises(FileExistsError):
                migrations.restore_backup(source, existing)
            self.assertEqual(existing.read_bytes(), b'')
            if os.name != 'nt':
                symlink = Path(directory) / 'link.sqlite3'
                symlink.symlink_to(existing)
                with self.assertRaises(FileExistsError):
                    migrations.restore_backup(source, symlink)
                self.assertTrue(symlink.is_symlink())


if __name__ == '__main__':
    unittest.main()
