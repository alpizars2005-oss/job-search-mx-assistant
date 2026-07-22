import unittest

from jobsearch_assistant.models import CandidateProfile
from jobsearch_assistant.search_queries import build_browser_urls, build_search_queries


class SearchQueryTests(unittest.TestCase):
    def test_build_queries_and_urls(self) -> None:
        profile = CandidateProfile(
            target_roles=["help desk"],
            preferred_locations=["mexico"],
            remote_only=True,
        )
        queries = build_search_queries(profile)
        self.assertIn('"help desk"', queries[0])
        urls = build_browser_urls(profile, "linkedin")
        self.assertTrue(urls[0].startswith("https://www.google.com/search?q="))


if __name__ == "__main__":
    unittest.main()
