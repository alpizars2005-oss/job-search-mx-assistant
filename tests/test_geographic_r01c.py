"""R-01c: explicit hiring restrictions, contextual controls and immutable history."""
import hashlib
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.automation_store import AutomationStore
from jobsearch_assistant.daily_reports import DailyReports
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.eligibility import evaluate_eligibility
from jobsearch_assistant.matching import evaluate_match
from jobsearch_assistant.models import CandidateProfile, EvaluationResult, JobPosting
from jobsearch_assistant.sources.models import NormalizedJob
from jobsearch_assistant.workflow_contracts import content_digest, vacancy_digest


class GeographicR01cTests(unittest.TestCase):
    permission = 'We can hire candidates residing in Mexico. '

    def setUp(self):
        self.profile = CandidateProfile(skills=['python', 'git', 'linux'],
            target_roles=['Python Developer'], experience_years=1, degree_completed=False,
            residence_country='MX', work_authorized_countries=['MX'],
            language_levels={'English': 'B2', 'Spanish': 'native'})

    def job(self, kind, phrase='', location='Remote', permission=True):
        description = ((self.permission if permission else '') + phrase + ' Junior role. '
            'Python, Git and Linux. 0-2 years of experience. English required. '
            'Salary: 25,000 MXN per month.')
        if kind is JobPosting:
            return JobPosting(title='Junior Python Developer', company='Synthetic',
                              location=location, description=description)
        return NormalizedJob(source='ashby', source_board='synthetic', source_job_id='r01c',
            company='Synthetic', title='Junior Python Developer', locations=[location],
            work_mode='remote', url=None, description=description, published_at=None,
            retrieved_at='2026-11-05T19:00:00Z', verification_status='listed',
            eligibility_evidence={}, provenance={'locations': ['location'],
                                                'description': ['descriptionPlain']})

    def geography(self, job):
        return next(item for item in evaluate_eligibility(self.profile, job)
                    if item['name'] == 'mexico_hiring')

    def test_eight_reported_restrictions_never_receive_priority(self):
        for phrase, location in (
            ('Open to candidates in Canada only.', 'Remote'),
            ('Position restricted to US residents.', 'Remote'),
            ('This is a US-only role.', 'Remote'),
            ('We only hire in the United States.', 'Remote'),
            ('Applicants outside the US will not be considered.', 'Remote'),
            ('Solo para residentes de Estados Unidos.', 'Remote'),
            ('', 'Remoto (solo EE. UU.)'),
            ('', 'Remote - EU only'),
        ):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(phrase=phrase, location=location,
                                      kind=kind.__name__, permission=permission):
                        job = self.job(kind, phrase, location, permission)
                        requirement = self.geography(job)
                        self.assertEqual(requirement['status'], 'contradictory' if permission else 'unmet')
                        result = evaluate_match(self.profile, job)
                        self.assertEqual(result.recommendation,
                                         'insufficient_information' if permission else 'ineligible')
                        self.assertNotIn(result.recommendation, ('high_priority', 'medium_priority'))
                        self.assertNotIn('mexico_hiring_confirmed', result.positive_signals)
                        evidence = requirement['evidence']
                        fields = {'description': job.description,
                                  'location' if kind is JobPosting else 'locations[0]': location}
                        negative_field = 'description' if phrase else (
                            'location' if kind is JobPosting else 'locations[0]')
                        self.assertTrue(any(fact['field'] == negative_field for fact in evidence))
                        if permission:
                            self.assertTrue(any(self.permission.strip() in fact['span'] for fact in evidence))
                        for fact in evidence:
                            self.assertEqual(fields[fact['field']][fact['start']:fact['end']], fact['span'])
                            if kind is NormalizedJob:
                                self.assertEqual(fact['provenance'], ['descriptionPlain']
                                                 if fact['field'] == 'description' else ['location'])

    def test_reported_location_controls_keep_priority_only_with_mexico_permission(self):
        for location in ('Remote', 'Remote - Mexico', 'Remote (US or Mexico)',
                         'Remote (US, Mexico)', 'Remote - LATAM', 'Remote - Americas',
                         'Remote - North America', 'Mexico City, Mexico (Remote)'):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(location=location, kind=kind.__name__, permission=permission):
                        job = self.job(kind, location=location, permission=permission)
                        self.assertEqual(self.geography(job)['status'], 'met' if permission else 'unknown')
                        self.assertEqual(evaluate_match(self.profile, job).recommendation,
                                         'high_priority' if permission else 'insufficient_information')

    def test_reported_incidental_and_negated_controls_keep_priority(self):
        for phrase in ('We work with US customers.', 'US holidays are observed.',
                       'Benefits for US employees include 401k.',
                       'Headquarters: San Francisco, United States.',
                       'Experience with US healthcare regulations (HIPAA) is a plus.',
                       'Not limited to US residents.', 'US residency is not required.',
                       'Not only US residents; we hire across the Americas.',
                       'You will collaborate with our US only on-call team.'):
            for kind in (JobPosting, NormalizedJob):
                with self.subTest(phrase=phrase, kind=kind.__name__):
                    job = self.job(kind, phrase)
                    self.assertEqual(self.geography(job)['status'], 'met')
                    self.assertEqual(evaluate_match(self.profile, job).recommendation, 'high_priority')

    def test_new_grammar_preserves_negation_role_scope_and_mexico_exceptions(self):
        for phrase in ('This is not a US-only role.',
                       'We do not only hire in the United States.',
                       'Applicants outside the US will not be considered for other roles.',
                       'Solo para residentes de Estados Unidos para otro puesto.',
                       'For sales roles, we only hire in the United States.',
                       'Position examples from other teams are restricted to US residents.',
                       'Benefits for a US-only role include 401k.',
                       'Our customer has a US-only role.',
                       'We only hire in the United States, or Mexico.',
                       'Open to candidates in Canada only, except applicants from Mexico.',
                       'Position restricted to US residents, or Mexico.',
                       'This is a US-only role, except applicants from Mexico.',
                       'Not open to candidates in Canada only.',
                       'We collaborate with colleagues in Europe and the European Union.'):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(phrase=phrase, kind=kind.__name__, permission=permission):
                        job = self.job(kind, phrase, permission=permission)
                        self.assertEqual(self.geography(job)['status'], 'met' if permission else 'unknown')
                        self.assertEqual(evaluate_match(self.profile, job).recommendation,
                                         'high_priority' if permission else 'insufficient_information')

    def test_conditional_new_hiring_predicates_remain_unknown(self):
        for phrase in ('We may only hire in the United States.',
                       'This might be a US-only role.',
                       'Open to candidates in Canada only if approved.'):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(phrase=phrase, kind=kind.__name__, permission=permission):
                        job = self.job(kind, phrase, permission=permission)
                        requirement = self.geography(job)
                        self.assertEqual(requirement['status'], 'unknown')
                        self.assertTrue(any(phrase in fact['span'] for fact in requirement['evidence']))
                        self.assertEqual(evaluate_match(self.profile, job).recommendation,
                                         'insufficient_information')

    def test_v7_cache_is_refreshed_once_and_history_hashes_and_reports_survive(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'DRY_RUN': 'true', 'AUTO_SUBMIT': 'false'}), patch(
                    'urllib.request.OpenerDirector.open', side_effect=AssertionError('No network')):
            home = Path(directory)
            database = ApplicationDatabase(home / 'applications.sqlite3')
            job = self.job(NormalizedJob, 'Open to candidates in Canada only.')
            vacancy = database.upsert_vacancy(job)
            versions = ['legacy_v1', *[f'matching_v{number}' for number in range(2, 8)]]
            previous = {}
            for version in versions:
                previous[version] = database.save_evaluation(vacancy, self.profile,
                    EvaluationResult(95, 'high_priority', algorithm_version=version), job=job)
            with database._connection() as connection:
                history = [tuple(row) for row in connection.execute('SELECT * FROM evaluations ORDER BY id')]
                connection.execute('INSERT INTO automation_observations VALUES (?,?,?,?,?)',
                    (vacancy, vacancy_digest(job), content_digest(self.profile.to_dict()),
                     'matching_v7', previous['matching_v7']))
            # Inventory every stored field; compare the raw JSON bytes separately.
            snapshots = [tuple(value.encode('utf-8') for value in row[5:]) for row in history]
            snapshot_hashes = [tuple(hashlib.sha256(value).hexdigest() for value in row) for row in snapshots]
            before_bytes = repr(history).encode('utf-8')
            before_hash = hashlib.sha256(before_bytes).hexdigest()
            store = AutomationStore(database)
            with patch('jobsearch_assistant.automation_store.timestamp', return_value='2026-11-05T19:00:00Z'), \
                    patch('jobsearch_assistant.automation_store.ALGORITHM_VERSION', 'matching_v7'):
                run = store.start('synthetic', 'synthetic')
                old = store.observe(run, job, self.profile)
                store.finish(run, 'success', [])
            self.assertEqual(old['evaluation_id'], previous['matching_v7'])
            reports = DailyReports(home, now=lambda: datetime.fromisoformat('2026-11-05T20:00:00+00:00'))
            reports.generate(start_date='2026-11-05')
            published = {p.name: p.read_bytes() for p in (home / 'reports/2026-11-05').iterdir()}
            old_report = reports.read('2026-11-05')['evaluations'][0]
            self.assertEqual(old_report['algorithm_version'], 'matching_v7')
            self.assertEqual(old_report['evaluation_id'], previous['matching_v7'])
            with patch('jobsearch_assistant.automation_store.timestamp', return_value='2026-11-06T19:00:00Z'):
                run = store.start('synthetic', 'synthetic')
                current = store.observe(run, job, self.profile)
                store.finish(run, 'success', [])
            self.assertEqual(current['change'], 'reevaluated')
            self.assertEqual(current['classification'], 'insufficient_information')
            restarted = AutomationStore(ApplicationDatabase(home / 'applications.sqlite3'))
            with patch('jobsearch_assistant.automation_store.timestamp', return_value='2026-11-06T19:01:00Z'):
                run = restarted.start('synthetic', 'synthetic')
                repeated = restarted.observe(run, job, self.profile)
                restarted.finish(run, 'success', [])
            self.assertEqual(repeated['change'], 'unchanged')
            self.assertEqual(repeated['evaluation_id'], current['evaluation_id'])
            with database._connection() as connection:
                after = [tuple(row) for row in connection.execute('''SELECT * FROM evaluations
                    WHERE algorithm_version != 'matching_v8' ORDER BY id''')]
            after_bytes = repr(after).encode('utf-8')
            kept_snapshots = [tuple(value.encode('utf-8') for value in row[5:]) for row in after]
            self.assertEqual(kept_snapshots, snapshots)
            self.assertEqual([tuple(hashlib.sha256(value).hexdigest() for value in row)
                              for row in kept_snapshots], snapshot_hashes)
            self.assertEqual(after_bytes, before_bytes)
            self.assertEqual(hashlib.sha256(after_bytes).hexdigest(), before_hash)
            evaluations = database.list_evaluations(vacancy)
            self.assertEqual(len(evaluations), 8)
            self.assertEqual(len(database.list_vacancies()), 1)
            self.assertEqual(next(item for item in evaluations if item['id'] == current['evaluation_id'])
                             ['algorithm_version'], 'matching_v8')
            reports = DailyReports(home, now=lambda: datetime.fromisoformat('2026-11-06T20:00:00+00:00'))
            reports.generate(start_date='2026-11-05')
            self.assertEqual(published, {p.name: p.read_bytes() for p in (home / 'reports/2026-11-05').iterdir()})
            new_report = reports.read('2026-11-06')['evaluations'][0]
            self.assertEqual(new_report['algorithm_version'], 'matching_v8')
            self.assertEqual(new_report['evaluation_id'], current['evaluation_id'])
            self.assertEqual(new_report['classification'], 'insufficient_information')


if __name__ == '__main__':
    unittest.main()
