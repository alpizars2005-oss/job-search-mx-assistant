from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from scripts import auto_update


class OriginValidationTests(unittest.TestCase):
    def test_accepts_exact_https_and_ssh_origins(self):
        self.assertTrue(
            auto_update.is_expected_origin(
                "https://github.com/alpizars2005-oss/job-search-mx-assistant.git"
            )
        )
        self.assertTrue(
            auto_update.is_expected_origin(
                "git@github.com:alpizars2005-oss/job-search-mx-assistant.git"
            )
        )

    def test_rejects_other_hosts_or_repositories(self):
        self.assertFalse(
            auto_update.is_expected_origin(
                "https://example.com/alpizars2005-oss/job-search-mx-assistant.git"
            )
        )
        self.assertFalse(
            auto_update.is_expected_origin(
                "https://github.com/alpizars2005-oss/other-project.git"
            )
        )
        self.assertFalse(auto_update.is_expected_origin("file:///tmp/repo"))


class UpdateFlowTests(unittest.TestCase):
    def _git_checkout(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / ".git").mkdir()
        return temporary, root

    def test_feature_branch_is_never_updated(self):
        temporary, root = self._git_checkout()
        try:
            def fake_git(*args, check=True):
                key = tuple(args)
                outputs = {
                    ("rev-parse", "--is-inside-work-tree"): "true\n",
                    ("rev-parse", "--abbrev-ref", "HEAD"): "feature/test\n",
                }
                return CompletedProcess(["git", *args], 0, outputs.get(key, ""), "")

            with patch.object(auto_update, "ROOT", root), patch.object(
                auto_update, "run_git", side_effect=fake_git
            ) as runner:
                result = auto_update.update_checkout()

            self.assertEqual(result.status, "skip")
            self.assertIn("feature/test", result.detail)
            self.assertFalse(any(call.args[0] == "fetch" for call in runner.call_args_list))
        finally:
            temporary.cleanup()

    def test_dirty_checkout_is_never_fetched_or_modified(self):
        temporary, root = self._git_checkout()
        try:
            def fake_git(*args, check=True):
                key = tuple(args)
                outputs = {
                    ("rev-parse", "--is-inside-work-tree"): "true\n",
                    ("rev-parse", "--abbrev-ref", "HEAD"): "main\n",
                    ("remote", "get-url", "origin"): (
                        "https://github.com/alpizars2005-oss/job-search-mx-assistant.git\n"
                    ),
                    ("status", "--porcelain"): " M README.md\n",
                }
                return CompletedProcess(["git", *args], 0, outputs.get(key, ""), "")

            with patch.object(auto_update, "ROOT", root), patch.object(
                auto_update, "run_git", side_effect=fake_git
            ) as runner:
                result = auto_update.update_checkout()

            self.assertEqual(result.status, "skip")
            self.assertIn("local changes", result.detail)
            commands = [call.args for call in runner.call_args_list]
            self.assertFalse(any(command and command[0] in {"fetch", "merge"} for command in commands))
        finally:
            temporary.cleanup()

    def test_clean_checkout_fast_forwards_only_to_fetched_main(self):
        temporary, root = self._git_checkout()
        local_sha = "1" * 40
        remote_sha = "2" * 40
        head_reads = 0
        calls = []
        try:
            def fake_git(*args, check=True):
                nonlocal head_reads
                calls.append(tuple(args))
                key = tuple(args)
                if key == ("rev-parse", "--is-inside-work-tree"):
                    output = "true\n"
                elif key == ("rev-parse", "--abbrev-ref", "HEAD"):
                    output = "main\n"
                elif key == ("remote", "get-url", "origin"):
                    output = "git@github.com:alpizars2005-oss/job-search-mx-assistant.git\n"
                elif key == ("status", "--porcelain"):
                    output = ""
                elif key == ("rev-parse", "origin/main"):
                    output = remote_sha + "\n"
                elif key == ("rev-parse", "HEAD"):
                    head_reads += 1
                    output = (local_sha if head_reads == 1 else remote_sha) + "\n"
                elif key == ("merge-base", "--is-ancestor", local_sha, remote_sha):
                    return CompletedProcess(["git", *args], 0, "", "")
                else:
                    output = ""
                return CompletedProcess(["git", *args], 0, output, "")

            with patch.object(auto_update, "ROOT", root), patch.object(
                auto_update, "run_git", side_effect=fake_git
            ):
                result = auto_update.update_checkout()

            self.assertEqual(result.status, "updated")
            self.assertIn(("fetch", "--quiet", "origin", "main"), calls)
            self.assertIn(("merge", "--ff-only", "--quiet", "origin/main"), calls)
            self.assertFalse(any("reset" in command for call in calls for command in call))
        finally:
            temporary.cleanup()

    def test_diverged_checkout_is_not_merged(self):
        temporary, root = self._git_checkout()
        local_sha = "a" * 40
        remote_sha = "b" * 40
        calls = []
        try:
            def fake_git(*args, check=True):
                calls.append(tuple(args))
                key = tuple(args)
                outputs = {
                    ("rev-parse", "--is-inside-work-tree"): "true\n",
                    ("rev-parse", "--abbrev-ref", "HEAD"): "main\n",
                    ("remote", "get-url", "origin"): (
                        "https://github.com/alpizars2005-oss/job-search-mx-assistant\n"
                    ),
                    ("status", "--porcelain"): "",
                    ("rev-parse", "HEAD"): local_sha + "\n",
                    ("rev-parse", "origin/main"): remote_sha + "\n",
                }
                if key == ("merge-base", "--is-ancestor", local_sha, remote_sha):
                    return CompletedProcess(["git", *args], 1, "", "")
                return CompletedProcess(["git", *args], 0, outputs.get(key, ""), "")

            with patch.object(auto_update, "ROOT", root), patch.object(
                auto_update, "run_git", side_effect=fake_git
            ):
                result = auto_update.update_checkout()

            self.assertEqual(result.status, "skip")
            self.assertIn("diverged", result.detail)
            self.assertFalse(any(call and call[0] == "merge" for call in calls))
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
