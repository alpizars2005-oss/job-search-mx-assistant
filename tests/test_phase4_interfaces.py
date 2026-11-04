"""Synthetic, offline public-interface checks for documents and authorization."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.cli import main
from jobsearch_assistant.config import data_home, database_path


class Phase4InterfaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = patch.dict(os.environ, {
            'JOB_SEARCH_ASSISTANT_HOME': str(self.root / 'private'),
            'DRY_RUN': 'true', 'AUTO_SUBMIT': 'false'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.proof = self.root / 'synthetic-evidence.txt'
        self.proof.write_text('Synthetic evidence of a personal Python project.', encoding='utf-8')
        self.master = self.root / 'master.json'
        self.master.write_text(json.dumps({
            'schema_version': 1,
            'candidate': {'name': 'Synthetic Candidate', 'contact': ['synthetic@example.test']},
            'evidence': [{'id': 'proof', 'path': self.proof.name,
                          'sha256': hashlib.sha256(self.proof.read_bytes()).hexdigest()}],
            'claims': [{'id': 'python-project', 'kind': 'project',
                'text': {'es': 'Proyecto personal: automatización con Python.',
                         'en': 'Personal project: Python automation.'},
                'evidence_ids': ['proof'], 'attested': True},
                {'id': 'unverified', 'kind': 'certification',
                 'text': {'es': 'Certificación desconocida.', 'en': 'Unverified certification.'},
                 'evidence_ids': [], 'attested': False}]}), encoding='utf-8')
        self.posting = self.root / 'posting.json'
        self.posting.write_text(json.dumps({
            'company': 'Synthetic Company', 'title': 'Junior Python Developer',
            'location': 'Remote - Mexico', 'url': 'https://example.test/Jobs/Case-ID',
            'description': 'Fully remote. We can hire candidates residing in Mexico. Python.'}), encoding='utf-8')

    def invoke(self, *arguments):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), \
                self.assertRaises(SystemExit) as result:
            main(list(arguments))
        return result.exception.code, output.getvalue(), error.getvalue()

    def json_command(self, *arguments):
        code, output, error = self.invoke(*arguments)
        self.assertEqual(code, 0, error)
        return json.loads(output)

    def prepare_draft(self, language='en', format='txt'):
        master = self.json_command('resumes', 'import', str(self.master))['master_id']
        vacancy = self.json_command('vacancies', 'import', str(self.posting))['vacancy_id']
        version = self.json_command('resumes', 'tailor', master, '--vacancy', str(vacancy),
                                    '--language', language, '--format', format)
        candidacy = self.json_command('candidacies', 'create', '--vacancy', str(vacancy),
                                      '--resume', version['version_id'])['candidacy_id']
        if self.json_command('candidacies', 'show', str(candidacy))['resume_version_id'] != version['version_id']:
            self.json_command('candidacies', 'edit', str(candidacy), '--resume', version['version_id'])
        return candidacy, version

    def approve(self, candidacy):
        review = self.json_command('candidacies', 'review', str(candidacy))
        return self.json_command('candidacies', 'approve', str(candidacy),
                                 '--digest', review['review_digest'])['authorization_id']

    def test_full_bilingual_document_draft_and_one_use_simulation_work_offline(self):
        for language, expected in (('es', 'Proyecto personal'), ('en', 'Personal project')):
            with self.subTest(language=language):
                candidacy, version = self.prepare_draft(language, 'docx')
                shown = self.json_command('candidacies', 'show', str(candidacy))
                self.assertIn(expected, shown['content'])
                self.assertNotIn('Unverified certification', shown['content'])
                self.assertNotIn('Certificación desconocida', shown['content'])
                self.assertEqual(shown['resume_version_id'], version['version_id'])
                verified = self.json_command('resumes', 'verify', version['version_id'])
                self.assertTrue(verified['integrity_ok'])
                destination = self.root / (language + '.docx')
                self.json_command('resumes', 'export', version['version_id'], str(destination))
                self.assertTrue(destination.read_bytes().startswith(b'PK'))
                authorization = self.approve(candidacy)
                with patch('urllib.request.urlopen', side_effect=AssertionError('network')):
                    receipt = self.json_command('candidacies', 'simulate', authorization)
                self.assertEqual(receipt['authorization_id'], authorization)
                self.assertIs(receipt['submitted'], False)
                self.assertIs(receipt['dry_run'], True)
                code, _, _ = self.invoke('candidacies', 'simulate', authorization)
                self.assertEqual(code, 2)
                # A second language is an explicit new revision of the same candidacy.

    def test_manual_import_is_idempotent_and_keeps_provenance_without_network(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            first = self.json_command('vacancies', 'import', str(self.posting))
            second = self.json_command('vacancies', 'import', str(self.posting))
        self.assertEqual(first['vacancy_id'], second['vacancy_id'])
        jobs = self.json_command('vacancies', 'list')
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['job']['source'], 'manual')
        self.assertIn('manual', ' '.join(jobs[0]['job']['provenance']['description']))

    def test_default_listings_and_errors_do_not_disclose_document_contents(self):
        self.prepare_draft()
        for arguments in (('resumes', 'list'), ('candidacies', 'list')):
            code, output, error = self.invoke(*arguments)
            self.assertEqual((code, error), (0, ''))
            self.assertNotIn('synthetic@example.test', output)
            self.assertNotIn('Python automation.', output)
        for language in ('es', 'en'):
            code, output, error = self.invoke('resumes', 'import', str(self.root / 'private-value.json'),
                                               '--language', language)
            self.assertEqual((code, output), (2, ''))
            self.assertNotIn('private-value', error)
            self.assertNotIn(str(self.root), error)

    def test_changing_the_draft_invalidates_approval_across_restart(self):
        candidacy, _ = self.prepare_draft()
        authorization = self.approve(candidacy)
        changed = self.root / 'revised.txt'
        changed.write_text('A revised manual draft, supplied explicitly by the user.', encoding='utf-8')
        self.json_command('candidacies', 'edit', str(candidacy), '--content-file', str(changed))
        code, _, _ = self.invoke('candidacies', 'simulate', authorization)
        self.assertEqual(code, 2)
        history = self.json_command('candidacies', 'history', str(candidacy))
        self.assertTrue(history)
        self.assertEqual(self.json_command('candidacies', 'show', str(candidacy))['content'], changed.read_text())

    def test_tampered_document_revokes_authorization_even_after_bytes_are_restored(self):
        candidacy, version = self.prepare_draft()
        authorization = self.approve(candidacy)
        artifact = next(path for path in (data_home() / 'resumes').rglob('*')
                        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == version['sha256'])
        original = artifact.read_bytes()
        artifact.write_bytes(b'Tampered synthetic document')
        self.assertEqual(self.invoke('candidacies', 'simulate', authorization)[0], 2)
        artifact.write_bytes(original)
        self.assertEqual(self.invoke('candidacies', 'simulate', authorization)[0], 2)

    def test_tracker_transitions_and_recording_applied_never_send(self):
        candidacy, _ = self.prepare_draft()
        authorization = self.approve(candidacy)
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            self.json_command('candidacies', 'update', str(candidacy), '--status', 'applied',
                              '--next-step', 'Manual follow-up', '--follow-up', '2026-12-01')
        shown = self.json_command('candidacies', 'show', str(candidacy))
        self.assertEqual(shown['status'], 'applied')
        self.assertEqual(self.invoke('candidacies', 'simulate', authorization)[0], 2)
        self.assertEqual(self.invoke('candidacies', 'update', str(candidacy), '--status', 'saved')[0], 2)

    def test_legacy_cli_tracker_obeys_managed_transitions_and_revokes_approval(self):
        candidacy, _ = self.prepare_draft()
        authorization = self.approve(candidacy)
        application_id = self.json_command('candidacies', 'show', str(candidacy))['application_id']
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            self.assertEqual(self.invoke('applications', 'update', str(application_id), '--status', 'applied')[0], 0)
        self.assertEqual(self.invoke('candidacies', 'simulate', authorization)[0], 2)
        code, output, error = self.invoke('applications', 'update', str(application_id), '--status', 'saved')
        self.assertEqual((code, output), (2, ''))
        self.assertNotIn('Traceback', error)
        self.assertEqual(self.json_command('candidacies', 'show', str(candidacy))['status'], 'applied')

    def test_unsafe_runtime_policy_cannot_consume_an_approval(self):
        candidacy, _ = self.prepare_draft()
        authorization = self.approve(candidacy)
        with patch.dict(os.environ, {'AUTO_SUBMIT': 'true'}):
            self.assertEqual(self.invoke('candidacies', 'simulate', authorization)[0], 2)
        receipt = self.json_command('candidacies', 'simulate', authorization)
        self.assertIs(receipt['submitted'], False)

    def test_backup_restore_revokes_old_permissions_and_allows_fresh_review(self):
        candidacy, version = self.prepare_draft()
        authorization = self.approve(candidacy)
        backup = self.root / 'active-backup.sqlite3'
        self.assertEqual(self.invoke('database', 'backup', '--source', str(database_path()),
                                     '--output', str(backup))[0], 0)
        self.json_command('candidacies', 'simulate', authorization)
        recovered = self.root / 'recovered'
        self.assertEqual(self.invoke('database', 'restore', '--source', str(backup),
                                     '--output', str(recovered / 'applications.sqlite3'))[0], 0)
        shutil.copytree(data_home() / 'resumes', recovered / 'resumes')
        with patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': str(recovered)}):
            checked = self.json_command('resumes', 'verify', version['version_id'])
            self.assertEqual(checked['sha256'], version['sha256'])
            self.assertEqual(self.invoke('candidacies', 'simulate', authorization)[0], 2)
            renewed = self.approve(candidacy)
            self.assertNotEqual(renewed, authorization)
            self.assertIs(self.json_command('candidacies', 'simulate', renewed)['submitted'], False)
        self.assertEqual(self.invoke('candidacies', 'simulate', authorization)[0], 2)

    def test_two_cli_processes_cannot_consume_the_same_authorization(self):
        candidacy, _ = self.prepare_draft()
        authorization = self.approve(candidacy)
        command = [sys.executable, '-m', 'jobsearch_assistant', 'candidacies', 'simulate', authorization]
        with ThreadPoolExecutor(max_workers=2) as executor:
            outputs = list(executor.map(lambda _: subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=False), range(2)))
        self.assertEqual(sorted(result.returncode for result in outputs), [0, 2])
        successful = next(result for result in outputs if result.returncode == 0)
        self.assertIs(json.loads(successful.stdout)['submitted'], False)
        self.assertNotIn('synthetic@example.test', successful.stdout)


class Phase4GuiTests(unittest.TestCase):
    def test_managed_transition_failure_is_redacted_without_callback_traceback(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from jobsearch_assistant.gui import JobSearchApp

        app = SimpleNamespace(
            _selected_application_id=Mock(return_value=1),
            database=Mock(update=Mock(side_effect=ValueError('private-value'))),
            application_notes=Mock(get=Mock(return_value='private notes')),
            selected_status=Mock(get=Mock(return_value='saved')),
            refresh_dashboard=Mock(), refresh_applications=Mock(), t=lambda key: key)
        with patch('jobsearch_assistant.gui.messagebox.showerror') as error:
            JobSearchApp.update_selected_application(app)
        self.assertTrue(error.called)
        self.assertNotIn('private-value', str(error.call_args))
