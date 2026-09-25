import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from jobsearch_assistant.config import (
    default_profile,
    ensure_workspace,
    load_profile,
    load_settings,
    profile_path,
    settings_path,
)
from jobsearch_assistant.evaluator import evaluate_job
from jobsearch_assistant.models import CandidateProfile, JobPosting


class ProfileShapeTests(unittest.TestCase):
    def test_valid_profile_round_trip_keeps_values_and_input(self) -> None:
        payload = default_profile().to_dict()
        payload.update(name="Example User", remote_only=False, skills=[])
        before = copy.deepcopy(payload)
        self.assertEqual(CandidateProfile.from_dict(payload).to_dict(), before)
        self.assertEqual(payload, before)

    def test_missing_and_unknown_fields_keep_existing_defaults(self) -> None:
        self.assertEqual(CandidateProfile.from_dict({}), CandidateProfile())
        self.assertEqual(
            CandidateProfile.from_dict({"name": "Example", "future_field": {}}),
            CandidateProfile(name="Example"),
        )

    def test_non_object_profiles_are_rejected(self) -> None:
        for payload in (None, [], "profile", 1, True):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                CandidateProfile.from_dict(payload)

    def test_text_fields_require_strings(self) -> None:
        for field in ("name", "headline", "location"):
            for value in (None, [], {}, 1, False):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    CandidateProfile.from_dict({field: value})

    def test_list_fields_require_arrays_of_strings(self) -> None:
        fields = (
            "languages", "skills", "target_roles", "preferred_locations",
            "accepted_seniority", "deal_breakers",
        )
        for field in fields:
            for value in (None, "python", {}, 1, ["python", None], [1], [[]]):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    CandidateProfile.from_dict({field: value})

    def test_remote_only_requires_a_boolean(self) -> None:
        for value in ("false", "true", 0, 1, None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CandidateProfile.from_dict({"remote_only": value})
        for value in (True, False):
            with self.subTest(value=value):
                self.assertIs(CandidateProfile.from_dict({"remote_only": value}).remote_only, value)

    def test_aliases_require_string_keys_and_string_arrays(self) -> None:
        for value in (None, [], "aliases", {"python": "python3"},
                      {"python": None}, {"python": [1]}, {1: ["python"]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CandidateProfile.from_dict({"skill_aliases": value})
        self.assertEqual(
            CandidateProfile.from_dict({"skill_aliases": {"python": ["python3"]}}).skill_aliases,
            {"python": ["python3"]},
        )

    def test_error_does_not_echo_profile_contents(self) -> None:
        private_value = "not-a-real-personal-secret"
        with self.assertRaises(ValueError) as error:
            CandidateProfile.from_dict({"skills": private_value})
        self.assertNotIn(private_value, str(error.exception))

    def test_valid_profile_loading_does_not_change_scoring(self) -> None:
        profile = default_profile()
        jobs = (
            JobPosting(title="Junior Python Developer", location="Remote - Mexico",
                       description="Python, Linux, Git and English; 1 year of experience."),
            JobPosting(title="Senior Engineer", location="On-site", description="7 years"),
            JobPosting(description="Send a gift card for a Telegram interview."),
            JobPosting(),
        )
        for job in jobs:
            with self.subTest(job=job.title):
                self.assertEqual(
                    evaluate_job(profile, job),
                    evaluate_job(CandidateProfile.from_dict(profile.to_dict()), job),
                )


class StoredConfigShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {"JOB_SEARCH_ASSISTANT_HOME": directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        ensure_workspace()

    def test_invalid_settings_fall_back_without_rewriting(self) -> None:
        values = (None, [], "es", 1, True, {"language": []}, {"language": {}},
                  {"language": None}, {"language": 1}, {"language": "invalid"})
        for value in values:
            with self.subTest(value=value):
                original = json.dumps(value).encode("utf-8")
                settings_path().write_bytes(original)
                self.assertEqual(load_settings(), {"language": "es"})
                self.assertEqual(settings_path().read_bytes(), original)

    def test_invalid_settings_encoding_and_syntax_do_not_crash(self) -> None:
        for original in (b"\xff", b"{invalid", b""):
            with self.subTest(original=original):
                settings_path().write_bytes(original)
                self.assertEqual(load_settings(), {"language": "es"})
                self.assertEqual(settings_path().read_bytes(), original)

    def test_valid_settings_keep_both_languages(self) -> None:
        for language in ("en", "es"):
            with self.subTest(language=language):
                settings_path().write_text(json.dumps({"language": language}), encoding="utf-8")
                self.assertEqual(load_settings(), {"language": language})

    def test_invalid_stored_profiles_fall_back_without_rewriting(self) -> None:
        values = (None, [], "profile", 1, True, {"skills": None}, {"skills": "python"},
                  {"remote_only": "false"}, {"skill_aliases": {"python": "python3"}})
        for value in values:
            with self.subTest(value=value):
                original = json.dumps(value).encode("utf-8")
                profile_path().write_bytes(original)
                self.assertEqual(load_profile(), default_profile())
                self.assertEqual(profile_path().read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
