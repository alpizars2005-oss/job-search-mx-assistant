"""R-01: whole location labels must constrain eligibility without widening prose rules."""
import unittest
import tempfile
from pathlib import Path

from jobsearch_assistant.eligibility import evaluate_eligibility
from jobsearch_assistant.matching import evaluate_match
from jobsearch_assistant.models import CandidateProfile, JobPosting
from jobsearch_assistant.sources.models import NormalizedJob


class GeographicLocationTests(unittest.TestCase):
    def setUp(self):
        self.profile = CandidateProfile(skills=['python', 'git', 'linux'],
            target_roles=['python developer'], preferred_locations=['Mexico'],
            residence_country='MX', experience_years=1)
        self.permission = 'We can hire candidates residing in Mexico. '

    def job(self, kind, locations, permission=True, extra=''):
        description = ('Remote junior Python developer using Python, Git and Linux. '
                       'English required. Requires 1 year of experience. '
                       + (self.permission if permission else '') + extra)
        if kind is JobPosting:
            return JobPosting(title='Junior Python Developer', company='Synthetic',
                              location='; '.join(locations), description=description)
        return NormalizedJob(source='ashby', source_board='synthetic', source_job_id='r01',
            company='Synthetic', title='Junior Python Developer', locations=locations,
            work_mode='remote', url=None, description=description, published_at=None,
            retrieved_at='2026-11-05T12:00:00Z', verification_status='listed',
            eligibility_evidence={}, provenance={'locations': ['location', 'secondaryLocations'],
                                                'description': ['descriptionPlain']})

    def requirement(self, job):
        return next(item for item in evaluate_eligibility(self.profile, job)
                    if item['name'] == 'mexico_hiring')

    def test_exclusive_us_labels_never_unlock_priority_and_retain_evidence(self):
        for label in ('Remote (US only)', 'Remote - US only',
                      'Remote (United States only)', 'Remote (USA only)',
                      'Remote; US-based', 'Remote - US & Canada', 'United States'):
            for kind in (JobPosting, NormalizedJob):
                for permission, status, recommendation in (
                    (True, 'contradictory', 'insufficient_information'),
                    (False, 'unmet', 'ineligible')):
                    with self.subTest(label=label, kind=kind.__name__, permission=permission):
                        job = self.job(kind, [label], permission)
                        requirement = self.requirement(job)
                        self.assertEqual(requirement['status'], status)
                        result = evaluate_match(self.profile, job)
                        self.assertEqual(result.recommendation, recommendation)
                        self.assertNotIn(result.recommendation, ('high_priority', 'medium_priority'))
                        self.assertNotIn('mexico_hiring_confirmed', result.positive_signals)
                        facts = [fact for fact in requirement['evidence']
                                 if fact['field'].startswith('location')]
                        self.assertTrue(facts)
                        for fact in facts:
                            self.assertEqual(label[fact['start']:fact['end']], fact['span'])
                            if kind is NormalizedJob:
                                self.assertEqual(fact['provenance'], ['location', 'secondaryLocations'])
                        if permission:
                            self.assertTrue(any(self.permission.strip() in fact['span']
                                                for fact in requirement['evidence']))

    def test_mexico_alternatives_and_incidental_us_mentions_remain_eligible(self):
        for locations, extra in (
            (['Remote - Mexico'], ''),
            (['Remote'], ''),
            (['Remote'], 'Not only US residents may apply.'),
            (['Remote'], 'Our customers are in the United States.'),
            (['United States', 'Mexico'], ''),
            (['Remote - US', 'Remote - Mexico'], ''),
            (['Remote - US & Mexico'], ''),
        ):
            for kind in (JobPosting, NormalizedJob):
                with self.subTest(locations=locations, extra=extra, kind=kind.__name__):
                    job = self.job(kind, locations, extra=extra)
                    self.assertEqual(self.requirement(job)['status'], 'met')
                    self.assertEqual(evaluate_match(self.profile, job).recommendation, 'high_priority')

    def test_mexico_alternative_does_not_cancel_an_explicit_exclusive_restriction(self):
        for locations, extra in (
            (['Remote (US only)', 'Remote - Mexico'], ''),
            (['United States', 'Mexico'], 'US residents only.'),
            (['Remote - US', 'Remote - Mexico'], 'We cannot hire candidates residing in Mexico.'),
        ):
            for kind in (JobPosting, NormalizedJob):
                with self.subTest(locations=locations, extra=extra, kind=kind.__name__):
                    job = self.job(kind, locations, extra=extra)
                    self.assertEqual(self.requirement(job)['status'], 'contradictory')
                    self.assertEqual(evaluate_match(self.profile, job).recommendation,
                                     'insufficient_information')

    def test_v3_observation_is_reevaluated_without_rewriting_its_historical_snapshot(self):
        from jobsearch_assistant.automation_store import AutomationStore
        from jobsearch_assistant.database import ApplicationDatabase
        from jobsearch_assistant.models import EvaluationResult
        from jobsearch_assistant.workflow_contracts import content_digest, vacancy_digest
        with tempfile.TemporaryDirectory() as directory:
            database = ApplicationDatabase(Path(directory) / 'database.sqlite3')
            job = self.job(NormalizedJob, ['Remote (US only)'])
            vacancy = database.upsert_vacancy(job)
            previous = database.save_evaluation(vacancy, self.profile,
                EvaluationResult(95, 'high_priority', algorithm_version='matching_v3'), job=job)
            history = database.list_evaluations(vacancy)[0]
            with database._connection() as connection:
                connection.execute('INSERT INTO automation_observations VALUES (?,?,?,?,?)',
                    (vacancy, vacancy_digest(job), content_digest(self.profile.to_dict()),
                     'matching_v3', previous))
            store = AutomationStore(database)
            run = store.start('synthetic', content_digest(self.profile.to_dict()))
            current = store.observe(run, job, self.profile)
            store.finish(run, 'success', [])
            self.assertEqual(current['change'], 'reevaluated')
            self.assertNotEqual(current['evaluation_id'], previous)
            saved = {item['id']: item for item in database.list_evaluations(vacancy)}
            self.assertEqual(saved[previous], history)
            self.assertEqual(saved[current['evaluation_id']]['algorithm_version'], 'matching_v4')
            self.assertEqual(current['classification'], 'insufficient_information')


if __name__ == '__main__':
    unittest.main()
