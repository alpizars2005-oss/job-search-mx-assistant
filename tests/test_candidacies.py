"""Synthetic SQLite workflow contract tests, including a concrete file verifier."""
import copy
import hashlib
import json
import tempfile
import os
import subprocess
import sys
import unittest
from contextlib import closing
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
                        candidate_name='Synthetic Candidate')
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

    def test_verifier_is_required_and_errors_are_redacted(self):
        with self.assertRaises(WorkflowError):
            CandidacyWorkflow(self.database, object())
        candidacy_id = self.create()
        with patch.object(self.resumes, 'verify_version', side_effect=OSError('/private/cv/full-text')):
            with self.assertRaises(WorkflowError) as raised:
                self.workflow.review(candidacy_id)
        self.assertNotIn('/private', str(raised.exception))
