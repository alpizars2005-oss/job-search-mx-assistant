import unittest

from jobsearch_assistant.eligibility import evaluate_eligibility
from jobsearch_assistant.models import CandidateProfile, JobPosting
from jobsearch_assistant.sources.models import NormalizedJob


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.profile = CandidateProfile(skills=['python'], experience_years=1,
                                        degree_completed=False)

    def requirement(self, description='', name='mexico_hiring', **job_fields):
        job_fields.setdefault('title', 'Junior Python Developer')
        job_fields.setdefault('location', 'Remote')
        job = JobPosting(description=description, **job_fields)
        return {item['name']: item for item in evaluate_eligibility(self.profile, job)}[name]

    def test_generic_regions_and_candidate_authorization_do_not_grant_employer_permission(self):
        self.profile.residence_country = 'MX'
        self.profile.work_authorized_countries = ['MX']
        for location in ('Remote - Mexico', 'Global', 'Americas', 'LATAM', 'Worldwide'):
            with self.subTest(location=location):
                self.assertEqual(self.requirement(location=location)['status'], 'unknown')

    def test_explicit_bilingual_mexico_authorization_and_actual_evidence(self):
        for sentence in ('We can hire candidates residing in Mexico.',
                         'Podemos contratar candidatos que residen en México.',
                         'This role is open to applicants based in Mexico.'):
            with self.subTest(sentence=sentence):
                result = self.requirement(sentence)
                self.assertEqual(result['status'], 'met')
                self.assertTrue(result['required'])
                evidence = result['evidence'][0]
                self.assertEqual(evidence['field'], 'description')
                self.assertEqual(sentence[evidence['start']:evidence['end']], evidence['span'])

    def test_us_only_negation_and_contradictory_authorization(self):
        for description, expected in (
            ('US residents only.', 'unmet'),
            ('Solo residentes de Estados Unidos.', 'unmet'),
            ('This role is not restricted to US residents.', 'unknown'),
            ('No se limita a residentes de Estados Unidos.', 'unknown'),
            ('We cannot hire candidates residing in Mexico.', 'unmet'),
            ('We can hire candidates residing in Mexico. US residents only.', 'contradictory'),
        ):
            with self.subTest(description=description):
                self.assertEqual(self.requirement(description)['status'], expected)

    def test_remote_negations_hybrid_and_conflicting_sources(self):
        for location, description, status in (
            ('', 'This position is not remote.', 'unmet'),
            ('Presencial', '', 'unmet'),
            ('Hybrid remote', '', 'unmet'),
            ('', 'Trabajo remoto.', 'met'),
            ('Remote', 'On-site attendance is required.', 'contradictory'),
            ('', 'Remote work may be available.', 'unknown'),
            ('', 'No es un puesto remoto.', 'unmet'),
            ('', 'This is not an on-site position.', 'unknown'),
        ):
            with self.subTest(location=location, description=description):
                self.assertEqual(self.requirement(description, 'remote_work', location=location)['status'], status)

    def test_negation_stays_with_its_own_predicate(self):
        for description in ('No degree required and fully remote.',
                            'This role is not only remote but flexible.',
                            'No travel required; remote position.'):
            with self.subTest(description=description):
                self.assertEqual(self.requirement(description, 'remote_work', location='')['status'], 'met')
        for description in ('Degree not required and English required.',
                            'No degree required and English required.'):
            with self.subTest(description=description):
                self.assertEqual(self.requirement(description, 'language_english')['status'], 'met')

    def test_conditional_permission_is_not_confirmed_authorization(self):
        for description in ('We can hire candidates residing in Mexico if local payroll is approved.',
                            'Podemos contratar candidatos en México sujeto a aprobación.'):
            with self.subTest(description=description):
                self.assertEqual(self.requirement(description)['status'], 'unknown')
        for description in ('No contratamos candidatos residentes en México.',
                            'Hiring is not permitted in Mexico.',
                            'Applicants must be US residents.',
                            'Solo contratamos residentes de Estados Unidos.'):
            with self.subTest(description=description):
                self.assertEqual(self.requirement(description)['status'], 'unmet')

    def test_required_and_preferred_experience_in_same_sentence_stay_separate(self):
        for description in ('2 years of experience required and 5 years preferred.',
                            '2 años de experiencia obligatorios, 5 años deseables.'):
            with self.subTest(description=description):
                result = self.requirement(description, 'experience')
                self.assertEqual(result['status'], 'unmet')
                self.assertEqual(result['minimum_years'], 2)

    def test_both_degree_alternative_routes_confirmed_missing_are_unmet(self):
        self.profile.conditions['equivalent_experience'] = False
        result = self.requirement('Degree or equivalent experience required.', 'completed_degree')
        self.assertEqual(result['status'], 'unmet')

    def test_non_mexico_only_residence_is_an_explicit_exclusion(self):
        for description in ('Canada residents only.', 'Applicants must reside in Canada.',
                            'Solo residentes de Canadá.'):
            with self.subTest(description=description):
                self.assertEqual(self.requirement(description)['status'], 'unmet')

    def test_candidate_work_authorization_is_a_distinct_requirement(self):
        description = 'Must be authorized to work in Mexico.'
        result = self.requirement(description, 'work_authorization_mx')
        self.assertEqual(result['status'], 'unknown')
        self.profile.work_authorized_countries = ['MX']
        self.assertEqual(self.requirement(description, 'work_authorization_mx')['status'], 'met')
        self.assertEqual(self.requirement(description)['status'], 'unknown')
        self.profile.work_authorized_countries = []
        self.assertEqual(self.requirement(description, 'work_authorization_mx')['status'], 'unmet')

    def test_student_friendly_education_does_not_require_completed_degree(self):
        for description in ('Currently pursuing a degree required.',
                            'Estudiante de ingeniería / carrera en curso.',
                            "Bachelor's degree in progress accepted."):
            with self.subTest(description=description):
                self.assertEqual(self.requirement(description, 'completed_degree')['status'], 'not_required')

    def test_remote_preference_can_be_disabled(self):
        self.profile.remote_only = False
        result = self.requirement('', 'remote_work', location='On-site')
        self.assertFalse(result['required'])
        self.assertEqual(result['status'], 'not_required')

    def test_required_years_use_declared_experience_and_preferred_years_are_optional(self):
        self.assertEqual(self.requirement('Requires 3 years of experience.', 'experience')['status'], 'unmet')
        self.profile.experience_years = None
        self.assertEqual(self.requirement('Requires 3 years of experience.', 'experience')['status'], 'unknown')
        self.profile.experience_years = 3
        self.assertEqual(self.requirement('Requires 3 years of experience.', 'experience')['status'], 'met')
        self.profile.experience_years = 0
        preferred = self.requirement('Preferably 5 years of experience.', 'preferred_experience')
        self.assertFalse(preferred['required'])
        self.assertEqual(self.requirement('Preferably 5 years of experience.', 'experience')['status'], 'not_required')
        self.assertEqual(self.requirement('No experience required.', 'experience')['status'], 'not_required')

    def test_degree_requirement_alternative_and_negation(self):
        for description, status in (
            ("Bachelor's degree required.", 'unmet'),
            ('Título universitario terminado obligatorio.', 'unmet'),
            ('No degree required.', 'not_required'),
            ('No se requiere título universitario.', 'not_required'),
            ("Bachelor's degree or equivalent experience required.", 'unknown'),
        ):
            with self.subTest(description=description):
                self.assertEqual(self.requirement(description, 'completed_degree')['status'], status)
        self.profile.degree_completed = None
        self.assertEqual(self.requirement('Completed degree required.', 'completed_degree')['status'], 'unknown')
        self.profile.conditions['equivalent_experience'] = True
        self.assertEqual(self.requirement('Degree or equivalent experience required.', 'completed_degree')['status'], 'met')

    def test_explicit_seniority_excludes_and_management_mentions_do_not(self):
        self.assertEqual(self.requirement('', 'seniority', title='Senior Python Developer')['status'], 'unmet')
        self.assertEqual(self.requirement('Reports to a senior manager.', 'seniority')['status'], 'not_required')
        self.assertEqual(self.requirement('', 'seniority', title='Junior or Senior Python Developer')['status'], 'unknown')

    def test_general_language_is_known_but_advanced_level_is_not_invented(self):
        self.assertEqual(self.requirement('English required.', 'language_english')['status'], 'met')
        self.assertEqual(self.requirement('Fluent English required.', 'language_english')['status'], 'unknown')
        self.profile.language_levels['English'] = 'B1'
        self.assertEqual(self.requirement('Advanced English required.', 'language_english')['status'], 'unmet')
        self.profile.language_levels['English'] = 'C1'
        self.assertEqual(self.requirement('Inglés avanzado obligatorio.', 'language_english')['status'], 'met')
        self.assertEqual(self.requirement('No English required.', 'language_english')['status'], 'not_required')

    def test_additional_mandatory_conditions_are_not_assumed(self):
        for text, name in (('Security clearance required.', 'security_clearance'),
                           ('Must work weekends.', 'weekend_work'),
                           ('Travel required.', 'travel')):
            with self.subTest(text=text):
                self.assertEqual(self.requirement(text, name)['status'], 'unknown')
                self.profile.conditions[name] = False
                self.assertEqual(self.requirement(text, name)['status'], 'unmet')
                self.profile.conditions[name] = True
                self.assertEqual(self.requirement(text, name)['status'], 'met')
        requirements = evaluate_eligibility(self.profile, JobPosting(description='Must possess a valid nursing license.'))
        self.assertTrue(any(r['required'] and r['status'] == 'unknown' and r['name'].startswith('additional_requirement_') for r in requirements))

    def test_unknown_mandatory_fact_cannot_hide_behind_a_known_language_or_skill(self):
        for description in ('English required and a valid nursing license required.',
                            'Must know Python and possess a valid nursing license.',
                            'Prior professional experience in Python required.'):
            with self.subTest(description=description):
                result = evaluate_eligibility(self.profile, JobPosting(description=description))
                self.assertTrue(any(r['required'] and r['status'] == 'unknown'
                                    and r['name'].startswith('additional_requirement_') for r in result))

    def test_known_additional_conditions_can_share_required_and_preferred_clause(self):
        result = self.requirement('Travel preferred and security clearance required.', 'travel')
        self.assertFalse(result['required'])
        result = self.requirement('Travel preferred and security clearance required.', 'security_clearance')
        self.assertTrue(result['required'])

    def test_specific_certification_requires_specific_candidate_fact(self):
        self.profile.conditions['certification'] = True
        result = self.requirement('AWS certification required.', 'aws_certification')
        self.assertEqual(result['status'], 'unknown')
        self.profile.conditions['aws_certification'] = True
        self.assertEqual(self.requirement('AWS certification required.', 'aws_certification')['status'], 'met')

    def test_generic_customer_service_excluded_but_technical_support_preserved(self):
        self.assertEqual(self.requirement('', 'role_scope', title='Customer Service Representative')['status'], 'unmet')
        self.assertEqual(self.requirement('Help customers troubleshoot Linux.', 'role_scope', title='Technical Support Engineer')['status'], 'met')

    def test_negated_deal_breakers_do_not_become_exclusions(self):
        for description in ('No upfront payment required.', 'We never ask for upfront payment.',
                            'No se requiere pago por adelantado.'):
            with self.subTest(description=description):
                requirements = evaluate_eligibility(self.profile, JobPosting(description=description))
                self.assertFalse(any(r['name'].startswith('deal_breaker_') and r['status'] == 'unmet' for r in requirements))
        reqs = evaluate_eligibility(self.profile, JobPosting(description='Upfront payment required.'))
        self.assertTrue(any(r['name'].startswith('deal_breaker_') and r['status'] == 'unmet' for r in reqs))

    def test_normalized_field_provenance_is_preserved_without_trusting_region_hints(self):
        job = NormalizedJob(source='lever', source_board='synthetic', source_job_id='1',
                            company='Synthetic', title='Junior Engineer', locations=['Mexico'],
                            work_mode='remote', url=None,
                            description='We can hire candidates residing in Mexico.',
                            published_at=None, retrieved_at='2026-01-01T00:00:00Z',
                            verification_status='listed', eligibility_evidence={'mexico': True},
                            provenance={'description': ['descriptionPlain'], 'work_mode': ['workplaceType']})
        result = {r['name']: r for r in evaluate_eligibility(self.profile, job)}
        self.assertEqual(result['mexico_hiring']['status'], 'met')
        self.assertEqual(result['mexico_hiring']['evidence'][0]['provenance'], ['descriptionPlain'])
        self.assertEqual(result['remote_work']['status'], 'met')


if __name__ == '__main__':
    unittest.main()
