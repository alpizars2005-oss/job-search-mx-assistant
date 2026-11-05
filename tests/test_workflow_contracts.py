import math
import unittest
from dataclasses import replace

from jobsearch_assistant.sources.models import NormalizedJob
from jobsearch_assistant.workflow_contracts import (
    WorkflowError,
    canonical_json,
    content_digest,
    require_dry_run,
    vacancy_digest,
    vacancy_key,
)


class WorkflowContractTests(unittest.TestCase):
    def job(self):
        return NormalizedJob(
            source='lever', source_board='synthetic', source_job_id='Case-ID',
            company='Synthetic Company', title='Python Developer', locations=[],
            work_mode='unknown', url=None, description='Synthetic description',
            published_at=None, retrieved_at='2026-11-04T00:00:00Z',
            verification_status='incomplete', eligibility_evidence={'status': 'unknown'},
            provenance={'description': ['manual synthetic evidence']})

    def test_canonical_digest_is_stable_across_key_order_and_preserves_unicode(self):
        self.assertEqual(canonical_json({'b': 'México', 'a': 1}), '{"a":1,"b":"México"}')
        self.assertEqual(content_digest({'b': 2, 'a': 1}), content_digest({'a': 1, 'b': 2}))
        self.assertRegex(content_digest({'a': 1}), r'^[0-9a-f]{64}$')

    def test_nonfinite_values_cannot_enter_approved_json(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_json({'score': value})

    def test_observation_refresh_keeps_binding_but_content_changes_do_not(self):
        job = self.job()
        self.assertEqual(vacancy_key(job), ['lever', 'synthetic', 'Case-ID'])
        self.assertEqual(vacancy_digest(job), vacancy_digest(replace(job, retrieved_at='later')))
        for changes in ({'company': 'Changed'}, {'source_job_id': 'case-id'},
                        {'description': 'Changed'}, {'url': 'https://example.test/job'},
                        {'provenance': {}}, {'eligibility_evidence': {'status': 'changed'}}):
            with self.subTest(changes=changes):
                self.assertNotEqual(vacancy_digest(job), vacancy_digest(replace(job, **changes)))

    def test_policy_defaults_and_explicit_safe_flags(self):
        expected = {'dry_run': True, 'auto_submit': False}
        self.assertEqual(require_dry_run({}), expected)
        self.assertEqual(require_dry_run({'DRY_RUN': 'true', 'AUTO_SUBMIT': 'false'}), expected)
        self.assertEqual(require_dry_run({'DRY_RUN': ' TRUE ', 'AUTO_SUBMIT': 'FALSE'}), expected)

    def test_unsafe_or_malformed_flags_fail_without_echoing_values(self):
        for settings in ({'DRY_RUN': 'false'}, {'AUTO_SUBMIT': 'true'},
                         {'DRY_RUN': ''}, {'AUTO_SUBMIT': 'private-value'},
                         {'DRY_RUN': True}, {'AUTO_SUBMIT': '0'}):
            with self.subTest(settings=settings), self.assertRaises(WorkflowError) as error:
                require_dry_run(settings)
            self.assertEqual(error.exception.code, 'unsafe_runtime_policy')
            self.assertNotIn('private-value', str(error.exception))

    def test_diagnostic_codes_cannot_echo_an_untrusted_path_or_body(self):
        error = WorkflowError('private-value/person@example.test')
        self.assertEqual(error.code, 'workflow_error')
        self.assertNotIn('private-value', str(error))
        self.assertEqual(str(WorkflowError('stale_review')), 'stale_review')
