"""Synthetic whole-store snapshots, recoverability and non-destructive retention."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
from datetime import datetime, timedelta, timezone

from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.private_storage import private_directory, write_private
from jobsearch_assistant.runtime_control import RunLock
from jobsearch_assistant.workflow_contracts import WorkflowError
from jobsearch_assistant.storage import backup_bundle, verify_bundle, restore_bundle, inventory


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = private_directory(self.root / 'home')
        self.database = ApplicationDatabase(self.home / 'applications.sqlite3')
        write_private(self.home / 'profile.json', b'{"skills":["python"]}')
        write_private(self.home / 'settings.json', b'{"language":"es"}')
        write_private(self.home / 'resumes' / 'evidence' / 'proof', b'synthetic-evidence')
        self.destination = self.root / 'backup'
        self.policy = patch.dict(os.environ, {'DRY_RUN': 'true', 'AUTO_SUBMIT': 'false'})
        self.policy.start()
        self.addCleanup(self.policy.stop)

    def test_backup_restore_hashes_and_original_bytes_preserved(self):
        original = (self.home / 'profile.json').read_bytes()
        manifest = backup_bundle(self.home, self.destination)
        self.assertEqual(manifest, verify_bundle(self.destination))
        self.assertEqual(manifest['files']['profile.json'], hashlib.sha256(original).hexdigest())
        restored = self.root / 'restored'
        restore_bundle(self.destination, restored)
        self.assertEqual((restored / 'profile.json').read_bytes(), original)
        self.assertEqual((self.home / 'profile.json').read_bytes(), original)
        connection = sqlite3.connect(restored / 'applications.sqlite3')
        try:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(connection.execute("SELECT value FROM meta WHERE key='source_review_required'").fetchone()[0], '1')
        finally:
            connection.close()
        self.assertEqual((restored / 'resumes' / 'evidence' / 'proof').read_bytes(), b'synthetic-evidence')

    def test_wal_snapshot_is_self_contained_and_preserves_committed_data(self):
        connection = sqlite3.connect(self.database.path)
        try:
            self.assertEqual(connection.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            connection.execute("INSERT INTO meta VALUES('wal_test','committed')")
            connection.commit()
            self.assertTrue(Path(str(self.database.path) + '-wal').exists())
            manifest = backup_bundle(self.home, self.destination)
            self.assertEqual(verify_bundle(self.destination), manifest)
            self.assertFalse(any(name.endswith(('-wal', '-shm', '-journal')) for name in manifest['files']))
            self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            restored = self.root / 'wal-restored'
            restore_bundle(self.destination, restored)
            with closing(sqlite3.connect(restored / 'applications.sqlite3')) as recovered:
                self.assertEqual(recovered.execute("SELECT value FROM meta WHERE key='wal_test'").fetchone()[0], 'committed')
        finally:
            connection.close()

    def test_tampering_extra_files_and_unsafe_manifest_paths_fail(self):
        backup_bundle(self.home, self.destination)
        original = (self.destination / 'profile.json').read_bytes()
        write_private(self.destination / 'profile.json', b'changed')
        with self.assertRaises(WorkflowError):
            verify_bundle(self.destination)
        write_private(self.destination / 'profile.json', original)
        write_private(self.destination / 'unexpected', b'extra')
        with self.assertRaises(WorkflowError):
            verify_bundle(self.destination)
        (self.destination / 'unexpected').unlink()
        manifest = json.loads((self.destination / 'manifest.json').read_text())
        manifest['files']['../escape'] = '0' * 64
        write_private(self.destination / 'manifest.json', json.dumps(manifest).encode())
        with self.assertRaises(WorkflowError):
            verify_bundle(self.destination)
        with self.assertRaises(WorkflowError):
            restore_bundle(self.destination, self.root / 'unsafe-restore')
        self.assertFalse((self.root / 'unsafe-restore').exists())

    def test_existing_destination_and_nested_payload_destination_not_overwritten(self):
        self.destination.mkdir()
        with self.assertRaises(FileExistsError):
            backup_bundle(self.home, self.destination)
        self.assertEqual(list(self.destination.iterdir()), [])
        with self.assertRaises(WorkflowError):
            backup_bundle(self.home, self.home / 'resumes' / 'bad')
        backup_bundle(self.home, self.home / 'backups' / 'first')
        second = backup_bundle(self.home, self.home / 'backups' / 'second')
        self.assertFalse(any(name.startswith('backups/') for name in second['files']))
        with self.assertRaises(FileExistsError):
            restore_bundle(self.home / 'backups' / 'first', self.home)

    def test_competing_lock_and_unsafe_policy_fail_before_snapshot(self):
        with RunLock(self.home / 'automation.lock'), self.assertRaises(WorkflowError):
            backup_bundle(self.home, self.destination)
        self.assertFalse(self.destination.exists())
        with patch.dict(os.environ, {'AUTO_SUBMIT': 'true'}), self.assertRaises(WorkflowError):
            backup_bundle(self.home, self.destination)
        self.assertFalse(self.destination.exists())

    def test_cli_writers_share_backup_mutex_and_diagnostics_are_redacted(self):
        environment = {**os.environ, 'JOB_SEARCH_ASSISTANT_HOME': str(self.home)}
        with RunLock(self.home / 'automation.lock'):
            completed = subprocess.run([sys.executable, '-m', 'jobsearch_assistant', 'settings',
                                        '--language', 'en'], capture_output=True, text=True,
                                       env=environment, timeout=10)
        self.assertEqual(completed.returncode, 2)  # Historical manual CLI errors stay2.
        self.assertIn('run_locked', completed.stderr)
        self.assertNotIn(str(self.home), completed.stdout + completed.stderr)

        self.assertEqual((self.home / 'settings.json').read_bytes(), b'{"language":"es"}')
        completed = subprocess.run([sys.executable, '-m', 'jobsearch_assistant', 'storage',
                                    'backup', '--output', str(self.destination)],
                                   capture_output=True, text=True, env=environment, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIs(json.loads(completed.stdout)['verified'], True)
        self.assertNotIn(str(self.home), completed.stdout + completed.stderr)

    def test_nominal_readers_cannot_migrate_or_initialize_while_snapshot_locked(self):
        from test_telegram_retirement import make_four
        path = self.home / 'applications.sqlite3'
        path.unlink()
        make_four(path)
        before = path.read_bytes()
        environment = {**os.environ, 'JOB_SEARCH_ASSISTANT_HOME': str(self.home)}
        for command in (['applications', 'list'], ['vacancies', 'list'], ['doctor'],
                        ['export', '--format', 'json', '--output', str(self.root / 'export.json')]):
            with self.subTest(command=command), RunLock(self.home / 'automation.lock'):
                completed = subprocess.run([sys.executable, '-m', 'jobsearch_assistant', *command],
                    capture_output=True, text=True, env=environment, timeout=10)
                self.assertEqual(completed.returncode, 2)
                self.assertIn('run_locked', completed.stderr)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(self.home.glob('*.schema4-*.bak')), [])

    def test_gui_lifecycle_uses_same_mutex_before_constructing_window(self):
        from jobsearch_assistant.gui import main
        with patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': str(self.home)}), \
                patch('jobsearch_assistant.gui.JobSearchApp') as app, \
                RunLock(self.home / 'automation.lock'), self.assertRaises(SystemExit) as caught:
            main()
        self.assertEqual(caught.exception.code, 2)
        app.assert_not_called()
    def test_disk_full_and_file_change_fail_without_published_snapshot(self):
        with patch('jobsearch_assistant.storage.shutil.disk_usage', return_value=(10, 10, 0)), self.assertRaises(OSError):
            backup_bundle(self.home, self.destination)
        self.assertFalse(self.destination.exists())
        from jobsearch_assistant import storage
        original = storage._copy_file
        def mutate(source, destination):
            original(source, destination)
            if source.name == 'profile.json':
                write_private(source, b'{"skills":[]}')
        with patch.object(storage, '_copy_file', side_effect=mutate), self.assertRaises(WorkflowError):
            backup_bundle(self.home, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertFalse(any(p.name.startswith('.bundle-') for p in self.root.iterdir()))

    @unittest.skipUnless(os.name == 'posix', 'POSIX link and mode contracts')
    def test_private_modes_umask_zero_and_symlink_inputs_rejected(self):
        old = os.umask(0)
        try:
            backup_bundle(self.home, self.destination)
        finally:
            os.umask(old)
        for path in (self.destination, *self.destination.rglob('*')):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
        target = self.root / 'external'
        target.write_bytes(b'private')
        (self.home / 'resumes' / 'link').symlink_to(target)
        with self.assertRaises(OSError):
            backup_bundle(self.home, self.root / 'unsafe')
        self.assertEqual(target.read_bytes(), b'private')

    def test_retention_only_simulates_and_validates_configuration(self):
        backup_bundle(self.home, self.home / 'backups' / 'one')
        before = {p.relative_to(self.home).as_posix(): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        result = inventory(self.home, retention_days=1, keep_backups=1)
        self.assertIs(result['dry_run'], True)
        self.assertEqual(result['deleted'], 0)
        self.assertGreater(result['total_bytes'], 0)
        self.assertEqual(result['counts']['backups'], 1)
        after = {p.relative_to(self.home).as_posix(): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        for days in (0, True, -1):
            with self.assertRaises(WorkflowError):
                inventory(self.home, retention_days=days)

    def test_expired_backups_are_only_candidates_and_latest_is_protected(self):
        for index in (1, 2):
            path = self.home / 'backups' / str(index)
            manifest = backup_bundle(self.home, path)
            manifest['created_at'] = (datetime.now(timezone.utc) - timedelta(days=100 + index)).isoformat()
            write_private(path / 'manifest.json', json.dumps(manifest).encode())
        result = inventory(self.home, retention_days=90, keep_backups=1)
        self.assertEqual(len(result['backup_candidates']), 1)
        self.assertEqual(len(result['retained_backups']), 1)
        self.assertTrue((self.home / 'backups' / '2').exists())

    def test_restore_revokes_approval_preserves_real_cv_and_http_deadline(self):
        from jobsearch_assistant.resumes import ResumeStore
        from jobsearch_assistant.candidacies import CandidacyWorkflow
        from jobsearch_assistant.automation_store import AutomationStore
        from test_resumes import synthetic_master, synthetic_job
        store = ResumeStore(self.home / 'resumes')
        master = store.import_master(synthetic_master(self.home), base_dir=self.home)
        job = synthetic_job()
        version = store.create_version(master, job, 'en', format='txt')
        vacancy = self.database.upsert_vacancy(job)
        workflow = CandidacyWorkflow(self.database, store)
        candidate = workflow.create(vacancy, version['version_id'], 'Synthetic content')
        authorization = workflow.approve(candidate, workflow.review(candidate)['review_digest'])
        state = {'version': 1, 'providers': {'greenhouse': {'failures': 1,
            'paused_until': None, 'not_before': '2099-11-04T00:00:00+00:00'}}}
        AutomationStore(self.database).save_http_state(state)
        backup_bundle(self.home, self.destination)
        restored = self.root / 'recovered'
        restore_bundle(self.destination, restored)
        restored_db = ApplicationDatabase(restored / 'applications.sqlite3')
        recovered_store = ResumeStore(restored / 'resumes')
        self.assertEqual(recovered_store.verify_version(version['version_id'])['sha256'], version['sha256'])
        self.assertEqual(AutomationStore(restored_db).load_http_state(), state)
        with restored_db._connection() as connection:
            self.assertEqual(connection.execute('SELECT status FROM candidacy_authorizations WHERE authorization_id=?', (authorization,)).fetchone()[0], 'invalidated')
        self.assertEqual(CandidacyWorkflow(restored_db, recovered_store).get(candidate)['workflow_state'], 'draft')


if __name__ == '__main__':
    unittest.main()
