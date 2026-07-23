import unittest
from urllib.parse import unquote_plus, urlparse

from jobsearch_assistant.models import CandidateProfile
from jobsearch_assistant.search_queries import build_browser_urls, build_search_queries


class SearchQueryTests(unittest.TestCase):
    def test_remote_query_requires_remote_and_excludes_onsite_work(self) -> None:
        profile = CandidateProfile(
            target_roles=["help desk"],
            preferred_locations=["Remote", "Mexico", "Latin America"],
            remote_only=True,
        )

        query = build_search_queries(profile)[0]

        self.assertIn('"help desk"', query)
        self.assertIn('"100% remote"', query)
        self.assertIn('"home office"', query)
        self.assertIn('"Mexico"', query)
        self.assertIn('"Latin America"', query)
        self.assertNotIn('"Remote" OR "Mexico"', query)
        self.assertIn('-"presencial"', query)
        self.assertIn('-"híbrido"', query)
        self.assertIn('-"hybrid"', query)
        self.assertIn('-"onsite"', query)
        self.assertIn("-inurl:presencial", query)

    def test_remote_query_uses_default_eligibility_without_locations(self) -> None:
        profile = CandidateProfile(target_roles=["technical support"], remote_only=True)

        query = build_search_queries(profile)[0]

        self.assertIn('"Mexico"', query)
        self.assertIn('"Latin America"', query)
        self.assertIn('"LATAM"', query)

    def test_non_remote_query_keeps_regular_location_search(self) -> None:
        profile = CandidateProfile(
            target_roles=["help desk"],
            preferred_locations=["Mexico City"],
            remote_only=False,
        )

        query = build_search_queries(profile)[0]

        self.assertEqual(query, '"help desk" ("Mexico City")')
        self.assertNotIn('-"presencial"', query)

    def test_browser_url_is_encoded_and_limited_to_recent_results(self) -> None:
        profile = CandidateProfile(
            target_roles=["help desk"],
            preferred_locations=["Mexico"],
            remote_only=True,
        )

        url = build_browser_urls(profile, "linkedin")[0]
        parsed = urlparse(url)
        decoded = unquote_plus(parsed.query)

        self.assertTrue(url.startswith("https://www.google.com/search?q="))
        self.assertIn("site:linkedin.com/jobs/view", decoded)
        self.assertIn("tbs=qdr:m", decoded)


if __name__ == "__main__":
    unittest.main()
