import unittest

from jobsearch_assistant import matching
from jobsearch_assistant.matching import evaluate_match, explain_evaluation
from jobsearch_assistant.models import CandidateProfile, JobPosting


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.profile = CandidateProfile(skills=['python', 'linux', 'technical support'],
                                        target_roles=['technical support'],
                                        preferred_locations=['Mexico'],
                                        skill_aliases={'technical support': ['troubleshooting']})
        self.job = JobPosting(title='Junior Technical Support', location='Remote - Mexico',
                              description='Entry-level bilingual English role using Linux, Python and troubleshooting.')

    def test_new_evaluations_export_the_current_algorithm_version(self):
        self.assertEqual(getattr(matching, 'ALGORITHM_VERSION', None), 'matching_v6')
        self.assertEqual(evaluate_match(self.profile, self.job).algorithm_version, matching.ALGORITHM_VERSION)

    def test_known_skill_remote_signals_survive_essential_unknown(self):
        result = evaluate_match(self.profile, self.job)
        self.assertEqual(result.algorithm_version, 'matching_v6')
        self.assertGreaterEqual(result.score, 70)
        self.assertIn('python', result.matched_skills)
        self.assertIn('remote_match', result.positive_signals)
        self.assertEqual(result.recommendation, 'insufficient_information')
        self.assertIn('mexico_hiring', result.unknowns)
        self.assertNotIn('mexico_hiring', result.requirements_met)

    def test_ineligibility_overrides_high_score(self):
        self.job.description += ' US residents only.'
        result = evaluate_match(self.profile, self.job)
        self.assertGreaterEqual(result.score, 70)
        self.assertEqual(result.recommendation, 'ineligible')
        self.assertIn('mexico_hiring', result.missing_requirements)

    def test_confirmed_mexico_permission_unlocks_priority_without_inventing_salary(self):
        self.job.description += ' We can hire candidates residing in Mexico.'
        result = evaluate_match(self.profile, self.job)
        self.assertEqual(result.recommendation, 'high_priority')
        self.assertIn('salary_information', result.unknowns)
        self.assertFalse(any('salary' in r and 'points' in r for r in result.reasons))

    def test_score_bands_and_nonessential_ambiguity(self):
        # Hand-selected known signals span all four compatibility bands.
        for skills, title, description, expected in (
            (['python'], 'Junior Technical Support', 'Python. English required.', 'high_priority'),
            (['python'], 'Technical Support', 'Python.', 'medium_priority'),
            (['python'], 'Unlisted position', 'Python.', 'manual_review'),
            (['python'], 'Unlisted position', '', 'rejected'),
        ):
            with self.subTest(expected=expected):
                profile = CandidateProfile(skills=skills, target_roles=['technical support'])
                job = JobPosting(title=title, location='Remote',
                                 description=description + ' We can hire candidates residing in Mexico.')
                self.assertEqual(evaluate_match(profile, job).recommendation, expected)
        self.job.description += ' We can hire candidates residing in Mexico. Fluent French preferred.'
        self.assertEqual(evaluate_match(self.profile, self.job).recommendation, 'manual_review')

    def test_senior_and_year_risk_codes_remain_available(self):
        result = evaluate_match(self.profile, JobPosting(title='Senior Technical Support Manager',
                                location='On-site', description='Requires 7 years of experience.'))
        self.assertIn('senior_level', result.risks)
        self.assertIn('experience_requirement_7_years', result.risks)
        self.assertEqual(result.recommendation, 'ineligible')

    def test_suspicious_recruitment_is_excluded_but_negated_payment_is_safe(self):
        result = evaluate_match(self.profile, JobPosting(description='Telegram interview. Send a gift card to buy equipment.'))
        self.assertEqual(result.recommendation, 'ineligible')
        self.assertTrue(any(r.startswith('suspicious:') for r in result.risks))
        self.job.description += ' No upfront payment required. We can hire candidates residing in Mexico.'
        self.assertEqual(evaluate_match(self.profile, self.job).recommendation, 'high_priority')

    def test_explanations_are_bilingual_deterministic_and_honest(self):
        result = evaluate_match(self.profile, self.job)
        spanish = explain_evaluation(result, 'es')
        english = explain_evaluation(result, 'en')
        self.assertIn('Información insuficiente', spanish)
        self.assertIn('Insufficient information', english)
        self.assertIn('México', spanish)
        self.assertIn('Mexico', english)
        self.assertIn('probabilidad', spanish)
        self.assertIn('probability', english)
        self.assertEqual(evaluate_match(self.profile, self.job).to_dict(), result.to_dict())
        self.assertEqual(explain_evaluation(result), spanish)
        self.assertIn('description', english)
        self.assertIn('Algoritmo: matching_v6', spanish)
        self.assertIn('Algorithm: matching_v6', english)

    def test_exact_score_boundaries_are_applied_after_eligibility(self):
        for owned_count, matched_count, language, score, classification in (
            (1, 1, True, 80, 'high_priority'),
            (34, 33, True, 79, 'medium_priority'),
            (7, 4, True, 65, 'medium_priority'),
            (4, 3, False, 64, 'manual_review'),
            (3, 1, False, 50, 'manual_review'),
            (13, 4, False, 49, 'rejected'),
        ):
            with self.subTest(score=score):
                profile = CandidateProfile(skills=[f'synthetic_skill_{i}' for i in range(owned_count)],
                                           target_roles=['technical support'])
                job = JobPosting(title='Technical Support', location='Remote',
                                 description=' '.join(profile.skills[:matched_count]) +
                                 '. We can hire candidates residing in Mexico.' +
                                 (' English required.' if language else ''))
                result = evaluate_match(profile, job)
                self.assertEqual(result.score, score)
                self.assertEqual(result.recommendation, classification)

    def test_scoring_signals_include_checkable_original_source_spans(self):
        profile = CandidateProfile(skills=['python'], target_roles=['developer'],
                                   preferred_locations=['Mexico'])
        description = 'Python. We can hire candidates residing in Mexico.'
        job = JobPosting(title='Junior Developer', location='Remote - Mexico', description=description)
        result = evaluate_match(profile, job)
        skill_evidence = [fact for fact in result.evidence if fact.get('signal') == 'skill_match'
                          and fact.get('field') == 'description']
        self.assertTrue(skill_evidence)
        self.assertEqual(skill_evidence[0]['span'], 'Python.')
        for fact in result.evidence:
            if 'span' in fact:
                value = getattr(job, fact['field'])
                self.assertEqual(value[fact['start']:fact['end']], fact['span'])
        for signal in ('skill_match', 'target_role', 'location_match', 'junior_friendly', 'remote_match'):
            self.assertTrue(any(fact.get('signal') == signal for fact in result.evidence), signal)

    def test_adversarial_eligibility_cannot_be_overridden_by_high_compatibility(self):
        self.profile.degree_completed = False
        self.profile.experience_years = 5
        self.profile.language_levels['English'] = 'B1'
        self.profile.work_authorized_countries = ['MX']
        for restriction, expected in (
            ('We can hire in all countries except Mexico.', 'ineligible'),
            ('We are hiring engineers with experience in Mexico.', 'insufficient_information'),
            ("We can hire candidates residing in Mexico. Bachelor's degree required, English preferred.", 'ineligible'),
            ('We can hire candidates residing in Mexico. Fluent English required, Python preferred.', 'ineligible'),
            ('We can hire candidates residing in Mexico. Must be authorized to work in the United States.', 'ineligible'),
            ('We can hire candidates residing in Mexico. Must know Python plus an active medical registration.', 'insufficient_information'),
            ('We can hire candidates residing in Mexico. 5 years of Java experience required.', 'insufficient_information'),
            ('We can hire candidates residing in Mexico. Remote work is unavailable.', 'insufficient_information'),
        ):
            with self.subTest(restriction=restriction):
                self.job.description = 'Python, Linux and troubleshooting. ' + restriction
                self.assertEqual(evaluate_match(self.profile, self.job).recommendation, expected)

    def test_repeated_obligations_and_specific_mexico_denials_do_not_become_priority(self):
        self.profile.degree_completed = False
        self.profile.language_levels['English'] = 'B1'
        for text, recommendation in (
            ('English preferred and fluent English required.', 'ineligible'),
            ('Degree preferred, but completed degree required.', 'ineligible'),
            ('This role is not available to candidates based in Mexico.', 'insufficient_information'),
            ('Candidates residing in Mexico cannot apply.', 'insufficient_information'),
        ):
            with self.subTest(text=text):
                self.job.description = 'We can hire candidates residing in Mexico. Fully remote. ' + text
                self.assertEqual(evaluate_match(self.profile, self.job).recommendation, recommendation)
        for text in ('We may hire candidates residing in Mexico.',
                     'We hope we can hire candidates residing in Mexico.'):
            with self.subTest(text=text):
                self.job.description = 'Fully remote. ' + text
                self.assertEqual(evaluate_match(self.profile, self.job).recommendation, 'insufficient_information')

    def test_new_essential_unknown_and_work_authorization_have_bilingual_labels(self):
        self.profile.experience_years = 5
        self.profile.work_authorized_countries = ['MX']
        self.job.description = ('We can hire candidates residing in Mexico. '
                                '5 years of Java experience required. '
                                'Must be authorized to work in the United States.')
        result = evaluate_match(self.profile, self.job)
        self.assertIn('Experiencia específica sin verificar', explain_evaluation(result, 'es'))
        self.assertIn('Unverified technology or role experience', explain_evaluation(result, 'en'))
        self.assertIn('Permiso para trabajar en Estados Unidos', explain_evaluation(result, 'es'))
        self.assertIn('Permission to work in the United States', explain_evaluation(result, 'en'))

    def test_negated_skill_use_does_not_earn_matching_points(self):
        profile = CandidateProfile(skills=['python'])
        result = evaluate_match(profile, JobPosting(description='We do not use Python.'))
        self.assertEqual(result.matched_skills, [])
        self.assertNotIn('skill_match', result.positive_signals)

    def test_profile_experience_not_inferred_from_skills_or_headline(self):
        self.profile.headline = 'Five years learning Python'
        self.job.description += ' Requires 2 years of experience. We can hire candidates residing in Mexico.'
        result = evaluate_match(self.profile, self.job)
        self.assertEqual(result.recommendation, 'insufficient_information')
        self.assertIn('experience', result.unknowns)

    def test_conflicting_essential_facts_stay_unknown(self):
        self.job.description += ' We can hire candidates residing in Mexico. US residents only.'
        result = evaluate_match(self.profile, self.job)
        self.assertEqual(result.recommendation, 'insufficient_information')
        self.assertIn('mexico_hiring', result.unknowns)
        self.assertNotIn('mexico_hiring', result.missing_requirements)


if __name__ == '__main__':
    unittest.main()
