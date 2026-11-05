import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.config import data_home, ensure_workspace, load_profile, load_settings
from jobsearch_assistant.private_storage import PrivateStorageError


class ConfigTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows junction semantics')
    def test_override_junction_is_rejected_before_canonicalization(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.mkdir()
            link = Path(directory) / 'junction'
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                           check=True, capture_output=True)
            try:
                with patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': str(link)}), self.assertRaises(PrivateStorageError):
                    data_home()
                self.assertEqual(list(target.iterdir()), [])
            finally:
                link.rmdir()

    def test_override_data_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"JOB_SEARCH_ASSISTANT_HOME": directory}):
                self.assertEqual(data_home(), Path(directory).resolve())
                ensure_workspace("en")
                self.assertEqual(load_settings()["language"], "en")
                self.assertTrue(load_profile().skills)


if __name__ == "__main__":
    unittest.main()
