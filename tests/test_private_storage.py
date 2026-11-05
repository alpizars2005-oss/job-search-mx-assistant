import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.config import ensure_workspace, load_profile, save_profile, default_profile
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.exporters import export_csv, export_json
from jobsearch_assistant.migrations import backup_database, restore_backup


class SQLiteSidecarRaceTests(unittest.TestCase):
    def test_finished_writer_may_remove_its_journal_during_validation(self):
        from jobsearch_assistant import private_storage
        with tempfile.TemporaryDirectory() as directory:
            home = private_storage.private_directory(Path(directory))
            path = home / 'database.sqlite3'
            connection = private_storage.sqlite_private(path)
            connection.execute('CREATE TABLE preserved(value)')
            connection.commit()
            connection.close()
            journal = Path(str(path) + '-journal')
            private_storage.write_private(journal, b'')
            original = private_storage.protect_private_file
            seen = []
            def completed_writer(value, **options):
                if Path(value) == journal and not seen:
                    seen.append(True)
                    journal.unlink()
                return original(value, **options)
            with patch.object(private_storage, 'protect_private_file', side_effect=completed_writer):
                connection = private_storage.sqlite_private(path)
            try:
                self.assertEqual(connection.execute('SELECT * FROM preserved').fetchall(), [])
            finally:
                connection.close()
            self.assertEqual(seen, [True])


@unittest.skipIf(os.name == 'nt', 'POSIX permission bits; Windows ACL reviewed separately')
class PrivateStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def mode(self, path):
        return stat.S_IMODE(path.stat().st_mode)

    def test_initial_creation_updates_restart_and_exports_do_not_depend_on_umask(self):
        for mask in (0o000, 0o022):
            with self.subTest(mask=oct(mask)), patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': str(self.root / str(mask) / 'private')}):
                previous = os.umask(mask)
                try:
                    home = ensure_workspace()
                    db = ApplicationDatabase(home / 'applications.sqlite3')
                    save_profile(default_profile())
                    ensure_workspace()
                    export_csv([], home / 'exports' / 'tracker.csv')
                    export_json([], home / 'exports' / 'tracker.json')
                finally:
                    os.umask(previous)
                for directory in (home, home.parent, home / 'exports'):
                    self.assertEqual(self.mode(directory), 0o700)
                for name in ('profile.json', 'settings.json', 'applications.sqlite3', 'exports/tracker.csv', 'exports/tracker.json'):
                    self.assertEqual(self.mode(home / name), 0o600)
                self.assertEqual(db.list(), [])

    def test_existing_owned_home_and_files_are_hardened_without_changing_bytes(self):
        home = self.root / 'private'
        home.mkdir(mode=0o755)
        path = home / 'profile.json'
        path.write_bytes(b'not valid JSON')
        path.chmod(0o644)
        with patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': str(home)}):
            ensure_workspace()
            self.assertTrue(load_profile().skills)
        self.assertEqual(path.read_bytes(), b'not valid JSON')
        self.assertEqual(self.mode(home), 0o700)
        self.assertEqual(self.mode(path), 0o600)

    def test_home_symlink_is_rejected_and_its_target_unchanged(self):
        target = self.root / 'target'
        target.mkdir(mode=0o755)
        target.chmod(0o755)
        linked = self.root / 'home'
        linked.symlink_to(target, target_is_directory=True)
        with patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': str(linked)}), self.assertRaises(OSError):
            ensure_workspace()
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(self.mode(target), 0o755)

    def test_profile_symlink_is_not_read_or_overwritten(self):
        home = self.root / 'private'
        home.mkdir()
        target = self.root / 'unrelated.json'
        target.write_bytes(b'{"headline":"UNRELATED"}')
        (home / 'profile.json').symlink_to(target)
        with patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': str(home)}):
            for action in (load_profile, lambda: save_profile(default_profile())):
                with self.subTest(action=action), self.assertRaises(OSError):
                    action()
        self.assertEqual(target.read_bytes(), b'{"headline":"UNRELATED"}')

    def test_export_rejects_symlink_and_hardlink_without_chmod_or_truncate(self):
        target = self.root / 'unrelated'
        target.write_bytes(b'UNRELATED')
        target.chmod(0o644)
        for link in (self.root / 'symlink.json', self.root / 'hardlink.json'):
            if link.name.startswith('sym'):
                link.symlink_to(target)
            else:
                os.link(target, link)
            with self.subTest(kind=link.name), self.assertRaises(OSError):
                export_json([], link)
            self.assertEqual(target.read_bytes(), b'UNRELATED')
            self.assertEqual(self.mode(target), 0o644)

    def test_existing_wal_shm_and_main_are_hardened(self):
        path = self.root / 'old.sqlite3'
        previous = os.umask(0o022)
        connection = sqlite3.connect(path)
        try:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA wal_autocheckpoint=0')
            connection.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            connection.execute("INSERT INTO meta VALUES('schema_version','999')")
            connection.commit()
            for file in (path, Path(str(path)+'-wal'), Path(str(path)+'-shm')):
                file.chmod(0o644)
            with self.assertRaises(ValueError):
                ApplicationDatabase(path)
            for file in (path, Path(str(path)+'-wal'), Path(str(path)+'-shm')):
                self.assertEqual(self.mode(file), 0o600)
        finally:
            connection.close()
            os.umask(previous)

    def test_backup_restore_private_and_fully_readable_under_restrictive_umask(self):
        db = ApplicationDatabase(self.root / 'source.sqlite3')
        for mask in (0o000, 0o022, 0o777):
            with self.subTest(mask=oct(mask)):
                backup, restored = self.root / f'backup-{mask}.sqlite3', self.root / f'restored-{mask}.sqlite3'
                previous = os.umask(mask)
                try:
                    backup_database(db.path, backup)
                    restore_backup(backup, restored)
                finally:
                    os.umask(previous)
                for file in (backup, restored):
                    self.assertEqual(self.mode(file), 0o600)
                    with closing(sqlite3.connect(file)) as connection:
                        self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone(), ('ok',))

    def test_private_file_owner_rejection_precedes_permissions_or_content_changes(self):
        from jobsearch_assistant.private_storage import protect_private_file
        path = self.root / 'foreign'
        path.write_bytes(b'UNRELATED')
        path.chmod(0o644)
        with patch('jobsearch_assistant.private_storage._owned', return_value=False), self.assertRaises(OSError):
            protect_private_file(path)
        self.assertEqual(path.read_bytes(), b'UNRELATED')
        self.assertEqual(self.mode(path), 0o644)

    def test_shared_parent_is_not_accepted_for_sqlite_or_chmodded(self):
        shared = self.root / 'shared'
        shared.mkdir()
        shared.chmod(0o1777)
        with self.assertRaises(OSError):
            ApplicationDatabase(shared / 'private.sqlite3')
        self.assertFalse((shared / 'private.sqlite3').exists())
        self.assertEqual(self.mode(shared), 0o1777)

    def test_external_evidence_permissions_unchanged_and_private_store_hardened(self):
        from test_resumes import synthetic_master
        from jobsearch_assistant.resumes import ResumeStore
        # The external evidence read must not adopt chmod rules for private copies.
        external = self.root / 'evidence'
        external.mkdir()
        external.chmod(0o755)
        payload = synthetic_master(external)
        for path in external.iterdir():
            if path.is_file():
                path.chmod(0o644)
        before = {p: self.mode(p) for p in external.iterdir() if p.is_file()}
        store = ResumeStore(self.root / 'private-resumes')
        store.import_master(payload, base_dir=external)
        for path, mode in before.items():
            self.assertEqual(self.mode(path), mode)
        self.assertEqual(self.mode(external), 0o755)
        for path in store.root.rglob('*'):
            self.assertEqual(self.mode(path), 0o700 if path.is_dir() else 0o600)

    def test_restore_never_chmods_valid_or_invalid_external_source(self):
        for valid in (True, False):
            with self.subTest(valid=valid):
                source = self.root / f'external-{valid}.sqlite3'
                if valid:
                    ApplicationDatabase(source)
                else:
                    source.write_bytes(b'NOT SQLITE')
                source.chmod(0o644)
                before = source.read_bytes()
                target = self.root / f'imported-{valid}.sqlite3'
                if valid:
                    restore_backup(source, target)
                    self.assertEqual(self.mode(target), 0o600)
                else:
                    with self.assertRaises(sqlite3.DatabaseError):
                        restore_backup(source, target)
                    self.assertFalse(target.exists())
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(self.mode(source), 0o644)

    def test_valid_large_profile_round_trip_does_not_silently_change_candidate(self):
        with patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': str(self.root / 'private')}):
            profile = default_profile()
            profile.headline = 'A' * (512 * 1024)
            save_profile(profile)
            self.assertEqual(load_profile().to_dict(), profile.to_dict())
