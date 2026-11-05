"""Offline regressions across public interfaces, with synthetic private data."""
import contextlib
import csv
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jobsearch_assistant.cli import main
from jobsearch_assistant.config import database_path
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.models import (
    ApplicationRecord,
    CandidateProfile,
    EvaluationResult,
    JobPosting,
)
from jobsearch_assistant.sources.models import (
    DiscoveryResult,
    HttpResponse,
    NormalizedJob,
    SourceReport,
)


def synthetic_job(provider="lever"):
    return NormalizedJob(
        source=provider, source_board="example", source_job_id="Case-ID",
        company="Synthetic Company", title="Junior Python Developer",
        locations=["Remote - Mexico"], work_mode="remote",
        url=None, description="Python and Linux. Fully remote. No degree required.",
        published_at=None, retrieved_at="2026-11-04T00:00:00+00:00",
        verification_status="listed", eligibility_evidence={"country_code": "MX", "status": "unknown"},
        provenance={"description": ["synthetic ATS description"], "work_mode": ["synthetic ATS mode"]},
    )


class Phase3CliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        environment = patch.dict(os.environ, {"JOB_SEARCH_ASSISTANT_HOME": str(self.root / "private")})
        environment.start()
        self.addCleanup(environment.stop)

    def invoke(self, *args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), \
                self.assertRaises(SystemExit) as result:
            main(list(args))
        return result.exception.code, output.getvalue(), error.getvalue()

    def test_discover_save_persists_all_providers_without_claiming_mexico_eligibility(self):
        jobs = [synthetic_job(provider) for provider in ("greenhouse", "lever", "ashby")]
        response = DiscoveryResult(jobs, [SourceReport(job.source, "example", status="ok") for job in jobs])
        with patch("jobsearch_assistant.sources.discovery.DiscoveryEngine.run", return_value=response):
            for _ in range(2):
                code, output, error = self.invoke("discover", "--save")
                self.assertEqual((code, error), (0, ""))
                payload = json.loads(output)
                self.assertEqual(len(payload["saved"]), 3)
                for item in payload["saved"]:
                    self.assertEqual(item["evaluation"]["algorithm_version"], "matching_v7")
                    self.assertEqual(item["evaluation"]["recommendation"], "insufficient_information")
        database = ApplicationDatabase(database_path())
        rows = database.list_vacancies()
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["job"]["provenance"], jobs[0].provenance)
            self.assertEqual(len(database.list_evaluations(row["id"])), 1)
        self.assertEqual(database.list(), [])  # Discovery does not create an application.

    def test_real_adapter_pipeline_persists_evidence_and_evaluates_offline(self):
        description = "Fully remote. We can hire candidates residing in Mexico. Python."
        rows = {
            "greenhouse": {"jobs": [{"id": 7, "title": "Junior Python Developer",
                "location": {"name": "Mexico"}, "content": description,
                "absolute_url": "https://job-boards.greenhouse.io/example/jobs/7"}]},
            "lever": [{"id": "Case-ID", "text": "Junior Python Developer",
                "categories": {"location": "Mexico"}, "descriptionPlain": description,
                "workplaceType": "remote", "hostedUrl": "https://jobs.lever.co/example/Case-ID"}],
            "ashby": {"jobs": [{"title": "Junior Python Developer", "location": "Mexico",
                "descriptionPlain": description, "workplaceType": "Remote", "isRemote": True,
                "isListed": True, "jobUrl": "https://jobs.ashbyhq.com/example/Case-ID"}]},
        }
        config = self.root / "sources.json"
        config.write_text(json.dumps({"schema_version": 1, "limits": {"min_interval": 0},
            "sources": [{"provider": provider, "board": "example", "company": "Synthetic Company",
                         "enabled": True} for provider in rows]}), encoding="utf-8")

        def response(url, timeout, max_bytes):
            provider = next(provider for provider in rows if provider in url)
            return HttpResponse(200, {"Content-Type": "application/json"},
                                json.dumps(rows[provider]).encode("utf-8"))

        with patch("jobsearch_assistant.sources.http.UrllibTransport.__call__", side_effect=response) as transport:
            code, output, error = self.invoke("discover", "--config", str(config), "--save")
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(transport.call_count, 3)
        payload = json.loads(output)
        database = ApplicationDatabase(database_path())
        for normalized, saved in zip(payload["jobs"], payload["saved"]):
            history = database.list_evaluations(saved["vacancy_id"])
            self.assertEqual(history[0]["job_snapshot"], normalized)
            self.assertTrue(normalized["provenance"]["description"][0].startswith("https://"))
            requirement = next(item for item in saved["evaluation"]["requirements"] if item["name"] == "mexico_hiring")
            self.assertEqual(requirement["status"], "met")
            self.assertEqual(normalized["eligibility_evidence"]["status"], "unknown")

    def test_vacancies_can_be_evaluated_again_offline_without_mutating_history(self):
        response = DiscoveryResult([synthetic_job()], [])
        with patch("jobsearch_assistant.sources.discovery.DiscoveryEngine.run", return_value=response):
            code, output, _ = self.invoke("discover", "--save")
            self.assertEqual(code, 0)
        saved = json.loads(output)["saved"][0]
        code, output, _ = self.invoke("vacancies", "list")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)[0]["id"], saved["vacancy_id"])
        code, output, _ = self.invoke("vacancies", "evaluate", str(saved["vacancy_id"]), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["evaluation_id"], saved["evaluation_id"])
        code, _, error = self.invoke("vacancies", "evaluate", "999999")
        self.assertEqual(code, 2)
        self.assertIn("999999", error)

    def test_future_database_is_not_migrated_by_vacancies_and_error_is_redacted(self):
        self.root.joinpath("private").mkdir()
        path = database_path()
        with contextlib.closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO meta VALUES ('schema_version', '999')")
        original = path.read_bytes()
        code, output, error = self.invoke("vacancies", "list")
        self.assertEqual((code, output), (2, ""))
        self.assertNotIn(str(path), error)
        self.assertEqual(path.read_bytes(), original)

    def test_analyze_json_and_plain_text_share_versioned_bilingual_result(self):
        posting = self.root / "posting.txt"
        posting.write_text("Fully remote. Python. US residents only.", encoding="utf-8")
        code, output, _ = self.invoke("analyze", str(posting), "--json")
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertEqual(result["algorithm_version"], "matching_v7")
        self.assertEqual(result["recommendation"], "ineligible")
        for language in ("es", "en"):
            code, output, _ = self.invoke("analyze", str(posting), "--language", language)
            self.assertEqual(code, 0)
            self.assertIn("matching_v7", output)
            self.assertIn("100", output)

    def test_analyze_save_json_remains_machine_readable_and_idempotent(self):
        posting = self.root / "posting.txt"
        posting.write_text("Not remote. US residents only.", encoding="utf-8")
        for _ in range(2):
            code, output, _ = self.invoke("analyze", str(posting), "--json", "--save")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["recommendation"], "ineligible")
        self.assertEqual(len(ApplicationDatabase(database_path()).list()), 1)

    def test_backup_and_restore_never_overwrite_or_initialize_private_workspace(self):
        source = self.root / "old.sqlite3"
        with contextlib.closing(sqlite3.connect(source)) as connection, connection:
            connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO meta VALUES ('schema_version','1')")
            connection.execute("CREATE TABLE synthetic (value TEXT)")
            connection.execute("INSERT INTO synthetic VALUES ('old-data')")
        backup, restored = self.root / "backup.sqlite3", self.root / "restored.sqlite3"
        for operation, src, dest in (("backup", source, backup), ("restore", backup, restored)):
            code, _, error = self.invoke("database", operation, "--source", str(src), "--output", str(dest))
            self.assertEqual((code, error), (0, ""))
        with contextlib.closing(sqlite3.connect(restored)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM synthetic").fetchone()[0], "old-data")
            self.assertEqual(connection.execute("SELECT value FROM meta").fetchone()[0], "1")
        code, _, _ = self.invoke("database", "restore", "--source", str(backup), "--output", str(restored))
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "private").exists())

    def test_exports_preserve_legacy_scores_labels_and_spreadsheet_safety(self):
        database = ApplicationDatabase(database_path())
        original = EvaluationResult(score=91, recommendation="strong_fit", reasons=["historical"])
        database.add(ApplicationRecord(id=None, job=JobPosting(title="=2+2", company="Synthetic"),
                                       evaluation=original, notes="@private synthetic note"))
        for file_format in ("csv", "json"):
            output = self.root / ("export." + file_format)
            code, _, error = self.invoke("export", "--format", file_format, "--output", str(output))
            self.assertEqual((code, error), (0, ""))
            if file_format == "json":
                evaluation = json.loads(output.read_text(encoding="utf-8"))[0]["evaluation"]
                self.assertEqual(evaluation, original.to_dict())
            else:
                with output.open(encoding="utf-8-sig", newline="") as handle:
                    row = next(csv.DictReader(handle))
                self.assertEqual(row["title"], "'=2+2")
                self.assertEqual(row["recommendation"], "strong_fit")
                self.assertEqual(row["notes"], "'@private synthetic note")
        self.assertEqual(database.list()[0].job.title, "=2+2")


class GuiHeadlessTests(unittest.TestCase):
    def test_editing_legacy_form_preserves_optional_verified_candidate_facts(self):
        from jobsearch_assistant.gui import JobSearchApp

        current = CandidateProfile(name="Synthetic", residence_country="MX", work_authorized_countries=["MX"],
                                   experience_years=1.5, degree_completed=False,
                                   language_levels={"English": "B2"}, conditions={"travel": False})
        values = {key: Mock(get=Mock(return_value=value)) for key, value in {
            "name": "Edited", "headline": "Student", "location": "Mexico", "skills": "python, linux",
            "target_roles": "junior developer", "preferred_locations": "remote", "remote_only": True,
        }.items()}
        app = SimpleNamespace(profile_vars=values, generate_search_urls=Mock(), t=lambda key: key)
        with patch("jobsearch_assistant.gui.load_profile", return_value=current), \
                patch("jobsearch_assistant.gui.save_profile") as save, \
                patch("jobsearch_assistant.gui.messagebox.showinfo"):
            JobSearchApp.save_profile_form(app)
        edited = save.call_args.args[0]
        self.assertEqual(edited.name, "Edited")
        for field in ("residence_country", "work_authorized_countries", "experience_years", "degree_completed",
                      "language_levels", "conditions"):
            self.assertEqual(getattr(edited, field), getattr(current, field))

    def test_analysis_uses_new_engine_without_creating_a_tk_window(self):
        from jobsearch_assistant.gui import JobSearchApp

        for language in ("es", "en"):
            with self.subTest(language=language):
                app = SimpleNamespace(
                    settings={"language": language}, profile=CandidateProfile(), t=lambda key: key,
                    description_text=Mock(get=Mock(return_value="Fully remote. US residents only.")),
                    job_vars={key: Mock(get=Mock(return_value="")) for key in ("title", "company", "location", "url")},
                    result_text=Mock(),
                )
                JobSearchApp.analyze_current(app)
                self.assertEqual(app.current_result.algorithm_version, "matching_v7")
                self.assertEqual(app.current_result.recommendation, "ineligible")
                report = app.result_text.insert.call_args.args[1]
                self.assertIn("matching_v7", report)
