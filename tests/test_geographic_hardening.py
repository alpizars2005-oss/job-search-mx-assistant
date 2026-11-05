"""Synthetic regressions for vacancy-scoped geographic eligibility."""
import unittest

from jobsearch_assistant.eligibility import evaluate_eligibility
from jobsearch_assistant.matching import evaluate_match
from jobsearch_assistant.models import CandidateProfile, JobPosting
from jobsearch_assistant.sources.models import NormalizedJob


class GeographicHardeningTests(unittest.TestCase):
    def setUp(self):
        self.profile = CandidateProfile(
            skills=['python', 'linux', 'technical support'],
            target_roles=['technical support'], preferred_locations=['Mexico'],
            skill_aliases={'technical support': ['troubleshooting']})

    def job(self, description='', location='Remote - Mexico'):
        return JobPosting(title='Junior Technical Support', location=location,
                          description='English, Linux, Python and troubleshooting. ' + description)

    def geography(self, job):
        return next(item for item in evaluate_eligibility(self.profile, job)
                    if item['name'] == 'mexico_hiring')

    def test_six_audit_restrictions_exclude_even_with_high_compatibility(self):
        for text, location in (
            ('Open only to residents of the United States.', 'Remote - Mexico'),
            ('Only candidates located in the US will be considered.', 'Remote - Mexico'),
            ('US-based candidates only.', 'Remote - Mexico'),
            ('Applicants must reside in the United States.', 'Remote - Mexico'),
            ('Residencia exclusiva en Estados Unidos.', 'Remote - Mexico'),
            ('', 'Remote - United States'),
            ('', 'Remote, USA'),
        ):
            with self.subTest(text=text, location=location):
                job = self.job(text, location)
                self.assertEqual(self.geography(job)['status'], 'unmet')
                result = evaluate_match(self.profile, job)
                self.assertGreaterEqual(result.score, 80)
                self.assertEqual(result.recommendation, 'ineligible')
                self.assertIn('mexico_hiring', result.missing_requirements)

    def test_reviewed_country_first_and_spanish_resident_restrictions(self):
        for text in (
            'Open only to US residents.',
            'Only US residents may apply.',
            'Contratación exclusiva para residentes de Estados Unidos.',
        ):
            for permission, status, recommendation in (
                ('', 'unmet', 'ineligible'),
                ('We can hire candidates residing in Mexico. ', 'contradictory', 'insufficient_information'),
            ):
                with self.subTest(text=text, permission=bool(permission)):
                    job = self.job(permission + text)
                    requirement = self.geography(job)
                    self.assertEqual(requirement['status'], status)
                    result = evaluate_match(self.profile, job)
                    self.assertGreaterEqual(result.score, 80)
                    self.assertEqual(result.recommendation, recommendation)
                    self.assertNotIn('mexico_hiring_confirmed', result.positive_signals)

    def test_reviewed_phrasings_preserve_negation_and_vacancy_scope(self):
        for text in (
            'This role is not open only to US residents.',
            'Not only US residents may apply.',
            'No contratación exclusiva para residentes de Estados Unidos.',
            'Our US office is open only to US residents.',
            'Sales roles are open only to US residents.',
            'For sales roles, only US residents may apply.',
            'Only US residents may apply for other roles.',
            'Contratación exclusiva para residentes de Estados Unidos para otros puestos.',
        ):
            with self.subTest(text=text):
                job = self.job('We can hire candidates residing in Mexico. ' + text)
                self.assertEqual(self.geography(job)['status'], 'met')
                self.assertEqual(evaluate_match(self.profile, job).recommendation, 'high_priority')

    def test_same_vacancy_permission_and_restriction_are_contradictory(self):
        permission = 'We can hire candidates residing in Mexico. '
        for text, location in (
            ('Open only to residents of the United States.', 'Remote - Mexico'),
            ('Only candidates located in the US will be considered.', 'Remote - Mexico'),
            ('US-based candidates only.', 'Remote - Mexico'),
            ('Applicants must reside in the United States.', 'Remote - Mexico'),
            ('Residencia exclusiva en Estados Unidos.', 'Remote - Mexico'),
            ('This technical support role is US-based.', 'Remote - Mexico'),
            ('', 'Remote - United States'),
            ('', 'Remote, USA'),
        ):
            with self.subTest(text=text, location=location):
                job = self.job(permission + text, location)
                requirement = self.geography(job)
                self.assertEqual(requirement['status'], 'contradictory')
                self.assertEqual(requirement['reason_code'], 'conflicting_hiring_restrictions')
                result = evaluate_match(self.profile, job)
                self.assertEqual(result.recommendation, 'insufficient_information')
                self.assertIn('mexico_hiring', result.unknowns)
                self.assertNotIn('mexico_hiring', result.requirements_met)
                self.assertNotIn('mexico_hiring_confirmed', result.positive_signals)

    def test_conflicting_clauses_in_the_same_sentence_remain_unknown(self):
        for text in (
            'We can hire candidates residing in Mexico, but this role is not available to candidates based in Mexico.',
            'We can hire candidates residing in Mexico, but we cannot hire candidates residing in Mexico.',
        ):
            with self.subTest(text=text):
                job = self.job(text)
                self.assertEqual(self.geography(job)['status'], 'contradictory')
                self.assertEqual(evaluate_match(self.profile, job).recommendation, 'insufficient_information')

    def test_permission_for_another_role_cannot_enable_this_vacancy(self):
        for text in (
            'While we can hire candidates residing in Mexico for sales roles, this engineering role is US-based.',
            'We can hire candidates residing in Mexico for other roles. US-based candidates only.',
            'For sales roles, we can hire candidates residing in Mexico. This technical support role is US-based.',
            'Podemos contratar candidatos que residen en México para puestos de ventas. Residencia exclusiva en Estados Unidos.',
        ):
            with self.subTest(text=text):
                job = self.job(text)
                self.assertEqual(self.geography(job)['status'], 'unmet')
                self.assertEqual(evaluate_match(self.profile, job).recommendation, 'ineligible')
        for text in (
            'We can hire candidates residing in Mexico for sales roles.',
            'We can hire candidates residing in Mexico for all sales roles.',
            'We can hire candidates residing in Mexico for all other roles.',
            'We can hire candidates residing in Mexico for this other role.',
            'We can hire candidates residing in Mexico for sales.',
            'We can hire candidates residing in Mexico for other opportunities.',
            'For other positions, we can hire candidates residing in Mexico.',
            'For sales, we can hire candidates residing in Mexico.',
            'Podemos contratar candidatos que residen en México para puestos de ventas.',
        ):
            with self.subTest(text=text):
                job = self.job(text)
                self.assertEqual(self.geography(job)['status'], 'unknown')
                self.assertEqual(evaluate_match(self.profile, job).recommendation, 'insufficient_information')

    def test_incidental_us_mentions_and_negated_restrictions_preserve_valid_permission(self):
        for text in (
            'We have US offices only.',
            'We support US-based clients only.',
            'Our company is US-based.',
            'Our US office is open only to residents of the United States.',
            'The client must reside in the US.',
            'Only candidates located in the US are eligible for travel reimbursement.',
            'US residents only need to submit a W-9.',
            'Open only to residents of the United States or Mexico.',
            'US-based candidates only except applicants from Mexico.',
            'Sales roles are open only to residents of the United States.',
            'For our US office, only US-based employees attend the event.',
            'This role is not restricted to residents of the United States.',
            'This role is not limited to US residents.',
            'Not only US residents may apply.',
            'Not only US-based candidates will be considered.',
            'No residencia exclusiva en Estados Unidos.',
            'No se limita a residentes de Estados Unidos.',
            'US residence is not required.',
            'Applicants do not have to reside in the US.',
            'Only US-based candidates are not required.',
            'Only candidates located in the US will not be considered.',
            'We are not unable to hire candidates residing in Mexico.',
            'We cannot hire sales candidates in Mexico, but we can hire candidates residing in Mexico for this role.',
        ):
            with self.subTest(text=text):
                job = self.job('We can hire candidates residing in Mexico. ' + text)
                self.assertEqual(self.geography(job)['status'], 'met')
                self.assertEqual(evaluate_match(self.profile, job).recommendation, 'high_priority')

    def test_general_regions_alone_do_not_confirm_permission(self):
        for location in ('Remote', 'Global', 'Americas', 'LATAM', 'Mexico', 'Remote - Mexico'):
            with self.subTest(location=location):
                job = self.job(location=location)
                self.assertEqual(self.geography(job)['status'], 'unknown')
                self.assertEqual(evaluate_match(self.profile, job).recommendation, 'insufficient_information')

    def test_explicit_permission_for_this_role_and_non_us_restrictions(self):
        for text in (
            'We can hire candidates residing in Mexico for this role.',
            'We can hire candidates residing in Mexico for all roles.',
            'For this role, we can hire candidates residing in Mexico.',
            'This role is open to applicants based in Mexico.',
            'Podemos contratar candidatos que residen en México para esta vacante.',
        ):
            with self.subTest(text=text):
                self.assertEqual(evaluate_match(self.profile, self.job(text)).recommendation, 'high_priority')
        for text in ('Open only to residents of Canada.',
                     'Only applicants based in Germany will be considered.',
                     'Residencia exclusiva en Canadá.'):
            with self.subTest(text=text):
                self.assertEqual(evaluate_match(self.profile, self.job(text)).recommendation, 'ineligible')

    def test_restriction_evidence_retains_original_span_offsets_and_ats_provenance(self):
        description = 'Python. Sólo candidatos residentes en Estados Unidos.'
        job = NormalizedJob(
            source='lever', source_board='synthetic', source_job_id='geography-1',
            company='Synthetic', title='Junior Technical Support',
            locations=['Remote, USA'], work_mode='remote', url=None,
            description=description, published_at=None, retrieved_at='2026-01-01T00:00:00Z',
            verification_status='listed', eligibility_evidence={'mexico': True},
            provenance={'description': ['descriptionPlain'], 'locations': ['categories.location']})
        requirement = self.geography(job)
        self.assertEqual(requirement['status'], 'unmet')
        fields = {'description': description, 'locations[0]': job.locations[0]}
        self.assertEqual({fact['field'] for fact in requirement['evidence']}, set(fields))
        for fact in requirement['evidence']:
            self.assertEqual(fields[fact['field']][fact['start']:fact['end']], fact['span'])
            expected = ['descriptionPlain'] if fact['field'] == 'description' else ['categories.location']
            self.assertEqual(fact['provenance'], expected)


if __name__ == '__main__':
    unittest.main()
