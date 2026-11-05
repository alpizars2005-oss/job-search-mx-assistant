"""Synthetic SQLite workflow contract tests, including a concrete file verifier."""
import copy
import hashlib
import json
import sqlite3
import tempfile
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.candidacies import CandidacyWorkflow
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.models import ApplicationRecord, EvaluationResult, JobPosting
from jobsearch_assistant.sources.models import NormalizedJob
from jobsearch_assistant.workflow_contracts import (
    WorkflowError, canonical_json, content_digest, vacancy_digest, vacancy_key,
)


def synthetic_job(**updates):
    values = dict(source='manual', source_board='synthetic', source_job_id='job-1',
                  company='Synthetic Company', title='Python Developer', locations=['Mexico'],
                  work_mode='remote', url='https://example.test/job-1', description='Python project',
                  published_at=None, retrieved_at='2026-11-04T12:00:00Z',
                  verification_status='unverified', eligibility_evidence={}, provenance={})
    values.update(updates)
    return NormalizedJob(**values)


class FileResumes:
    """Concrete immutable manifest + byte SHA verifier; no optional callback."""
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_version(self, job, text='Synthetic Candidate\nPython project'):
        document = text.encode('utf-8')
        metadata = dict(master_id='b' * 64, sha256=hashlib.sha256(document).hexdigest(),
                        language='en', format='txt', vacancy_key=vacancy_key(job),
                        vacancy_digest=vacancy_digest(job), claim_ids=['project-1'],
                        created_at='2026-11-04T12:00:00Z', text=text,
                        candidate_name='Synthetic Candidate',
                        claims=[{'id': 'project-1', 'kind': 'project',
                                 'text': 'Synthetic Python project', 'evidence_ids': ['evidence-1']}])
        version_id = content_digest(metadata)
        metadata['version_id'] = version_id
        (self.root / (version_id + '.txt')).write_bytes(document)
        (self.root / (version_id + '.json')).write_text(canonical_json(metadata), encoding='utf-8')
        return metadata

    def verify_version(self, version_id):
        metadata = json.loads((self.root / (version_id + '.json')).read_text(encoding='utf-8'))
        manifest = copy.deepcopy(metadata)
        manifest.pop('version_id')
        if content_digest(manifest) != version_id:
            raise WorkflowError('resume_integrity_failed')
        document = (self.root / (version_id + '.txt')).read_bytes()
        if hashlib.sha256(document).hexdigest() != metadata['sha256']:
            raise WorkflowError('resume_integrity_failed')
        return metadata


class WorkflowCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = ApplicationDatabase(self.root / 'tracker.sqlite3')
        self.resumes = FileResumes(self.root / 'resumes')
        self.job = synthetic_job()
        self.vacancy_id = self.database.upsert_vacancy(self.job)
        self.version = self.resumes.create_version(self.job)
        self.workflow = CandidacyWorkflow(self.database, self.resumes)
        self.policy = patch.dict('os.environ', {'DRY_RUN': 'true', 'AUTO_SUBMIT': 'false'})
        self.policy.start()
        self.addCleanup(self.policy.stop)

    def create(self):
        return self.workflow.create(self.vacancy_id, self.version['version_id'], 'Synthetic cover text')

    def authorize(self, candidacy_id):
        return self.workflow.approve(candidacy_id, self.workflow.review(candidacy_id)['review_digest'])


class CandidacyTests(WorkflowCase):
    def test_create_reuses_legacy_application_and_deduplicates_vacancy(self):
        application_id = self.database.add(ApplicationRecord(
            id=None, job=JobPosting(title=self.job.title, company=self.job.company,
                                    url=self.job.url, description=self.job.description),
            evaluation=EvaluationResult(82, 'strong_fit'), notes='preserved legacy note'))
        candidacy_id = self.create()
        self.assertEqual(self.create(), candidacy_id)
        result = self.workflow.get(candidacy_id)
        self.assertEqual(result['application_id'], application_id)
        self.assertEqual(result['vacancy_id'], self.vacancy_id)
        self.assertEqual(result['revision'], 1)
        self.assertEqual(result['workflow_state'], 'draft')
        self.assertEqual(result['notes'], 'preserved legacy note')
        self.assertEqual(len(self.database.list()), 1)
        self.assertEqual(len(self.workflow.list()), 1)
        self.assertIsNone(self.workflow.get(999))

    def test_edits_are_immutable_and_exact_noops_do_not_rewrite_history(self):
        candidacy_id = self.create()
        old_history = self.workflow.history(candidacy_id)
        self.assertFalse(self.workflow.edit(candidacy_id, content='Synthetic cover text'))
        self.assertEqual(self.workflow.history(candidacy_id), old_history)
        self.assertTrue(self.workflow.edit(candidacy_id, content='Changed synthetic text'))
        self.assertEqual(self.workflow.get(candidacy_id)['revision'], 2)
        self.assertTrue(self.workflow.edit(candidacy_id, content='Synthetic cover text'))
        self.assertEqual(self.workflow.get(candidacy_id)['revision'], 3)
        history = self.workflow.history(candidacy_id)
        revisions = [item for item in history if item['type'] == 'revision']
        self.assertEqual([item['snapshot']['content'] for item in revisions],
                         ['Synthetic cover text', 'Changed synthetic text', 'Synthetic cover text'])

    def test_managed_tracker_graph_and_legacy_database_calls_are_guarded(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        application_id = self.workflow.get(candidacy_id)['application_id']
        self.assertTrue(self.database.update(application_id, status='interested'))
        self.assertTrue(self.database.update(application_id, status='applied'))
        with self.assertRaises(WorkflowError):
            self.workflow.simulate(auth)
        with self.assertRaises(WorkflowError):
            self.database.update(application_id, status='saved')
        for status in ('screening', 'interview', 'offer'):
            self.assertTrue(self.workflow.update_tracking(candidacy_id, status=status))
        self.assertFalse(self.workflow.update_tracking(candidacy_id, status='offer'))
        with self.assertRaises(WorkflowError):
            self.workflow.update_tracking(candidacy_id, status='rejected')
        legacy = self.database.add(ApplicationRecord(None, JobPosting(company='Other'), EvaluationResult(0, 'review')))
        self.assertTrue(self.database.update(legacy, status='offer'))
        self.assertTrue(self.database.update(legacy, status='saved'))

    def test_tracking_metadata_calendar_validation_and_noop(self):
        candidacy_id = self.create()
        future = (date.today() + timedelta(days=30)).isoformat()
        self.assertTrue(self.workflow.update_tracking(candidacy_id, notes='Synthetic note',
                        outcome='Awaiting answer', next_step='Prepare questions', follow_up_on=future))
        result = self.workflow.get(candidacy_id)
        self.assertEqual(result['follow_up_on'], future)
        self.assertEqual(result['outcome'], 'Awaiting answer')
        previous = self.workflow.history(candidacy_id)
        self.assertFalse(self.workflow.update_tracking(candidacy_id, notes='Synthetic note',
                        outcome='Awaiting answer', next_step='Prepare questions', follow_up_on=future))
        self.assertEqual(self.workflow.history(candidacy_id), previous)
        for invalid in ('2026-02-30', '2026-1-01', 'tomorrow', True, 7):
            with self.subTest(invalid=invalid), self.assertRaises(WorkflowError):
                self.workflow.update_tracking(candidacy_id, follow_up_on=invalid)

    def test_no_orphan_application_when_create_fails(self):
        with self.assertRaises(WorkflowError):
            self.workflow.create(self.vacancy_id, '0' * 64, 'Synthetic')
        self.assertEqual(self.database.list(), [])
        self.assertEqual(self.workflow.list(), [])

    def test_wrong_vacancy_binding_and_malformed_input_fail_safely(self):
        other = synthetic_job(source_job_id='job-2', company='Other Synthetic')
        other_id = self.database.upsert_vacancy(other)
        for vacancy, version, content in ((True, self.version['version_id'], 'Text'),
                         (self.vacancy_id, '../private/path', 'Text'),
                         (self.vacancy_id, self.version['version_id'], 3),
                         (other_id, self.version['version_id'], 'Text')):
            with self.subTest(vacancy=vacancy), self.assertRaises(WorkflowError) as raised:
                self.workflow.create(vacancy, version, content)
            self.assertNotIn('private/path', str(raised.exception))

    def test_legacy_update_cannot_use_bool_as_managed_record_identifier(self):
        candidacy_id = self.create()
        with self.assertRaises(WorkflowError):
            self.database.update(True, status='applied')
        self.assertEqual(self.workflow.get(candidacy_id)['status'], 'saved')

    def test_complete_managed_transition_matrix(self):
        graph = {
            'saved': {'interested', 'applied', 'rejected', 'withdrawn'},
            'interested': {'saved', 'applied', 'rejected', 'withdrawn'},
            'applied': {'screening', 'interview', 'offer', 'rejected', 'withdrawn'},
            'screening': {'interview', 'offer', 'rejected', 'withdrawn'},
            'interview': {'offer', 'rejected', 'withdrawn'},
            'offer': set(), 'rejected': set(), 'withdrawn': set(),
        }
        candidacy_id = self.create()
        application_id = self.workflow.get(candidacy_id)['application_id']
        # Set up each source state directly; every tested operation still uses
        # the public API to enforce the requested edge.
        for current, allowed in graph.items():
            for target in graph:
                with self.subTest(current=current, target=target):
                    with self.database._connection() as connection:
                        connection.execute('UPDATE applications SET status=? WHERE id=?',
                                           (current, application_id))
                    if target == current:
                        self.assertFalse(self.database.update(application_id, status=target))
                    elif target in allowed:
                        self.assertTrue(self.database.update(application_id, status=target))
                    else:
                        with self.assertRaises(WorkflowError):
                            self.database.update(application_id, status=target)

    def test_failed_revision_write_rolls_back_new_application_and_identity(self):
        with self.database._connection() as connection:
            connection.execute("""CREATE TRIGGER synthetic_revision_failure
                BEFORE INSERT ON candidacy_revisions BEGIN
                SELECT RAISE(ABORT, 'Synthetic interruption'); END""")
        with self.assertRaises(Exception):
            self.create()
        self.assertEqual(self.database.list(), [])
        self.assertEqual(self.workflow.list(), [])
        with self.database._connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM application_identities').fetchone()[0], 0)

    def test_revision_and_event_snapshots_cannot_be_rewritten(self):
        candidacy_id = self.create()
        self.authorize(candidacy_id)
        previous = self.workflow.history(candidacy_id)
        for table in ('candidacy_revisions', 'candidacy_events'):
            for operation in ('UPDATE ' + table + " SET snapshot_json='{}'", 'DELETE FROM ' + table):
                with self.subTest(operation=operation), self.assertRaises(Exception):
                    with self.database._connection() as connection:
                        connection.execute(operation)
        self.assertEqual(self.workflow.history(candidacy_id), previous)

    def test_concurrent_process_create_reuses_one_application_and_revision(self):
        script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_candidacies import FileResumes
from jobsearch_assistant.candidacies import CandidacyWorkflow
from jobsearch_assistant.database import ApplicationDatabase
workflow = CandidacyWorkflow(ApplicationDatabase(Path(sys.argv[2])), FileResumes(Path(sys.argv[3])))
print(workflow.create(int(sys.argv[4]), sys.argv[5], 'Synthetic cover text'))
"""
        args = [sys.executable, '-c', script, str(Path(__file__).parent), str(self.database.path),
                str(self.resumes.root), str(self.vacancy_id), self.version['version_id']]
        processes = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, env=os.environ.copy()) for _ in range(2)]
        results = []
        for process in processes:
            output, errors = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, errors)
            results.append(int(output))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.database.list()), 1)
        self.assertEqual(len(self.workflow.list()), 1)
        self.assertEqual(len([item for item in self.workflow.history(results[0])
                              if item['type'] == 'revision']), 1)

    def test_changing_vacancy_requires_matching_cv_and_revokes_previous_authorization(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        other = synthetic_job(source_job_id='job-2', company='Other Company', url='https://example.test/job-2')
        vacancy_id = self.database.upsert_vacancy(other)
        version = self.resumes.create_version(other)
        self.assertTrue(self.workflow.edit(candidacy_id, vacancy_id=vacancy_id,
                                          resume_version_id=version['version_id']))
        result = self.workflow.get(candidacy_id)
        self.assertEqual(result['vacancy_id'], vacancy_id)
        self.assertEqual(result['company'], 'Other Company')
        self.assertEqual(result['revision'], 2)
        with self.assertRaises(WorkflowError):
            self.workflow.simulate(auth)
        self.assertEqual(self.database.find_duplicate(JobPosting(title=other.title, company=other.company,
                                                               url=other.url)), result['application_id'])

    def test_retarget_and_source_repair_preserve_previous_evaluation_without_reattribution(self):
        for source_repair in (False, True):
            with self.subTest(source_repair=source_repair):
                job = synthetic_job(source_job_id='repair' if source_repair else 'retarget',
                                    url='https://example.test/repair' if source_repair else 'https://example.test/retarget')
                vacancy_id = self.database.upsert_vacancy(job)
                old_evaluation = EvaluationResult(95, 'high_priority', algorithm_version='matching_v2',
                                                 reasons=['Only Original Company role fits'])
                application_id = self.database.add(ApplicationRecord(None,
                    JobPosting(title=job.title, company=job.company, url=job.url, description=job.description,
                               location=', '.join(job.locations)), old_evaluation))
                old_version = self.resumes.create_version(job)
                candidacy_id = self.workflow.create(vacancy_id, old_version['version_id'], 'Synthetic text')
                with self.database._connection() as connection:
                    previous = dict(connection.execute('SELECT * FROM applications WHERE id=?', (application_id,)).fetchone())
                changed = replace(job, company='Different Synthetic Company', title='Senior Other Role',
                                  description='Different requirements',
                                  source_job_id=job.source_job_id if source_repair else 'new-retarget',
                                  url=job.url if source_repair else 'https://example.test/new-retarget')
                changed_id = self.database.upsert_vacancy(changed)
                new_version = self.resumes.create_version(changed)
                self.workflow.edit(candidacy_id, vacancy_id=changed_id, resume_version_id=new_version['version_id'])
                result = next(item for item in self.database.list() if item.id == application_id)
                self.assertEqual(result.job.company, changed.company)
                self.assertEqual(result.evaluation.recommendation, 'insufficient_information')
                self.assertEqual(result.evaluation.score, 0)
                self.assertNotIn('Only Original Company role fits', result.evaluation.reasons)
                preserved = [item for item in self.workflow.history(candidacy_id)
                             if item.get('event_type') == 'application_snapshot_preserved']
                self.assertEqual(preserved[-1]['snapshot']['application'], previous)

    def test_content_only_edit_preserves_current_evaluation_and_failed_retarget_is_atomic(self):
        evaluation = EvaluationResult(95, 'high_priority', reasons=['Synthetic verified match'])
        application_id = self.database.add(ApplicationRecord(None,
            JobPosting(title=self.job.title, company=self.job.company, url=self.job.url,
                       description=self.job.description, location=', '.join(self.job.locations)), evaluation))
        candidacy_id = self.create()
        self.workflow.edit(candidacy_id, content='Content-only update')
        self.assertEqual(self.database.list()[0].evaluation.to_dict(), evaluation.to_dict())
        self.assertFalse(any(item.get('event_type') == 'application_snapshot_preserved'
                             for item in self.workflow.history(candidacy_id)))
        auth = self.authorize(candidacy_id)
        before = self.workflow.history(candidacy_id)
        other = replace(self.job, source_job_id='atomic-retarget', company='Other Synthetic',
                        url='https://example.test/atomic-retarget')
        vacancy_id = self.database.upsert_vacancy(other)
        version = self.resumes.create_version(other)
        with self.database._connection() as connection:
            connection.execute("""CREATE TRIGGER synthetic_retarget_failure
                BEFORE INSERT ON candidacy_revisions WHEN NEW.revision=3
                BEGIN SELECT RAISE(ABORT, 'Synthetic retarget failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.workflow.edit(candidacy_id, vacancy_id=vacancy_id, resume_version_id=version['version_id'])
        result = next(item for item in self.database.list() if item.id == application_id)
        self.assertEqual(result.job.company, self.job.company)
        self.assertEqual(result.evaluation.to_dict(), evaluation.to_dict())
        self.assertEqual(self.workflow.history(candidacy_id), before)
        self.assertIs(self.workflow.simulate(auth)['submitted'], False)

    def test_history_uses_one_read_snapshot_during_interleaved_writer(self):
        candidacy_id = self.create()
        with self.database._connection() as connection:
            self.assertEqual(connection.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
        writer = CandidacyWorkflow(ApplicationDatabase(self.database.path), self.resumes)
        triggered = []
        class InterleavingConnection(sqlite3.Connection):
            def execute(inner, sql, *args, **kwargs):
                if sql.startswith('SELECT * FROM candidacy_events') and not triggered:
                    triggered.append(True)
                    writer.edit(candidacy_id, content='Writer second revision')
                return super().execute(sql, *args, **kwargs)
        def interleaving_connection():
            connection = sqlite3.connect(self.database.path, timeout=30, factory=InterleavingConnection)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            return connection
        with patch.object(self.database, 'connect', side_effect=interleaving_connection):
            history = self.workflow.history(candidacy_id)
        self.assertTrue(triggered)
        self.assertEqual(self.workflow.get(candidacy_id)['revision'], 2)
        revisions = {item['revision'] for item in history if item['type'] == 'revision'}
        event_revisions = {item['revision'] for item in history if item['type'] == 'event'}
        self.assertEqual(revisions, {1})
        self.assertTrue(event_revisions <= revisions)

    def test_verifier_is_required_and_errors_are_redacted(self):
        with self.assertRaises(WorkflowError):
            CandidacyWorkflow(self.database, object())
        candidacy_id = self.create()
        with patch.object(self.resumes, 'verify_version', side_effect=OSError('/private/cv/full-text')):
            with self.assertRaises(WorkflowError) as raised:
                self.workflow.review(candidacy_id)
        self.assertNotIn('/private', str(raised.exception))


class BackendIntegrationBoundaryTests(WorkflowCase):
    def test_generated_content_and_resume_regeneration_are_verified_inside_writer_transaction(self):
        from jobsearch_assistant.drafts import build_draft
        from contextlib import closing
        metadata = self.resumes.verify_version(self.version['version_id'])
        observed = []
        def locked_generation(job, version):
            observed.append(version['version_id'])
            with closing(sqlite3.connect(self.database.path, timeout=0)) as independent:
                with self.assertRaises(sqlite3.OperationalError):
                    independent.execute('BEGIN IMMEDIATE')
            return build_draft(job, version)
        with patch('jobsearch_assistant.drafts.build_draft', side_effect=locked_generation):
            candidacy_id = self.workflow.create(self.vacancy_id, self.version['version_id'], None)
            expected = build_draft(self.job, metadata)
            self.assertEqual(self.workflow.get(candidacy_id)['content'], expected)
            self.assertFalse(self.workflow.edit(candidacy_id, regenerate_content=True))
            self.workflow.edit(candidacy_id, content='Manual synthetic text')
            self.assertTrue(self.workflow.edit(candidacy_id, regenerate_content=True))
            self.assertEqual(self.workflow.get(candidacy_id)['content'], expected)
        self.assertEqual(observed, [self.version['version_id']] * 3)

    def test_existing_create_and_regeneration_guard_current_before_any_replacement_verification(self):
        for operation in ('duplicate_create', 'regenerate_edit'):
            with self.subTest(operation=operation):
                candidacy_id = self.create()
                auth = self.authorize(candidacy_id)
                original_verify = self.resumes.verify_version
                verified = []
                def lazy_constructor_failure(version_id):
                    verified.append(version_id)
                    raise OSError('/private/store/construction/failure')
                with patch.object(self.resumes, 'verify_version', side_effect=lazy_constructor_failure):
                    with self.assertRaises(WorkflowError):
                        if operation == 'duplicate_create':
                            self.workflow.create(self.vacancy_id, self.version['version_id'], None)
                        else:
                            self.workflow.edit(candidacy_id, resume_version_id=self.version['version_id'],
                                               regenerate_content=True)
                self.assertEqual(verified, [self.version['version_id']])
                original_verify(self.version['version_id'])
                with self.assertRaises(WorkflowError):
                    self.workflow.simulate(auth)
                if operation == 'duplicate_create':
                    # A real content edit gives the next case an independent
                    # revision; an invalidated capability is never renewed.
                    self.workflow.edit(candidacy_id, content='Next independent synthetic revision')

    def test_duplicate_application_alias_checks_current_binding_before_requested_cv(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        alias = replace(self.job, source_job_id='alias-job', company='Alias Synthetic Company')
        alias_id = self.database.upsert_vacancy(alias)
        alias_version = self.resumes.create_version(alias)
        verified = []
        def failed_current_verifier(version_id):
            verified.append(version_id)
            raise WorkflowError('resume_integrity_failed')
        with patch.object(self.resumes, 'verify_version', side_effect=failed_current_verifier):
            with self.assertRaises(WorkflowError):
                self.workflow.create(alias_id, alias_version['version_id'], None)
        self.assertEqual(verified, [self.version['version_id']])
        with self.assertRaises(WorkflowError):
            self.workflow.simulate(auth)
        self.assertEqual(len(self.workflow.list()), 1)

    def test_invalid_generation_arguments_do_not_revoke_valid_approval(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        original = self.workflow.history(candidacy_id)
        for arguments in ({'regenerate_content': 1}, {'regenerate_content': 'true'},
                          {'regenerate_content': True, 'content': 'Explicit synthetic text'}):
            with self.subTest(arguments=arguments), self.assertRaises(WorkflowError):
                self.workflow.edit(candidacy_id, **arguments)
        self.assertEqual(self.workflow.history(candidacy_id), original)
        self.assertIs(self.workflow.simulate(auth)['submitted'], False)

    def test_invalid_requested_replacement_keeps_valid_current_authorization(self):
        candidacy_id = self.create()
        auth = self.authorize(candidacy_id)
        original = self.workflow.history(candidacy_id)
        with self.assertRaises(WorkflowError):
            self.workflow.edit(candidacy_id, resume_version_id='0' * 64, regenerate_content=True)
        self.assertEqual(self.workflow.history(candidacy_id), original)
        self.assertIs(self.workflow.simulate(auth)['submitted'], False)

    def test_initial_legacy_adoption_reconciles_current_job_preserving_old_row_and_dates(self):
        for status in ('saved', 'interested'):
            with self.subTest(status=status):
                target = replace(self.job, source_job_id='adopt-' + status,
                                 company='New Synthetic Company', title='Senior Rust Director',
                                 description='New synthetic Rust requirements',
                                 url='https://example.test/Jobs/Case-ID-' + status)
                target_id = self.database.upsert_vacancy(target)
                version = self.resumes.create_version(target)
                old = ApplicationRecord(None, JobPosting(title='Junior Python Developer',
                    company='Old Synthetic Company', url=target.url, description='Old Python requirements'),
                    EvaluationResult(95, 'high_priority', reasons=['Only Old Synthetic Company fits']),
                    status=status, notes='Preserved synthetic note',
                    created_at='2024-01-02T03:04:05Z', updated_at='2024-02-03T04:05:06Z')
                application_id = self.database.add(old)
                with self.database._connection() as connection:
                    previous = dict(connection.execute('SELECT * FROM applications WHERE id=?',
                                                       (application_id,)).fetchone())
                candidacy_id = self.workflow.create(target_id, version['version_id'], 'Synthetic adoption text')
                result = next(item for item in self.database.list() if item.id == application_id)
                self.assertEqual(result.job.company, target.company)
                self.assertEqual(result.job.title, target.title)
                self.assertEqual(result.job.description, target.description)
                self.assertEqual(result.evaluation.recommendation, 'insufficient_information')
                self.assertEqual(result.evaluation.algorithm_version, 'unevaluated')
                self.assertEqual(result.status, status)
                self.assertEqual(result.notes, old.notes)
                self.assertEqual(result.created_at, old.created_at)
                self.assertEqual(result.updated_at, old.updated_at)
                preserved = [item for item in self.workflow.history(candidacy_id)
                             if item.get('event_type') == 'application_snapshot_preserved']
                self.assertEqual(preserved[-1]['snapshot']['application'], previous)
                self.assertEqual(preserved[-1]['snapshot']['target_vacancy'], json.loads(canonical_json(target.__dict__)))
                reviewed = self.workflow.review(candidacy_id)
                self.assertEqual(reviewed['snapshot']['company'], result.job.company)
                self.assertEqual(reviewed['snapshot']['vacancy']['title'], result.job.title)

    def test_mismatched_applied_and_later_legacy_adoptions_are_rejected_without_history(self):
        for status in ('applied', 'screening', 'interview', 'offer', 'rejected', 'withdrawn'):
            with self.subTest(status=status):
                target = replace(self.job, source_job_id='historical-' + status,
                                 company='New Synthetic Company', url='https://example.test/historical-' + status)
                target_id = self.database.upsert_vacancy(target)
                version = self.resumes.create_version(target)
                application_id = self.database.add(ApplicationRecord(None,
                    JobPosting(company='Previous Synthetic Company', url=target.url),
                    EvaluationResult(95, 'high_priority'), status=status))
                with self.database._connection() as connection:
                    before = dict(connection.execute('SELECT * FROM applications WHERE id=?',
                                                     (application_id,)).fetchone())
                with self.assertRaises(WorkflowError):
                    self.workflow.create(target_id, version['version_id'], 'Synthetic adoption text')
                with self.database._connection() as connection:
                    self.assertEqual(dict(connection.execute('SELECT * FROM applications WHERE id=?',
                                                            (application_id,)).fetchone()), before)
                    self.assertIsNone(connection.execute('SELECT id FROM candidacies WHERE application_id=?',
                                                         (application_id,)).fetchone())
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM candidacy_events').fetchone()[0], 0)

    def test_same_content_legacy_adoption_preserves_exact_evaluation_json_even_when_applied(self):
        for index, status in enumerate(('saved', 'interested', 'applied', 'offer')):
            with self.subTest(status=status):
                target = replace(self.job, source_job_id='exact-' + status,
                                 url='https://example.test/exact-' + status)
                vacancy_id = self.database.upsert_vacancy(target)
                version = self.resumes.create_version(target)
                application_id = self.database.add(ApplicationRecord(None,
                    JobPosting(title=target.title, company=target.company,
                               location=', '.join(target.locations), url=target.url, description=target.description),
                    EvaluationResult(95, 'high_priority', reasons=['Exact synthetic job']), status=status))
                with self.database._connection() as connection:
                    connection.execute('UPDATE applications SET evaluation_json=? WHERE id=?',
                        ('{ "score" : 95, "recommendation" : "high_priority", "reasons" : ["Exact synthetic job"] }', application_id))
                    previous = dict(connection.execute('SELECT * FROM applications WHERE id=?',
                                                       (application_id,)).fetchone())
                candidacy_id = self.workflow.create(vacancy_id, version['version_id'], 'Synthetic adoption text')
                with self.database._connection() as connection:
                    self.assertEqual(dict(connection.execute('SELECT * FROM applications WHERE id=?',
                                                            (application_id,)).fetchone()), previous)
                self.assertFalse(any(item.get('event_type') == 'application_snapshot_preserved'
                                     for item in self.workflow.history(candidacy_id)))

    def test_new_application_placeholder_does_not_claim_matching_engine_execution(self):
        candidacy_id = self.create()
        application_id = self.workflow.get(candidacy_id)['application_id']
        result = next(item for item in self.database.list() if item.id == application_id)
        self.assertEqual(result.evaluation.recommendation, 'insufficient_information')
        self.assertEqual(result.evaluation.algorithm_version, 'unevaluated')
        self.assertEqual(result.evaluation.score, 0)

    def test_legacy_reconciliation_failure_rolls_back_original_row_and_all_new_history(self):
        application_id = self.database.add(ApplicationRecord(None,
            JobPosting(company='Old Synthetic Company', url=self.job.url),
            EvaluationResult(95, 'high_priority'), notes='Original synthetic notes'))
        with self.database._connection() as connection:
            original = dict(connection.execute('SELECT * FROM applications WHERE id=?', (application_id,)).fetchone())
            connection.execute("""CREATE TRIGGER synthetic_adoption_failure BEFORE INSERT ON candidacy_revisions
                BEGIN SELECT RAISE(ABORT, 'Synthetic adoption failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.create()
        with self.database._connection() as connection:
            self.assertEqual(dict(connection.execute('SELECT * FROM applications WHERE id=?',
                                                    (application_id,)).fetchone()), original)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM candidacies').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM candidacy_events').fetchone()[0], 0)
