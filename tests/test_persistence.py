import json
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, replace
from pathlib import Path

from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.models import (
    ApplicationRecord,
    CandidateProfile,
    EvaluationResult,
    JobPosting,
)
from jobsearch_assistant.sources.models import NormalizedJob


def record(url='https://example.test/Jobs/ABC'):
    return ApplicationRecord(
        id=None, job=JobPosting(title='Python Developer', company='Synthetic Co', url=url),
        evaluation=EvaluationResult(score=82, recommendation='strong_fit'),
        notes='Synthetic notes',
    )


def normalized_job(**changes):
    job = NormalizedJob(
        source='greenhouse', source_board='synthetic', source_job_id='123',
        company='Synthetic Co', title='Python Developer', locations=['Mexico'],
        work_mode='remote', url='https://example.test/Jobs/ABC',
        description='Synthetic Python role', published_at=None,
        retrieved_at='2026-11-04T10:20:30Z', verification_status='listed',
        eligibility_evidence={'mexico': None},
        provenance={'description': ['$.jobs[0].content'], 'title': ['$.jobs[0].title']},
    )
    return replace(job, **changes)


class PersistenceTests(unittest.TestCase):
    def test_add_is_idempotent_after_restart_and_preserves_original_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            database = ApplicationDatabase(path)
            first = database.add(record())
            changed = record()
            changed.notes = 'Must not overwrite original'
            self.assertEqual(ApplicationDatabase(path).add(changed), first)
            self.assertEqual(len(database.list()), 1)
            self.assertEqual(database.list()[0].notes, 'Synthetic notes')

    def test_url_paths_and_queries_remain_case_sensitive(self):
        with tempfile.TemporaryDirectory() as directory:
            database = ApplicationDatabase(Path(directory) / 'test.sqlite3')
            first = database.add(record('HTTPS://EXAMPLE.TEST/Jobs/ABC?Token=A'))
            self.assertEqual(database.find_duplicate(
                record('https://example.test/Jobs/ABC?Token=A').job), first)
            self.assertIsNone(database.find_duplicate(
                record('https://example.test/jobs/abc?Token=A').job))
            self.assertIsNone(database.find_duplicate(
                record('https://example.test/Jobs/ABC?Token=a').job))

    def test_add_with_no_url_uses_normalized_company_and_title(self):
        with tempfile.TemporaryDirectory() as directory:
            database = ApplicationDatabase(Path(directory) / 'test.sqlite3')
            first = database.add(record(''))
            duplicate = record('')
            duplicate.job.company = ' SYNTHETIC CO '
            duplicate.job.title = ' python developer '
            self.assertEqual(database.add(duplicate), first)

    def test_two_independent_initializers_and_legacy_writers_deduplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            barrier = threading.Barrier(2)

            def write(_):
                barrier.wait(timeout=10)
                return ApplicationDatabase(path).add(record())

            with ThreadPoolExecutor(max_workers=2) as executor:
                identifiers = list(executor.map(write, range(2)))
            self.assertEqual(identifiers, [1, 1])
            self.assertEqual(len(ApplicationDatabase(path).list()), 1)

    def test_vacancy_upsert_preserves_all_source_evidence_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            job = normalized_job()
            database = ApplicationDatabase(path)
            identifier = database.upsert_vacancy(job)
            self.assertEqual(ApplicationDatabase(path).get_vacancy(identifier), job)
            self.assertEqual(database.list_vacancies(), [{'id': identifier, 'job': asdict(job)}])
            self.assertIsNone(database.get_vacancy(999))

    def test_vacancy_identity_includes_source_board_and_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            database = ApplicationDatabase(Path(directory) / 'test.sqlite3')
            identifier = database.upsert_vacancy(normalized_job())
            changed = normalized_job(description='Updated description', retrieved_at='2026-11-05T01:00:00Z')
            self.assertEqual(database.upsert_vacancy(changed), identifier)
            self.assertEqual(database.get_vacancy(identifier), changed)
            different_board = database.upsert_vacancy(normalized_job(source_board='other'))
            different_source = database.upsert_vacancy(normalized_job(source='lever'))
            self.assertEqual(len({identifier, different_board, different_source}), 3)
            self.assertEqual(len(database.list_vacancies()), 3)

    def test_evaluation_reuses_canonical_inputs_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            database = ApplicationDatabase(path)
            job = normalized_job()
            vacancy = database.upsert_vacancy(job)
            profile = CandidateProfile(skills=['Python'], conditions={'travel': False, 'on_call': None})
            result = EvaluationResult(score=80, recommendation='high_priority', algorithm_version='matching_v2')
            identifier = database.save_evaluation(vacancy, profile, result)
            reordered = CandidateProfile(skills=['Python'], conditions={'on_call': None, 'travel': False})
            restarted = ApplicationDatabase(path)
            self.assertEqual(restarted.save_evaluation(vacancy, reordered, result), identifier)
            evaluations = restarted.list_evaluations(vacancy)
            self.assertEqual(len(evaluations), 1)
            saved = evaluations[0]
            self.assertEqual(saved['id'], identifier)
            self.assertEqual(saved['algorithm_version'], 'matching_v2')
            self.assertEqual(saved['evaluation'], result.to_dict())
            self.assertEqual(saved['job_snapshot'], asdict(job))
            self.assertEqual(saved['profile_snapshot'], profile.to_dict())
            self.assertRegex(saved['profile_fingerprint'], r'^[0-9a-f]{64}$')
            self.assertRegex(saved['input_fingerprint'], r'^[0-9a-f]{64}$')
            self.assertEqual(restarted.list_evaluations(999), [])

    def test_evaluation_snapshot_does_not_change_when_vacancy_or_profile_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            database = ApplicationDatabase(Path(directory) / 'test.sqlite3')
            job = normalized_job()
            vacancy = database.upsert_vacancy(job)
            profile = CandidateProfile(skills=['Python'])
            result = EvaluationResult(score=80, recommendation='high_priority', algorithm_version='matching_v2')
            first = database.save_evaluation(vacancy, profile, result)
            original = database.list_evaluations(vacancy)[0]
            profile.skills.append('Linux')
            database.upsert_vacancy(normalized_job(description='New text'))
            second = database.save_evaluation(vacancy, profile, result)
            self.assertNotEqual(first, second)
            self.assertEqual(database.list_evaluations(vacancy)[0], original)
            self.assertEqual(original['profile_snapshot']['skills'], ['Python'])
            self.assertEqual(original['job_snapshot']['description'], 'Synthetic Python role')

    def test_changed_algorithm_or_profile_creates_separate_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = ApplicationDatabase(Path(directory) / 'test.sqlite3')
            vacancy = database.upsert_vacancy(normalized_job())
            profile = CandidateProfile(skills=['Python'])
            result = EvaluationResult(score=80, recommendation='high_priority', algorithm_version='matching_v2')
            first = database.save_evaluation(vacancy, profile, result)
            second = database.save_evaluation(vacancy, profile, replace(result, algorithm_version='matching_v3'))
            third = database.save_evaluation(vacancy, CandidateProfile(skills=['Linux']), result)
            self.assertEqual(len({first, second, third}), 3)

    def test_conflicting_result_for_same_inputs_and_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = ApplicationDatabase(Path(directory) / 'test.sqlite3')
            vacancy = database.upsert_vacancy(normalized_job())
            profile = CandidateProfile()
            result = EvaluationResult(score=80, recommendation='high_priority', algorithm_version='matching_v2')
            database.save_evaluation(vacancy, profile, result)
            with self.assertRaises(ValueError):
                database.save_evaluation(vacancy, profile, replace(result, score=81))
            self.assertEqual(database.list_evaluations(vacancy)[0]['evaluation']['score'], 80)

    def test_evaluated_job_snapshot_is_used_even_if_vacancy_was_updated(self):
        with tempfile.TemporaryDirectory() as directory:
            database = ApplicationDatabase(Path(directory) / 'test.sqlite3')
            original = normalized_job()
            vacancy = database.upsert_vacancy(original)
            database.upsert_vacancy(normalized_job(description='Concurrent update'))
            profile = CandidateProfile()
            result = EvaluationResult(score=80, recommendation='high_priority', algorithm_version='matching_v2')
            database.save_evaluation(vacancy, profile, result, job=original)
            self.assertEqual(database.list_evaluations(vacancy)[0]['job_snapshot'], asdict(original))
            self.assertEqual(database.get_vacancy(vacancy).description, 'Concurrent update')
            with self.assertRaises(ValueError):
                database.save_evaluation(vacancy, profile, result,
                                         job=normalized_job(source_board='unrelated'))
            with self.assertRaises(ValueError):
                database.save_evaluation(999, profile, result)

    def test_two_writers_share_one_vacancy_and_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            ApplicationDatabase(path)
            barrier = threading.Barrier(2)

            def write(_):
                database = ApplicationDatabase(path)
                barrier.wait(timeout=10)
                vacancy = database.upsert_vacancy(normalized_job())
                evaluation = database.save_evaluation(
                    vacancy, CandidateProfile(),
                    EvaluationResult(score=80, recommendation='high_priority', algorithm_version='matching_v2'),
                )
                return vacancy, evaluation

            with ThreadPoolExecutor(max_workers=2) as executor:
                identifiers = list(executor.map(write, range(2)))
            self.assertEqual(identifiers, [(1, 1), (1, 1)])
            self.assertEqual(len(ApplicationDatabase(path).list_vacancies()), 1)
            self.assertEqual(len(ApplicationDatabase(path).list_evaluations(1)), 1)

    def test_two_processes_share_one_vacancy_and_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            job = normalized_job()
            script = '''
import json
import sys
from pathlib import Path
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.models import CandidateProfile, EvaluationResult
from jobsearch_assistant.sources.models import NormalizedJob
if sys.stdin.readline().strip() != 'go':
    raise SystemExit(2)
database = ApplicationDatabase(Path(sys.argv[1]))
job = NormalizedJob(**json.loads(sys.argv[2]))
vacancy = database.upsert_vacancy(job)
evaluation = database.save_evaluation(
    vacancy, CandidateProfile(),
    EvaluationResult(score=80, recommendation='high_priority', algorithm_version='matching_v2'),
    job=job,
)
print(json.dumps({'vacancy': vacancy, 'evaluation': evaluation}))
'''
            command = [sys.executable, '-c', script, str(path), json.dumps(asdict(job))]
            workers = []
            with ExitStack() as stack:
                try:
                    for _ in range(2):
                        workers.append(stack.enter_context(subprocess.Popen(
                            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                        )))
                    gate = threading.Barrier(2)

                    def release(worker):
                        gate.wait(timeout=10)
                        return worker.communicate(input='go\n', timeout=30)

                    with ThreadPoolExecutor(max_workers=2) as executor:
                        results = list(executor.map(release, workers))
                    for worker, (output, error) in zip(workers, results):
                        self.assertEqual(worker.returncode, 0, error)
                        self.assertEqual(json.loads(output), {'vacancy': 1, 'evaluation': 1})
                finally:
                    for worker in workers:
                        if worker.poll() is None:
                            worker.kill()
            database = ApplicationDatabase(path)
            self.assertEqual(database.list_vacancies(), [{'id': 1, 'job': asdict(job)}])
            evaluations = database.list_evaluations(1)
            self.assertEqual(len(evaluations), 1)
            self.assertEqual(evaluations[0]['job_snapshot'], asdict(job))
            self.assertEqual(evaluations[0]['profile_snapshot'], CandidateProfile().to_dict())


if __name__ == '__main__':
    unittest.main()
