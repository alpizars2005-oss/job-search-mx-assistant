import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.config import data_home, ensure_workspace, load_profile, load_settings


class ConfigTests(unittest.TestCase):
    def test_override_data_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"JOB_SEARCH_ASSISTANT_HOME": directory}):
                self.assertEqual(data_home(), Path(directory).resolve())
                ensure_workspace("en")
                self.assertEqual(load_settings()["language"], "en")
                self.assertTrue(load_profile().skills)


if __name__ == "__main__":
    unittest.main()
