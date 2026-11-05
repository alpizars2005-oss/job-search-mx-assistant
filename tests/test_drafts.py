import unittest

from jobsearch_assistant.drafts import build_draft
from jobsearch_assistant.sources.models import NormalizedJob
from jobsearch_assistant.workflow_contracts import WorkflowError


class DraftCompositionTests(unittest.TestCase):
    def job(self):
        return NormalizedJob(
            source='manual', source_board='local', source_job_id='stable', company='Synthetic Co',
            title='Junior Developer', locations=[], work_mode='unknown', url=None,
            description='We seek AWS, Java and 10 years of professional experience.',
            published_at=None, retrieved_at='now', verification_status='incomplete',
            eligibility_evidence={}, provenance={})

    def test_composition_uses_only_selected_attested_fact_text(self):
        for language, label in (('en', 'Personal projects'), ('es', 'Proyectos personales')):
            with self.subTest(language=language):
                metadata = {'language': language, 'candidate_name': 'Synthetic Candidate',
                            'claims': [{'id': 'project', 'kind': 'project',
                                        'text': 'Python: synthetic personal project.', 'evidence_ids': ['proof']}]}
                text = build_draft(self.job(), metadata)
                self.assertIn(label, text)
                self.assertIn('Python: synthetic personal project.', text)
                for unsupported in ('AWS', 'Java', '10 years'):
                    self.assertNotIn(unsupported, text)

    def test_missing_traceable_claims_cannot_generate_a_factual_letter(self):
        with self.assertRaises(WorkflowError):
            build_draft(self.job(), {'language': 'en', 'candidate_name': 'Synthetic', 'claims': []})
