"""R-01: whole location labels must constrain eligibility without widening prose rules."""
import unittest
import tempfile
from dataclasses import replace
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

    def audited_job(self, kind, location='Remote', clause='', permission=True):
        description = ((self.permission if permission else '')
            + 'Junior role. Python, Git and Linux. 0-2 years of experience. '
              'English required. Salary: 25,000 MXN per month. ' + clause)
        return replace(self.job(kind, [location]), description=description)

    def assert_geographic_exclusion(self, job, permission, negative_field):
        requirement = self.requirement(job)
        self.assertEqual(requirement['status'], 'contradictory' if permission else 'unmet')
        result = evaluate_match(self.profile, job)
        self.assertEqual(result.recommendation, 'insufficient_information' if permission else 'ineligible')
        self.assertNotIn(result.recommendation, ('high_priority', 'medium_priority'))
        self.assertNotIn('mexico_hiring_confirmed', result.positive_signals)
        self.assertTrue(any(fact['field'] == negative_field for fact in requirement['evidence']))
        if permission:
            self.assertTrue(any(self.permission.strip() in fact['span']
                                for fact in requirement['evidence']))
        fields = {'description': job.description}
        if isinstance(job, NormalizedJob):
            fields.update({f'locations[{index}]': value for index, value in enumerate(job.locations)})
        else:
            fields['location'] = job.location
        for fact in requirement['evidence']:
            self.assertEqual(fields[fact['field']][fact['start']:fact['end']], fact['span'])
            if isinstance(job, NormalizedJob):
                self.assertEqual(fact['provenance'], ['descriptionPlain'] if fact['field'] == 'description'
                                 else ['location', 'secondaryLocations'])

    def test_r01b_bare_country_only_is_a_vacancy_hiring_condition(self):
        for clause in ('This role is US only.', 'This position is US only.',
                       'Location: US only.', 'Eligibility: United States only.',
                       'Hiring in the US only.', 'This role is US only - EST hours.',
                       'This customer support role is US only.'):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(clause=clause, kind=kind.__name__, permission=permission):
                        self.assert_geographic_exclusion(
                            self.audited_job(kind, clause=clause, permission=permission),
                            permission, 'description')

    def test_r01b_explicit_exclusivity_survives_region_and_timezone_decoration(self):
        for location in ('Remote: North America (US only)', 'Remote (US Only - EST)',
                         'Remote (US Only - EST hours)',
                         'Remote: North America (US only; EST hours)'):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(location=location, kind=kind.__name__, permission=permission):
                        self.assert_geographic_exclusion(
                            self.audited_job(kind, location=location, permission=permission),
                            permission, 'location' if kind is JobPosting else 'locations[0]')

    def test_n03_common_ats_formats_and_exclusive_hiring_clause(self):
        for location, clause in (
            ('US Remote', ''), ('Remote | United States', ''), ('Remote — USA', ''),
            ('New York, NY or Remote (US)', ''), ('Remote - United States of America', ''),
            ('Remoto - Estados Unidos', ''),
            ('Remote', 'Only open to candidates in the United States.'),
        ):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(location=location, clause=clause,
                                      kind=kind.__name__, permission=permission):
                        self.assert_geographic_exclusion(
                            self.audited_job(kind, location=location, clause=clause, permission=permission),
                            permission, 'description' if clause else
                            'location' if kind is JobPosting else 'locations[0]')

    def test_country_mentions_in_other_predicates_do_not_exclude_this_vacancy(self):
        for clause in (
            'Our offices are in the US only.',
            'This role supports clients in the US only.',
            'Benefits are available in the US only.',
            'Working hours: US only.',
            'This role follows US only time zones.',
            'This role requires EST hours.',
            'US only benefits apply to US-based employees.',
            'This role is not US only.',
            'Not only US residents may apply.',
            'Other roles are US only.',
            'This position is US only for other roles.',
            'This role is US only except applicants from Mexico.',
            'This role is US only or open to candidates in Mexico.',
            'We use the tag US only for office expenses.',
            'Office location: US only.',
            'Only open to candidates in the United States for relocation benefits.',
            'Only open to candidates in the United States or Mexico.',
        ):
            for kind in (JobPosting, NormalizedJob):
                with self.subTest(clause=clause, kind=kind.__name__):
                    job = self.audited_job(kind, clause=clause)
                    self.assertEqual(self.requirement(job)['status'], 'met')
                    # An unparsed mandatory schedule still needs review under
                    # the existing contract; it is not a residence exclusion.
                    expected = ('insufficient_information' if clause == 'This role requires EST hours.'
                                else 'high_priority')
                    self.assertEqual(evaluate_match(self.profile, job).recommendation, expected)

    def test_remote_mexico_alternatives_and_timezones_are_not_exclusive(self):
        for location in ('Remote', 'Remote - Mexico', 'Remote - US or Mexico',
                         'Remote (US, Mexico)', 'Remote - LATAM',
                         'Remote - EST hours', 'Remote (US time zone)',
                         'Remote: North America (EST)', 'Remote (US only or Mexico)'):
            for kind in (JobPosting, NormalizedJob):
                with self.subTest(location=location, kind=kind.__name__):
                    job = self.audited_job(kind, location=location)
                    self.assertEqual(self.requirement(job)['status'], 'met')
                    self.assertEqual(evaluate_match(self.profile, job).recommendation, 'high_priority')

    def test_regions_and_timezones_without_hiring_permission_remain_unknown(self):
        for location in ('Remote', 'Remote - LATAM', 'Remote: North America (EST)',
                         'Remote (US time zone)', 'Remote - EST hours'):
            for kind in (JobPosting, NormalizedJob):
                with self.subTest(location=location, kind=kind.__name__):
                    job = self.audited_job(kind, location=location, permission=False)
                    self.assertEqual(self.requirement(job)['status'], 'unknown')
                    self.assertEqual(evaluate_match(self.profile, job).recommendation,
                                     'insufficient_information')

    def test_conditional_country_only_statements_require_review_instead_of_exclusion(self):
        for clause in ('This role may be US only.', 'Hiring might be US only.',
                       'This position could be United States only.',
                       'If this role is US only, eligibility needs clarification.'):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(clause=clause, kind=kind.__name__, permission=permission):
                        job = self.audited_job(kind, clause=clause, permission=permission)
                        requirement = self.requirement(job)
                        self.assertEqual(requirement['status'], 'unknown')
                        self.assertEqual(evaluate_match(self.profile, job).recommendation,
                                         'insufficient_information')
                        self.assertTrue(any(fact['field'] == 'description' and clause in fact['span']
                                            for fact in requirement['evidence']))

    def test_comma_separated_mexico_exceptions_preserve_the_alternative(self):
        for clause in ('This role is US only, except applicants from Mexico.',
                       'This role is US only, or open to candidates in Mexico.',
                       'Only open to candidates in the United States, or Mexico.'):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(clause=clause, kind=kind.__name__, permission=permission):
                        job = self.audited_job(kind, clause=clause, permission=permission)
                        self.assertEqual(self.requirement(job)['status'], 'met' if permission else 'unknown')
                        self.assertEqual(evaluate_match(self.profile, job).recommendation,
                                         'high_priority' if permission else 'insufficient_information')

    def test_postposed_conditions_do_not_become_confirmed_country_restrictions(self):
        for clause in ('This role is US only if tax approval is denied.',
                       'This role is US only, subject to eligibility clarification.',
                       'Only open to candidates in the United States if a contract changes.'):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(clause=clause, kind=kind.__name__, permission=permission):
                        job = self.audited_job(kind, clause=clause, permission=permission)
                        self.assertEqual(self.requirement(job)['status'], 'unknown')
                        self.assertEqual(evaluate_match(self.profile, job).recommendation,
                                         'insufficient_information')
                        self.assertTrue(any(clause in fact['span'] for fact in self.requirement(job)['evidence']))

    def test_role_word_alone_cannot_turn_a_different_predicate_into_residence(self):
        for clause in ('This role offers health insurance in the US only.',
                       'This role has US only working hours.',
                       'This role processes US only data.',
                       'This position uses US only equipment.'):
            for kind in (JobPosting, NormalizedJob):
                for permission in (True, False):
                    with self.subTest(clause=clause, kind=kind.__name__, permission=permission):
                        job = self.audited_job(kind, clause=clause, permission=permission)
                        self.assertEqual(self.requirement(job)['status'], 'met' if permission else 'unknown')
                        self.assertEqual(evaluate_match(self.profile, job).recommendation,
                                         'high_priority' if permission else 'insufficient_information')

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

    def test_multiple_country_bound_labels_in_one_field_keep_each_restriction(self):
        for label, expected_spans in (
            ('Remote - US; Remote - Canada', ['Remote - US;', 'Remote - Canada']),
            ('Remote - US\nRemote - Canada', ['Remote - US', 'Remote - Canada']),
            ('United States; Canada', ['United States;', 'Canada']),
        ):
            for kind in (JobPosting, NormalizedJob):
                with self.subTest(label=label, kind=kind.__name__):
                    job = self.job(kind, [label])
                    requirement = self.requirement(job)
                    self.assertEqual(requirement['status'], 'contradictory')
                    self.assertEqual(evaluate_match(self.profile, job).recommendation,
                                     'insufficient_information')
                    spans = [fact['span'] for fact in requirement['evidence']
                             if fact['field'].startswith('location')]
                    self.assertEqual(spans, expected_spans)

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
            self.assertEqual(saved[current['evaluation_id']]['algorithm_version'], 'matching_v6')
            self.assertEqual(current['classification'], 'insufficient_information')

    def test_v4_cache_is_reevaluated_once_and_all_older_snapshot_bytes_survive(self):
        from jobsearch_assistant.automation_store import AutomationStore
        from jobsearch_assistant.database import ApplicationDatabase
        from jobsearch_assistant.models import EvaluationResult
        from jobsearch_assistant.workflow_contracts import content_digest, vacancy_digest
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'database.sqlite3'
            database = ApplicationDatabase(path)
            job = self.audited_job(NormalizedJob, clause='This role is US only.')
            vacancy = database.upsert_vacancy(job)
            previous = {}
            for version in ('legacy_v1', 'matching_v2', 'matching_v3', 'matching_v4'):
                previous[version] = database.save_evaluation(vacancy, self.profile,
                    EvaluationResult(95, 'high_priority', algorithm_version=version), job=job)
            with database._connection() as connection:
                history = [tuple(row) for row in connection.execute('''SELECT id,algorithm_version,
                    job_snapshot_json,profile_snapshot_json,evaluation_json FROM evaluations ORDER BY id''')]
                connection.execute('INSERT INTO automation_observations VALUES (?,?,?,?,?)',
                    (vacancy, vacancy_digest(job), content_digest(self.profile.to_dict()),
                     'matching_v4', previous['matching_v4']))
            store = AutomationStore(database)
            run = store.start('synthetic', 'synthetic')
            current = store.observe(run, job, self.profile)
            store.finish(run, 'success', [])
            self.assertEqual(current['change'], 'reevaluated')
            self.assertEqual(current['classification'], 'insufficient_information')
            restarted = AutomationStore(ApplicationDatabase(path))
            run = restarted.start('synthetic', 'synthetic')
            repeated = restarted.observe(run, job, self.profile)
            restarted.finish(run, 'success', [])
            self.assertEqual(repeated['change'], 'unchanged')
            self.assertEqual(repeated['evaluation_id'], current['evaluation_id'])
            with database._connection() as connection:
                kept = [tuple(row) for row in connection.execute('''SELECT id,algorithm_version,
                    job_snapshot_json,profile_snapshot_json,evaluation_json FROM evaluations
                    WHERE algorithm_version != 'matching_v6' ORDER BY id''')]
            self.assertEqual(kept, history)
            evaluations = database.list_evaluations(vacancy)
            self.assertEqual(len(evaluations), 5)
            self.assertEqual(len(database.list_vacancies()), 1)
            new = next(item for item in evaluations if item['id'] == current['evaluation_id'])
            self.assertEqual(new['algorithm_version'], 'matching_v6')
            self.assertEqual(new['evaluation']['recommendation'], 'insufficient_information')

    def test_published_v5_candidate_cache_cannot_reuse_a_false_exclusion(self):
        from jobsearch_assistant.automation_store import AutomationStore
        from jobsearch_assistant.database import ApplicationDatabase
        from jobsearch_assistant.models import EvaluationResult
        from jobsearch_assistant.workflow_contracts import content_digest, vacancy_digest
        with tempfile.TemporaryDirectory() as directory:
            database = ApplicationDatabase(Path(directory) / 'database.sqlite3')
            job = self.audited_job(NormalizedJob,
                clause='This role offers health insurance in the US only.')
            vacancy = database.upsert_vacancy(job)
            previous = database.save_evaluation(vacancy, self.profile,
                EvaluationResult(87, 'insufficient_information', algorithm_version='matching_v5'), job=job)
            history = database.list_evaluations(vacancy)[0]
            with database._connection() as connection:
                connection.execute('INSERT INTO automation_observations VALUES (?,?,?,?,?)',
                    (vacancy, vacancy_digest(job), content_digest(self.profile.to_dict()),
                     'matching_v5', previous))
            store = AutomationStore(database)
            run = store.start('synthetic', 'synthetic')
            current = store.observe(run, job, self.profile)
            store.finish(run, 'success', [])
            self.assertEqual(current['change'], 'reevaluated')
            self.assertNotEqual(current['evaluation_id'], previous)
            self.assertEqual(current['classification'], 'high_priority')
            kept = next(item for item in database.list_evaluations(vacancy) if item['id'] == previous)
            self.assertEqual(kept, history)


if __name__ == '__main__':
    unittest.main()
