import tempfile
import unittest
from pathlib import Path

from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.models import ApplicationRecord, EvaluationResult, JobPosting


class DatabaseTests(unittest.TestCase):
    def test_add_list_update_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = ApplicationDatabase(Path(directory) / "test.sqlite3")
            record_id = database.add(
                ApplicationRecord(
                    id=None,
                    job=JobPosting(title="Support", company="Example"),
                    evaluation=EvaluationResult(score=80, recommendation="strong_fit"),
                )
            )
            self.assertEqual(record_id, 1)
            self.assertEqual(len(database.list()), 1)
            self.assertTrue(database.update_status(record_id, "applied"))
            self.assertEqual(database.list()[0].status, "applied")
            self.assertEqual(database.summary()["applied"], 1)
            self.assertEqual(
                database.find_duplicate(JobPosting(title="Support", company="Example")),
                record_id,
            )
            self.assertTrue(database.update(record_id, notes="Follow up Friday"))
            self.assertEqual(database.list()[0].notes, "Follow up Friday")


if __name__ == "__main__":
    unittest.main()
