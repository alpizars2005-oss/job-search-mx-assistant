"""Synthetic release tests; never create accounts, modify /etc or activate systemd."""
import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'scripts' / 'production' / 'manage.py'
spec = importlib.util.spec_from_file_location('production_manage', MODULE)
manage = importlib.util.module_from_spec(spec)
if MODULE.exists():
    spec.loader.exec_module(manage)

SHA = 'a' * 40
OTHER = 'b' * 40


@unittest.skipUnless(os.name == "posix", "Production provisioning targets Debian Linux")
class ProductionInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wheel = self.root / 'job_search_assistant-1.0.0-py3-none-any.whl'
        self.wheel.write_bytes(b'synthetic-wheel')
        self.payload = {'format': 1, 'project': 'job-search-assistant', 'commit': SHA,
                        'wheel': self.wheel.name, 'sha256': hashlib.sha256(self.wheel.read_bytes()).hexdigest(),
                        'schema_version': 5, 'python': '3.11'}
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text(json.dumps(self.payload))
        self.layout = {key: self.root / key for key in ('code', 'state', 'config', 'logs', 'backups', 'units')}

    def test_manifest_binds_explicit_commit_and_bytes_without_network(self):
        result = manage.read_manifest(self.manifest, self.wheel, SHA)
        self.assertEqual(result['commit'], SHA)
        for key, value in [('commit', OTHER), ('wheel', '../bad.whl'), ('schema_version', True),
                           ('sha256', 'f' * 64), ('python', '3.12')]:
            payload = dict(self.payload, **{key: value})
            self.manifest.write_text(json.dumps(payload))
            with self.subTest(key=key), self.assertRaises(manage.DeploymentError):
                manage.read_manifest(self.manifest, self.wheel, SHA)

    def test_symlink_and_hardlink_artifacts_rejected_without_modification(self):
        alias = self.root / 'alias.whl'
        alias.symlink_to(self.wheel)
        with self.assertRaises(manage.DeploymentError):
            manage.read_manifest(self.manifest, alias, SHA)
        alias.unlink()
        os.link(self.wheel, alias)
        with self.assertRaises(manage.DeploymentError):
            manage.read_manifest(self.manifest, self.wheel, SHA)
        self.assertEqual(self.wheel.read_bytes(), b'synthetic-wheel')

    def test_preflight_rejects_wrong_os_python_arch_and_missing_systemd(self):
        valid = dict(os_release={'ID': 'debian', 'VERSION_ID': '12'}, python_version=(3, 11),
                     architecture='x86_64', effective_uid=0, systemd_version=252)
        self.assertEqual(manage.validate_platform(**valid)['python'], '3.11')
        for key, value in [('os_release', {'ID': 'debian', 'VERSION_ID': '13'}),
                           ('python_version', (3, 12)), ('architecture', 'unknown'),
                           ('effective_uid', 1000), ('systemd_version', 0)]:
            with self.subTest(key=key), self.assertRaises(manage.DeploymentError):
                manage.validate_platform(**dict(valid, **{key: value}))

    def test_managed_layout_private_data_and_code_separation(self):
        manage.validate_layout(self.layout)
        uid = os.getuid() if hasattr(os, 'getuid') else 0
        gid = os.getgid() if hasattr(os, 'getgid') else 0
        manage.prepare_directories(self.layout, uid, gid)
        if os.name == 'posix':
            for key in ('state', 'logs', 'backups'):
                self.assertEqual(self.layout[key].stat().st_mode & 0o777, 0o700)
        with self.assertRaises(manage.DeploymentError):
            manage.validate_layout(dict(self.layout, state=self.layout['code'] / 'private'))

    def test_release_install_is_idempotent_and_offline(self):
        calls = []
        def runner(argv, **options):
            calls.append(list(map(str, argv)))
            if argv[1:3] == ['-m', 'venv']:
                binary = Path(argv[-1]) / 'bin' / 'python'
                binary.parent.mkdir(parents=True)
                binary.write_text('synthetic')
            return ''
        release = manage.stage_release(self.layout['code'], self.manifest, self.wheel, SHA,
                                       python='/usr/bin/python3.11', runner=runner)
        self.assertEqual(release.name, SHA)
        self.assertFalse((self.layout['code'] / 'current').exists())
        before = len(calls)
        self.assertEqual(manage.stage_release(self.layout['code'], self.manifest, self.wheel, SHA,
                                             python='/usr/bin/python3.11', runner=runner), release)
        self.assertEqual(len(calls), before)
        pip_install = next(call for call in calls if 'install' in call)
        self.assertIn('--no-index', pip_install)
        self.assertIn('--no-deps', pip_install)
        self.assertNotIn('-e', pip_install)
        self.assertTrue((release / 'manifest.json').is_file())

    def test_release_permissions_do_not_depend_on_restrictive_umask(self):
        def runner(argv, **options):
            if argv[1:3] == ['-m', 'venv']:
                binary = Path(argv[-1]) / 'bin/python'
                binary.parent.mkdir(parents=True)
                binary.write_text('synthetic')
                binary.chmod(0o700)
            return ''
        previous = os.umask(0o077)
        try:
            release = manage.stage_release(self.layout['code'], self.manifest, self.wheel, SHA,
                                           python='/usr/bin/python3.11', runner=runner)
        finally:
            os.umask(previous)
        self.assertEqual((release / 'venv/bin').stat().st_mode & 0o777, 0o755)
        self.assertEqual((release / 'venv/bin/python').stat().st_mode & 0o777, 0o755)
        self.assertEqual((release / 'manifest.json').stat().st_mode & 0o777, 0o644)

    def test_failed_stage_never_activates_or_overwrites_data(self):
        self.layout['state'].mkdir()
        marker = self.layout['state'] / 'profile.json'
        marker.write_bytes(b'private synthetic')
        def fail(*args, **kwargs):
            raise RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError):
            manage.stage_release(self.layout['code'], self.manifest, self.wheel, SHA,
                                 python='/usr/bin/python3.11', runner=fail)
        self.assertFalse((self.layout['code'] / 'current').exists())
        self.assertEqual(marker.read_bytes(), b'private synthetic')

    def _release(self, sha, schema):
        release = self.layout['code'] / 'releases' / sha
        release.mkdir(parents=True)
        (release / 'manifest.json').write_text(json.dumps(dict(self.payload, commit=sha, schema_version=schema)))
        (release / self.wheel.name).write_bytes(self.wheel.read_bytes())
        executable = release / 'venv/bin/jobsearch'
        executable.parent.mkdir(parents=True)
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        return release

    def _database(self, schema=5):
        self.layout['state'].mkdir(exist_ok=True)
        database = self.layout['state'] / 'applications.sqlite3'
        with sqlite3.connect(database) as connection:
            connection.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            connection.execute("INSERT INTO meta VALUES('schema_version',?)", (str(schema),))
        return database

    def test_activation_and_rollback_preserve_database_and_require_safe_schema(self):
        first, second = self._release(SHA, 5), self._release(OTHER, 5)
        database = self._database()
        original = database.read_bytes()
        manage.activate_release(self.layout['code'], SHA, database)
        self.assertEqual((self.layout['code'] / 'current').resolve(), first)
        manage.activate_release(self.layout['code'], OTHER, database)
        self.assertEqual((self.layout['code'] / 'current').resolve(), second)
        manage.activate_release(self.layout['code'], SHA, database)
        self.assertEqual((self.layout['code'] / 'current').resolve(), first)
        self.assertEqual(database.read_bytes(), original)
        (first / 'manifest.json').write_text(json.dumps(dict(self.payload, schema_version=4)))
        with self.assertRaises(manage.DeploymentError):
            manage.activate_release(self.layout['code'], SHA, database)
        self.assertEqual(database.read_bytes(), original)

    def test_activation_rejects_running_service_lock_and_unmanaged_current(self):
        self._release(SHA, 5)
        database = self._database()
        current = self.layout['code'] / 'current'
        current.mkdir()
        with self.assertRaises(manage.DeploymentError):
            manage.activate_release(self.layout['code'], SHA, database)
        current.rmdir()
        current.symlink_to('/tmp')
        with self.assertRaises(manage.DeploymentError):
            manage.activate_release(self.layout['code'], SHA, database)

    def test_activation_never_steals_held_lock(self):
        import fcntl
        self._release(SHA, 5)
        database = self._database()
        lock = database.parent / 'automation.lock'
        with lock.open('wb') as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            original_inode = lock.stat().st_ino
            with self.assertRaises(manage.DeploymentError):
                manage.activate_release(self.layout['code'], SHA, database)
            self.assertEqual(lock.stat().st_ino, original_inode)
            self.assertFalse((self.layout['code'] / 'current').exists())

    def test_unit_directory_permissions_are_preserved(self):
        self.layout['units'].mkdir(mode=0o750)
        self.layout['units'].chmod(0o750)
        uid, gid = os.getuid(), os.getgid()
        manage.prepare_directories(self.layout, uid, gid)
        self.assertEqual(self.layout['units'].stat().st_mode & 0o777, 0o750)

    def test_existing_data_activation_requires_recent_verified_bundle(self):
        self._release(SHA, 5)
        database = self._database()
        uid = os.getuid() if hasattr(os, 'getuid') else 0
        with self.assertRaises(manage.DeploymentError):
            manage.verify_backup_for_activation(self.layout['code'], None, database,
                                                'jobsearch-assistant', service_uid=uid)
        backup = self.root / 'bundle'
        backup.mkdir(mode=0o700)
        manifest = backup / 'manifest.json'
        payload = {'format_version': 1, 'schema_version': 5,
                   'created_at': datetime.now(timezone.utc).isoformat(),
                   'files': {'applications.sqlite3': '0' * 64}}
        manifest.write_text(json.dumps(payload))
        manifest.chmod(0o600)
        (self.layout['code'] / 'current').symlink_to(self.layout['code'] / 'releases' / SHA)
        calls = []
        manage.verify_backup_for_activation(self.layout['code'], backup, database, 'jobsearch-assistant',
                                            service_uid=uid, runner=lambda argv, **kw: calls.append(argv))
        self.assertIn('verify-backup', calls[0])
        self.assertIn('runuser', calls[0])
        for created in (datetime.now(timezone.utc) + timedelta(days=1),
                        datetime.now(timezone.utc) - timedelta(days=2)):
            manifest.write_text(json.dumps(dict(payload, created_at=created.isoformat())))
            with self.assertRaises(manage.DeploymentError):
                manage.verify_backup_for_activation(self.layout['code'], backup, database,
                                                    'jobsearch-assistant', service_uid=uid)

    def test_privileged_schema_read_uses_service_identity(self):
        database = self._database()
        uid = database.stat().st_uid
        if uid == 0:
            self.skipTest('Synthetic delegation fixture expects an unprivileged test UID')
        calls = []
        with patch.object(manage.os, 'getuid', return_value=0), \
                patch.object(manage.sqlite3, 'connect', side_effect=AssertionError('root SQL forbidden')):
            schema = manage._schema(database, uid, 'jobsearch-assistant',
                                    runner=lambda argv, **kw: calls.append(argv) or '5')
        self.assertEqual(schema, 5)
        self.assertEqual(calls[0][:4], ['runuser', '-u', 'jobsearch-assistant', '--'])

    def test_units_keep_failed_exit_codes_and_daily_timezone(self):
        units = manage.render_units(self.layout, 'jobsearch-assistant')
        self.assertEqual(set(units), {'jobsearch-search.service', 'jobsearch-search.timer',
                                     'jobsearch-report.service', 'jobsearch-report.timer'})
        search = units['jobsearch-search.service']
        for required in ('Type=oneshot', 'UMask=0077', 'StateDirectoryMode=0700',
                         'DRY_RUN=true', 'AUTO_SUBMIT=false', 'TimeoutStartSec=660',
                         'TimeoutStopSec=30', 'KillMode=control-group', 'NoNewPrivileges=true',
                         'CapabilityBoundingSet=', 'Restart=no', 'automation run'):
            self.assertIn(required, search)
        self.assertNotIn('SuccessExitStatus', search)
        self.assertNotIn('RemainAfterExit', search)
        self.assertIn('14:00:00 America/Mexico_City', units['jobsearch-report.timer'])
        self.assertIn('Persistent=true', units['jobsearch-search.timer'])
        self.assertIn('RandomizedDelaySec=120', units['jobsearch-search.timer'])
        self.assertNotIn('api.telegram', ''.join(units.values()))
        self.assertIn('reports generate', units['jobsearch-report.service'])

    def test_environment_existing_values_never_overwritten(self):
        uid = os.getuid() if hasattr(os, 'getuid') else 0
        gid = os.getgid() if hasattr(os, 'getgid') else 0
        manage.prepare_directories(self.layout, uid, gid)
        manage.write_environment(self.layout, gid)
        path = self.layout['config'] / 'runtime.env'
        self.assertIn('DRY_RUN=true', path.read_text())
        path.write_text('DRY_RUN=false\nAUTO_SUBMIT=false\n')
        with self.assertRaises(manage.DeploymentError):
            manage.write_environment(self.layout, gid)
        self.assertIn('DRY_RUN=false', path.read_text())


if __name__ == '__main__':
    unittest.main()
