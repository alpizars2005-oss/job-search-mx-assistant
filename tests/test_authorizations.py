import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.candidacies import CandidacyWorkflow
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.workflow_contracts import WorkflowError
from test_candidacies import WorkflowCase


class AuthorizationTests(WorkflowCase):
    def test_exact_review_required_idempotent_authorization_and_single_use(self):
        candidacy_id = self.create()
        with self.assertRaises(WorkflowError):
            self.workflow.approve(candidacy_id, '0' * 64)
        reviewed = self.workflow.review(candidacy_id)
        self.assertEqual(reviewed['snapshot']['company'], self.job.company)
        self.assertEqual(reviewed['snapshot']['resume']['sha256'], self.version['sha256'])
        with self.assertRaises(WorkflowError):
            self.workflow.approve(candidacy_id, '0' * 64)
        auth = self.workflow.approve(candidacy_id, reviewed['review_digest'])
        self.assertEqual(self.workflow.approve(candidacy_id, reviewed['review_digest']), auth)
        receipt = self.workflow.simulate(auth)
        self.assertIs(receipt['submitted'], False)
        self.assertIs(receipt['dry_run'], True)
        self.assertIs(receipt['auto_submit'], False)
        self.assertEqual(self.workflow.get(candidacy_id)['status'], 'saved')
        with self.assertRaises(WorkflowError):
            self.workflow.simulate(auth)
        self.workflow.review(candidacy_id)
        with self.assertRaises(WorkflowError):
            self.workflow.approve(candidacy_id, reviewed['review_digest'])

    def test_edit_then_revert_invalidates_old_capability(self):
        candidacy_id = self.create()
        old_review = self.workflow.review(candidacy_id)
        auth = self.workflow.approve(candidacy_id, old_review['review_digest'])
        self.workflow.edit(candidacy_id, content='Changed')
        self.workflow.edit(candidacy_id, content='Synthetic cover text')
        with self.assertRaises(WorkflowError):
            self.workflow.approve(candidacy_id, old_review['review_digest'])
        with self.assertRaises(WorkflowError):
            self.workflow.simulate(auth)
        self.assertNotEqual(self.authorize(candidacy_id), auth)

    def test_corrupt_bytes_revocation_is_committed_before_error(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        document = self.resumes.root / (self.version['version_id'] + '.txt')
        original = document.read_bytes()
        document.write_text('Modified synthetic CV', encoding='utf-8')
        with self.assertRaises(WorkflowError):
            self.workflow.simulate(auth)
        document.write_bytes(original)
        restarted = CandidacyWorkflow(ApplicationDatabase(self.database.path), self.resumes)
        with self.assertRaises(WorkflowError):
            restarted.simulate(auth)
        authorizations = [item for item in restarted.history(candidacy_id) if item['type'] == 'authorization']
        self.assertEqual(authorizations[-1]['status'], 'invalidated')

    def test_company_description_changes_revoke_but_retrieval_refresh_does_not(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        self.database.upsert_vacancy(replace(self.job, retrieved_at='2026-11-05T12:00:00Z'))
        self.assertIs(self.workflow.simulate(auth)['submitted'], False)
        for field, value in (('company', 'Other Company'), ('description', 'Different synthetic description')):
            with self.subTest(field=field):
                self.workflow.edit(candidacy_id, content='Revision for ' + field)
                new_auth = self.authorize(candidacy_id)
                self.database.upsert_vacancy(replace(self.job, **{field: value}))
                with self.assertRaises(WorkflowError):
                    self.workflow.simulate(new_auth)
                self.database.upsert_vacancy(self.job)
                with self.assertRaises(WorkflowError):
                    self.workflow.simulate(new_auth)

    def test_unsafe_policy_rejects_all_mutations(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        application_id = self.workflow.get(candidacy_id)['application_id']
        with patch.dict('os.environ', {'AUTO_SUBMIT': 'true'}):
            for mutation in (lambda: self.create(), lambda: self.workflow.review(candidacy_id),
                             lambda: self.workflow.edit(candidacy_id, content='Changed'),
                             lambda: self.workflow.approve(candidacy_id, '0' * 64),
                             lambda: self.workflow.simulate(auth),
                             lambda: self.workflow.update_tracking(candidacy_id, status='applied'),
                             lambda: self.database.update(application_id, status='applied')):
                with self.assertRaises(WorkflowError):
                    mutation()
        self.assertIs(self.workflow.simulate(auth)['submitted'], False)

    def test_two_independent_processes_only_one_consumes_and_restart_never_reactivates(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        script = '''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_candidacies import FileResumes
from jobsearch_assistant.candidacies import CandidacyWorkflow
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.workflow_contracts import WorkflowError
workflow = CandidacyWorkflow(ApplicationDatabase(Path(sys.argv[2])), FileResumes(Path(sys.argv[3])))
try:
    print(json.dumps(workflow.simulate(sys.argv[4])))
except WorkflowError as error:
    print(json.dumps({'error': error.code}))
'''
        arguments = [sys.executable, '-c', script, str(Path(__file__).parent),
                     str(self.database.path), str(self.resumes.root), auth]
        processes = [subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, env=os.environ.copy()) for _ in range(2)]
        responses = []
        for process in processes:
            output, errors = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, errors)
            responses.append(json.loads(output))
        self.assertEqual(sum(result.get('submitted') is False for result in responses), 1)
        self.assertEqual(sum('error' in result for result in responses), 1)
        restarted = CandidacyWorkflow(ApplicationDatabase(self.database.path), self.resumes)
        with self.assertRaises(WorkflowError):
            restarted.simulate(auth)

    def test_forged_verifier_bindings_revoke_persistently(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        original = self.resumes.verify_version
        def forged(version_id):
            metadata = original(version_id)
            metadata['sha256'] = '0' * 64
            metadata['text'] = 'Forged synthetic body'
            return metadata
        with patch.object(self.resumes, 'verify_version', side_effect=forged):
            with self.assertRaises(WorkflowError):
                self.workflow.simulate(auth)
        with self.assertRaises(WorkflowError):
            self.workflow.simulate(auth)

    def test_manifest_tampering_during_approve_invalidates_review(self):
        candidacy_id = self.create()
        reviewed = self.workflow.review(candidacy_id)
        manifest = self.resumes.root / (self.version['version_id'] + '.json')
        original = manifest.read_bytes()
        forged = json.loads(original)
        forged['vacancy_digest'] = '0' * 64
        manifest.write_text(json.dumps(forged), encoding='utf-8')
        with self.assertRaises(WorkflowError):
            self.workflow.approve(candidacy_id, reviewed['review_digest'])
        manifest.write_bytes(original)
        restarted = CandidacyWorkflow(ApplicationDatabase(self.database.path), self.resumes)
        with self.assertRaises(WorkflowError):
            restarted.approve(candidacy_id, reviewed['review_digest'])
        self.assertIsNone(restarted.get(candidacy_id)['review_digest'])

    def test_noop_edit_and_tracking_metadata_preserve_active_authorization(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        self.assertFalse(self.workflow.edit(candidacy_id, content='Synthetic cover text'))
        self.workflow.update_tracking(candidacy_id, notes='Private tracker note', next_step='Prepare')
        self.assertIs(self.workflow.simulate(auth)['submitted'], False)

    def test_unsafe_runtime_does_not_even_open_a_sender(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
            self.assertIs(self.workflow.simulate(auth)['submitted'], False)
            self.workflow.update_tracking(candidacy_id, status='applied')
        self.assertEqual(self.workflow.get(candidacy_id)['status'], 'applied')

    def test_abrupt_process_exit_before_commit_does_not_lose_authorization(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        script = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_candidacies import FileResumes
from jobsearch_assistant.candidacies import CandidacyWorkflow
from jobsearch_assistant.database import ApplicationDatabase
database = ApplicationDatabase(Path(sys.argv[2]))
workflow = CandidacyWorkflow(database, FileResumes(Path(sys.argv[3])))
original = database._event
def interrupted(connection, candidacy, kind, snapshot):
    original(connection, candidacy, kind, snapshot)
    if kind == 'simulated':
        os._exit(39)
database._event = interrupted
workflow.simulate(sys.argv[4])
"""
        result = subprocess.run([sys.executable, '-c', script, str(Path(__file__).parent),
                                str(self.database.path), str(self.resumes.root), auth],
                                check=False, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 39, result.stderr)
        restarted = CandidacyWorkflow(ApplicationDatabase(self.database.path), self.resumes)
        self.assertIs(restarted.simulate(auth)['submitted'], False)
        with self.assertRaises(WorkflowError):
            restarted.simulate(auth)

    def test_cv_version_change_revokes_and_new_revision_approves(self):
        candidacy_id = self.create()
        old_auth = self.authorize(candidacy_id)
        new_version = self.resumes.create_version(self.job, 'Synthetic Candidate\nSecond verified project')
        self.assertTrue(self.workflow.edit(candidacy_id, resume_version_id=new_version['version_id']))
        with self.assertRaises(WorkflowError):
            self.workflow.simulate(old_auth)
        new_auth = self.authorize(candidacy_id)
        self.assertNotEqual(new_auth, old_auth)
        self.assertIs(self.workflow.simulate(new_auth)['submitted'], False)

    def test_live_source_change_can_be_explicitly_revised_with_matching_new_cv(self):
        candidacy_id = self.create()
        old_auth = self.authorize(candidacy_id)
        changed_job = replace(self.job, company='Changed Synthetic Company')
        self.database.upsert_vacancy(changed_job)
        new_version = self.resumes.create_version(changed_job)
        self.assertTrue(self.workflow.edit(candidacy_id, resume_version_id=new_version['version_id']))
        self.assertEqual(self.workflow.get(candidacy_id)['company'], 'Changed Synthetic Company')
        with self.assertRaises(WorkflowError):
            self.workflow.simulate(old_auth)
        self.assertIs(self.workflow.simulate(self.authorize(candidacy_id))['submitted'], False)

    def test_bad_types_dates_hashes_states_are_static_errors(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        for operation in (lambda: self.workflow.edit(candidacy_id, resume_version_id=True),
                          lambda: self.workflow.review(True),
                          lambda: self.workflow.approve(candidacy_id, ['/private/path']),
                          lambda: self.workflow.simulate('../private/path'),
                          lambda: self.workflow.update_tracking(candidacy_id, status=['applied']),
                          lambda: self.workflow.update_tracking(candidacy_id, notes=3),
                          lambda: self.workflow.update_tracking(candidacy_id, outcome={}),
                          lambda: self.workflow.update_tracking(candidacy_id, next_step=True)):
            with self.subTest(operation=operation), self.assertRaises(WorkflowError) as raised:
                operation()
            self.assertNotIn('/private', str(raised.exception))
        self.assertIs(self.workflow.simulate(auth)['submitted'], False)

    def test_review_after_simulation_keeps_state_and_cannot_mint_capability(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        self.workflow.simulate(auth)
        history = self.workflow.history(candidacy_id)
        reviewed = self.workflow.review(candidacy_id)
        self.assertEqual(self.workflow.get(candidacy_id)['workflow_state'], 'simulated')
        self.assertEqual(self.workflow.history(candidacy_id), history)
        with self.assertRaises(WorkflowError):
            self.workflow.approve(candidacy_id, reviewed['review_digest'])

    def test_restore_revokes_old_active_capability_and_requires_fresh_revision_review(self):
        from jobsearch_assistant.migrations import backup_database, restore_backup
        candidacy_id = self.create()
        old_auth = self.authorize(candidacy_id)
        original_review = self.workflow.get(candidacy_id)['review_digest']
        old_history = self.workflow.history(candidacy_id)
        backup = self.root / 'active-backup.sqlite3'
        restored = self.root / 'restored.sqlite3'
        backup_database(self.database.path, backup)
        self.workflow.simulate(old_auth)
        restore_backup(backup, restored)
        workflow = CandidacyWorkflow(ApplicationDatabase(restored), self.resumes)
        with self.assertRaises(WorkflowError):
            workflow.simulate(old_auth)
        result = workflow.get(candidacy_id)
        self.assertEqual(result['revision'], 2)
        self.assertEqual(result['workflow_state'], 'draft')
        self.assertIsNone(result['review_digest'])
        with self.assertRaises(WorkflowError):
            workflow.approve(candidacy_id, original_review)
        reviewed = workflow.review(candidacy_id)
        new_auth = workflow.approve(candidacy_id, reviewed['review_digest'])
        self.assertNotEqual(new_auth, old_auth)
        self.assertIs(workflow.simulate(new_auth)['submitted'], False)
        # The private backup and terminal original keep their original states.
        backup_workflow = CandidacyWorkflow(ApplicationDatabase(backup), self.resumes)
        self.assertEqual(backup_workflow.history(candidacy_id), old_history)
        original_auths = [item for item in self.workflow.history(candidacy_id) if item['type'] == 'authorization']
        self.assertEqual(original_auths[-1]['status'], 'consumed')

    def test_restore_never_publishes_live_authorization_and_is_atomic_on_failure(self):
        import sqlite3
        from contextlib import closing
        from jobsearch_assistant import migrations
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        backup = self.root / 'active-backup.sqlite3'
        migrations.backup_database(self.database.path, backup)
        destination = self.root / 'restored.sqlite3'
        original_guard = migrations._invalidate_restored_workflow
        def interrupted(connection):
            original_guard(connection)
            raise RuntimeError('Synthetic restore interruption')
        with patch.object(migrations, '_invalidate_restored_workflow', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                migrations.restore_backup(backup, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob('.*.restore-*')), [])
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute('SELECT status FROM candidacy_authorizations WHERE authorization_id=?',
                                               (auth,)).fetchone()[0], 'active')
        real_link = os.link
        def guarded_publish(staging, target, *args, **kwargs):
            self.assertFalse(destination.exists())
            with closing(sqlite3.connect(staging)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM candidacy_authorizations WHERE status='active'").fetchone()[0], 0)
                self.assertEqual(connection.execute('SELECT revision, workflow_state, review_digest FROM candidacies').fetchone(),
                                 (2, 'draft', None))
            return real_link(staging, target, *args, **kwargs)
        with patch.object(migrations.os, 'link', side_effect=guarded_publish) as publication:
            migrations.restore_backup(backup, destination)
        publication.assert_called_once()
        self.assertEqual(list(self.root.glob('.*.restore-*')), [])
        with self.assertRaises(WorkflowError):
            CandidacyWorkflow(ApplicationDatabase(destination), self.resumes).simulate(auth)

    def test_restore_preserves_terminal_authorizations_and_publish_failures_leave_no_copy(self):
        import sqlite3
        from contextlib import closing
        from jobsearch_assistant import migrations
        states = {}
        for index, state in enumerate(('active', 'consumed', 'invalidated')):
            job = replace(self.job, source_job_id='restore-' + state,
                          url='https://example.test/restore-' + state)
            vacancy_id = self.database.upsert_vacancy(job)
            version = self.resumes.create_version(job)
            candidacy_id = self.workflow.create(vacancy_id, version['version_id'], 'Synthetic restore text')
            authorization = self.authorize(candidacy_id)
            if state == 'consumed':
                self.workflow.simulate(authorization)
            elif state == 'invalidated':
                self.workflow.edit(candidacy_id, content='Changed restore text')
            states[authorization] = state
        backup = self.root / 'restore-states.sqlite3'
        destination = self.root / 'restored-states.sqlite3'
        migrations.backup_database(self.database.path, backup)
        with patch.object(migrations.os, 'link', side_effect=OSError('Synthetic publication failure')):
            with self.assertRaises(OSError):
                migrations.restore_backup(backup, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob('.*.restore-*')), [])
        for path in (self.database.path, backup):
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(dict(connection.execute('SELECT authorization_id, status FROM candidacy_authorizations')), states)
        migrations.restore_backup(backup, destination)
        expected = {key: 'invalidated' if value == 'active' else value for key, value in states.items()}
        with closing(sqlite3.connect(destination)) as connection:
            self.assertEqual(dict(connection.execute('SELECT authorization_id, status FROM candidacy_authorizations')), expected)

    def test_restore_publication_race_preserves_destination_created_by_other_process(self):
        from jobsearch_assistant import migrations
        candidacy_id = self.create()
        self.authorize(candidacy_id)
        backup = self.root / 'restore-race.sqlite3'
        destination = self.root / 'restored-race.sqlite3'
        migrations.backup_database(self.database.path, backup)
        real_link = os.link
        def conflicting_publish(staging, target, *args, **kwargs):
            destination.write_bytes(b'Synthetic existing destination')
            return real_link(staging, target, *args, **kwargs)
        with patch.object(migrations.os, 'link', side_effect=conflicting_publish):
            with self.assertRaises(FileExistsError):
                migrations.restore_backup(backup, destination)
        self.assertEqual(destination.read_bytes(), b'Synthetic existing destination')
        self.assertEqual(list(self.root.glob('.*.restore-*')), [])
