import math
import unittest

from jobsearch_assistant.models import CandidateProfile, EvaluationResult


class MatchingContractTests(unittest.TestCase):
    def test_legacy_profile_keeps_new_candidate_facts_unknown(self):
        profile = CandidateProfile.from_dict({'name': 'Synthetic Candidate', 'skills': ['python']})
        for name in ('residence_country', 'work_authorized_countries', 'experience_years', 'degree_completed'):
            self.assertIsNone(getattr(profile, name))
        self.assertEqual(profile.language_levels, {})
        self.assertEqual(profile.conditions, {})

    def test_verified_input_types_roundtrip_without_inventing_facts(self):
        payload = {'residence_country': 'MX', 'work_authorized_countries': ['MX'],
                   'experience_years': 1.5, 'degree_completed': False,
                   'language_levels': {'English': 'B2'}, 'conditions': {'security_clearance': None}}
        result = CandidateProfile.from_dict(payload).to_dict()
        for name, value in payload.items():
            self.assertEqual(result[name], value)

    def test_invalid_optional_facts_are_rejected_without_echo(self):
        cases = {'residence_country': ['Mexico', 1, [], 'private-value'],
                 'work_authorized_countries': ['MX', [1], ['private-value']],
                 'experience_years': [True, -1, math.nan, math.inf, 10 ** 400, 'private-value'],
                 'degree_completed': ['false', 0, []],
                 'language_levels': [None, {'English': 1}, {'English': 'private-value'}],
                 'conditions': [[], {'private-value': 'yes'}]}
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value_type=type(value).__name__):
                    with self.assertRaises(ValueError) as error:
                        CandidateProfile.from_dict({name: value})
                    self.assertNotIn('private-value', str(error.exception))

    def test_old_evaluation_defaults_to_legacy_without_reinterpreting_score(self):
        historical_payload = {'score': 91, 'recommendation': 'strong_fit', 'reasons': ['old']}
        result = EvaluationResult(**historical_payload)
        self.assertEqual(result.algorithm_version, 'legacy_v1')
        self.assertEqual(result.score, 91)
        self.assertEqual(result.recommendation, 'strong_fit')
        self.assertEqual(result.reasons, ['old'])
        self.assertEqual(result.requirements, [])
        self.assertEqual(result.evidence, [])
