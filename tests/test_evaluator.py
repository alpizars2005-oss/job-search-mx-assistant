import unittest

from jobsearch_assistant.evaluator import evaluate_job, normalize
from jobsearch_assistant.models import CandidateProfile, JobPosting


class EvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = CandidateProfile(
            skills=["python", "linux", "technical support"],
            target_roles=["technical support", "help desk"],
            preferred_locations=["mexico", "remote"],
            remote_only=True,
            languages=["Spanish", "English"],
            skill_aliases={"technical support": ["help desk", "troubleshooting"]},
        )

    def test_normalize_removes_accents(self) -> None:
        self.assertEqual(normalize("México, Inglés"), "mexico, ingles")

    def test_strong_fit(self) -> None:
        job = JobPosting(
            title="Junior Technical Support",
            location="Remote - Mexico",
            description="Entry-level bilingual English role using Linux, Python and troubleshooting.",
        )
        result = evaluate_job(self.profile, job)
        self.assertGreaterEqual(result.score, 70)
        self.assertIn("python", result.matched_skills)
        self.assertIn("remote_match", result.positive_signals)

    def test_senior_role_is_penalized(self) -> None:
        job = JobPosting(
            title="Senior Technical Support Manager",
            location="On-site",
            description="Requires 7 years of experience.",
        )
        result = evaluate_job(self.profile, job)
        self.assertIn("senior_level", result.risks)
        self.assertIn("experience_requirement_7_years", result.risks)

    def test_suspicious_role_is_flagged(self) -> None:
        job = JobPosting(description="Telegram interview. Send a gift card to buy equipment.")
        result = evaluate_job(self.profile, job)
        self.assertEqual(result.recommendation, "review_risk")
        self.assertTrue(any(item.startswith("suspicious:") for item in result.risks))


if __name__ == "__main__":
    unittest.main()
