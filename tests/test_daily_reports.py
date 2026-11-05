"""Synthetic local reports: cutoff, honest counts, immutable private publication."""

import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from jobsearch_assistant.automation_store import AutomationStore
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.models import CandidateProfile
from jobsearch_assistant.runtime_control import RunLock
from jobsearch_assistant.sources.models import NormalizedJob
from jobsearch_assistant.workflow_contracts import WorkflowError
from jobsearch_assistant.daily_reports import DailyReports, ReportSchedule


def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def job(identity="one", **changes):
    values = dict(
        source="greenhouse",
        source_board="synthetic",
        source_job_id=identity,
        company="PRIVATE COMPANY",
        title="Python Junior",
        locations=["Mexico"],
        work_mode="remote",
        url=f"https://boards.greenhouse.io/synthetic/jobs/{identity}",
        description="We can hire candidates residing in Mexico.",
        published_at=None,
        retrieved_at="2026-11-04T12:00:00Z",
        verification_status="listed",
        eligibility_evidence={},
        provenance={},
    )
    values.update(changes)
    return NormalizedJob(**values)


class DailyReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.database = ApplicationDatabase(self.home / "applications.sqlite3")
        self.clock = at("2026-11-04T20:00:30Z")
        self.reports = DailyReports(self.home, now=lambda: self.clock)
        self.profile = CandidateProfile(name="PRIVATE CANDIDATE", skills=["python"])
        self.env = patch.dict(os.environ, {"DRY_RUN": "true", "AUTO_SUBMIT": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def observe(self, when="2026-11-04T19:00:00Z", item=None):
        with patch("jobsearch_assistant.automation_store.timestamp", return_value=when):
            store = AutomationStore(self.database)
            run = store.start("config", "profile")
            if item is not False:
                store.observe(run, item or job(), self.profile)
            store.finish(run, "success", [])
        return run

    def read(self, day="2026-11-04"):
        return self.reports.read(day)

    def test_cutoff_no_future(self):
        schedule = ReportSchedule()
        self.assertEqual(
            schedule.latest_due(at("2026-11-04T19:59:59Z")), date(2026, 11, 3)
        )
        self.assertEqual(
            schedule.latest_due(at("2026-11-04T20:00:00Z")), date(2026, 11, 4)
        )
        self.assertEqual(
            schedule.window(date(2026, 11, 4)),
            (at("2026-11-03T20:00:00Z"), at("2026-11-04T20:00:00Z")),
        )
        self.clock = at("2026-11-04T19:59:59Z")
        self.reports.generate(start_date="2026-11-04")
        self.assertFalse((self.home / "reports/2026-11-04").exists())

    def test_empty_no_network_and_honest_delivery(self):
        with patch(
            "urllib.request.OpenerDirector.open", side_effect=AssertionError("No I/O")
        ):
            result = self.reports.generate()
        self.assertEqual(result["generated"], ["2026-11-04"])
        report = self.read()
        self.assertEqual(report["summary"]["new_vacancies"], 0)
        self.assertEqual(report["summary"]["confirmed_real_submissions"], 0)
        self.assertEqual(
            report["delivery"],
            dict(generated=True, stored=True, delivered=False, read=False),
        )
        self.assertIn(
            "Envíos reales confirmados: 0",
            (self.home / "reports/2026-11-04/report.md").read_text(encoding="utf-8"),
        )

    def test_restart_idempotence(self):
        self.observe()
        self.reports.generate()
        folder = self.home / "reports/2026-11-04"
        first = {p.name: p.read_bytes() for p in folder.iterdir()}
        self.clock = at("2026-11-05T20:00:00Z")
        result = DailyReports(self.home, now=lambda: self.clock).generate()
        self.assertEqual(result["reused"], ["2026-11-04"])
        self.assertEqual(result["generated"], ["2026-11-05"])
        self.assertEqual(first, {p.name: p.read_bytes() for p in folder.iterdir()})

    def test_catchup_bounded_and_delay(self):
        self.observe("2026-11-01T19:00:00Z", False)
        self.clock = at("2026-11-04T21:00:00Z")
        result = self.reports.generate(max_reports=2)
        self.assertEqual(result["generated"], ["2026-11-01", "2026-11-02"])
        self.assertEqual(result["remaining"], 2)
        report = self.read("2026-11-01")
        self.assertTrue(report["delayed"])
        self.assertGreater(report["delay_seconds"], 86400)
        result = self.reports.generate(max_reports=2)
        self.assertEqual(result["generated"], ["2026-11-03", "2026-11-04"])
        self.assertEqual(result["remaining"], 0)

    def test_new_reobserved_cutoff_and_no_profile(self):
        self.observe("2026-11-03T20:00:00Z")
        self.observe("2026-11-04T19:30:00Z")
        self.observe("2026-11-04T20:00:00Z", job("next", company="Next day"))
        self.reports.generate(start_date="2026-11-04")
        report = self.read()
        self.assertEqual(report["summary"]["new_vacancies"], 1)
        self.assertEqual(report["summary"]["unchanged_observations"], 1)
        self.assertEqual(report["vacancies"][0]["company"], "PRIVATE COMPANY")
        self.assertEqual(
            report["vacancies"][0]["discovered_at"], "2026-11-03T20:00:00+00:00"
        )
        self.assertEqual(report["vacancies"][0]["url_status"], "validated_origin_only")
        self.assertNotIn("PRIVATE CANDIDATE", json.dumps(report))
        self.assertNotIn("description", report["vacancies"][0])

    def test_latest_evaluation_and_reasons(self):
        self.observe("2026-11-04T18:00:00Z")
        self.observe(
            "2026-11-04T19:00:00Z", job(description="US-based candidates only.")
        )
        self.reports.generate()
        report = self.read()
        self.assertEqual(len(report["evaluations"]), 1)
        self.assertEqual(report["evaluations"][0]["classification"], "ineligible")
        self.assertTrue(report["evaluations"][0]["reason_codes"])
        self.assertEqual(report["summary"]["ineligible"], 1)

    def test_unsafe_url_markdown_and_exportable_summary(self):
        self.observe(
            item=job(
                company="<img src=x onerror=evil()>",
                title="[role](javascript:evil())",
                url="https://evil.test/secret",
            )
        )
        self.reports.generate()
        report = self.read()
        self.assertIsNone(report["vacancies"][0]["url"])
        md = (self.home / "reports/2026-11-04/report.md").read_text(encoding="utf-8")
        self.assertNotIn("<img", md)
        self.assertNotIn("[role](javascript:", md)
        self.assertNotIn("evil.test", md)
        summary = json.dumps(self.reports.read("2026-11-04", summary=True))
        for private in (
            "PRIVATE",
            "javascript",
            "greenhouse.io",
            "profile_snapshot",
            "vacancy_snapshot",
            "candidate_name",
        ):
            self.assertNotIn(private, summary)

    def test_lock_policy_and_corruption(self):
        with (
            RunLock(self.home / "automation.lock"),
            self.assertRaises(WorkflowError) as error,
        ):
            self.reports.generate()
        self.assertEqual(error.exception.code, "run_locked")
        with (
            patch.dict(os.environ, {"AUTO_SUBMIT": "true"}),
            self.assertRaises(WorkflowError),
        ):
            self.reports.generate()
        self.reports.generate()
        path = self.home / "reports/2026-11-04/report.json"
        path.write_text("{bad")
        with self.assertRaises(WorkflowError) as error:
            self.reports.generate()
        self.assertEqual(error.exception.code, "report_integrity_error")
        self.assertEqual(path.read_text(encoding="utf-8"), "{bad")

    def test_disk_failure_retry(self):
        with (
            patch(
                "jobsearch_assistant.daily_reports.write_private",
                side_effect=OSError("disk full"),
            ),
            self.assertRaises(WorkflowError),
        ):
            self.reports.generate()
        self.assertFalse((self.home / "reports/2026-11-04").exists())
        self.reports.generate()
        self.assertEqual(self.read()["summary"]["new_vacancies"], 0)

    def test_configuration_validation_and_schedule_guard(self):
        for kwargs in ({"timezone_name": "../bad"}, {"at": "25:00"}, {"at": "2:00"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(WorkflowError):
                ReportSchedule(**kwargs)
        self.reports.generate()
        changed = DailyReports(
            self.home, schedule=ReportSchedule(at="15:00"), now=lambda: self.clock
        )
        with self.assertRaises(WorkflowError):
            changed.generate()
        with self.assertRaises(WorkflowError):
            self.reports.read("../2026-11-04")
        with self.assertRaises(WorkflowError):
            self.reports.generate(max_reports=True)

    @unittest.skipUnless(os.name == "posix", "POSIX modes")
    def test_private_modes_and_symlink(self):
        prior = os.umask(0)
        self.addCleanup(os.umask, prior)
        self.reports.generate()
        for path in (self.home / "reports").rglob("*"):
            self.assertEqual(
                path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600
            )
        other = self.home / "other"
        other.mkdir(mode=0o700)
        (other / "reports").symlink_to(self.home / "reports", target_is_directory=True)
        ApplicationDatabase(other / "applications.sqlite3")
        with self.assertRaises(WorkflowError):
            DailyReports(other, now=lambda: self.clock).generate()


if __name__ == "__main__":
    unittest.main()


class ReportWorkflowTests(unittest.TestCase):
    setUp = DailyReportTests.setUp
    observe = DailyReportTests.observe
    read = DailyReportTests.read

    def test_cv_tracker_approval_simulation_and_manual_applied_distinct(self):
        import hashlib
        from jobsearch_assistant.resumes import ResumeStore
        from jobsearch_assistant.candidacies import CandidacyWorkflow
        from jobsearch_assistant.models import (
            ApplicationRecord,
            EvaluationResult,
            JobPosting,
        )

        evidence = self.home / "proof.txt"
        evidence.write_bytes(b"Synthetic proof")
        master = {
            "schema_version": 1,
            "candidate": {
                "name": "PRIVATE CANDIDATE",
                "contact": ["private@example.invalid"],
            },
            "evidence": [
                {
                    "id": "proof",
                    "path": "proof.txt",
                    "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                }
            ],
            "claims": [
                {
                    "id": "project",
                    "kind": "project",
                    "text": {"es": "Proyecto Python", "en": "Python project"},
                    "evidence_ids": ["proof"],
                    "attested": True,
                },
                {
                    "id": "pending",
                    "kind": "experience",
                    "text": {"es": "Sin confirmar", "en": "Unverified"},
                    "evidence_ids": ["proof"],
                    "attested": False,
                },
            ],
        }
        resumes = ResumeStore(self.home / "resumes")
        master_id = resumes.import_master(master, base_dir=self.home)
        version = resumes.create_version(master_id, job(), "en", format="txt")
        vacancy = self.database.upsert_vacancy(job())
        workflow = CandidacyWorkflow(self.database, resumes)
        candidate = workflow.create(vacancy, version["version_id"], "PRIVATE COVER")
        reviewed = workflow.review(candidate)
        auth = workflow.approve(candidate, reviewed["review_digest"])
        with patch(
            "jobsearch_assistant.candidacies._now", return_value="2026-11-04T19:00:00Z"
        ):
            receipt = workflow.simulate(auth)
        self.assertFalse(receipt["submitted"])
        workflow.update_tracking(
            candidate,
            status="applied",
            outcome="Manual registered",
            next_step="Follow up",
            follow_up_on="2026-11-04",
        )
        self.database.add(
            ApplicationRecord(
                None,
                JobPosting("Other", "Other"),
                EvaluationResult(10, "rejected"),
                status="applied",
            )
        )
        self.reports.generate()
        report = self.read()
        self.assertEqual(report["summary"]["local_simulations"], 1)
        self.assertEqual(report["summary"]["manually_recorded_applied"], 2)
        self.assertEqual(report["summary"]["confirmed_real_submissions"], 0)
        self.assertEqual(report["summary"]["local_active_approvals"], 0)
        self.assertEqual(report["current_state"]["evidence"]["unverified_claims"], 1)
        self.assertEqual(
            report["current_state"]["resumes"][0]["sha256"], version["sha256"]
        )
        self.assertIn("follow_up_due", report["current_state"]["follow_up_actions"])
        for secret in (
            "PRIVATE CANDIDATE",
            "private@example.invalid",
            "PRIVATE COVER",
            "Python project",
        ):
            self.assertNotIn(secret, json.dumps(report))
        self.assertFalse(report["current_state"]["historical_as_of_cutoff"])

    def test_interview_approval_and_pending_review_counts(self):
        from jobsearch_assistant.models import (
            ApplicationRecord,
            EvaluationResult,
            JobPosting,
        )

        self.database.add(
            ApplicationRecord(
                None,
                JobPosting("Role", "Company"),
                EvaluationResult(20, "rejected"),
                status="interview",
            )
        )
        self.reports.generate()
        self.assertEqual(self.read()["summary"]["interviews_recorded"], 1)

    def test_suspension_source_diagnostics_and_enabled_boards(self):
        from jobsearch_assistant.sources.models import SourceConfig

        self.reports.generate(
            configs=[SourceConfig("lever", "synthetic", "Synthetic", True)]
        )
        report = self.read()
        self.assertEqual(
            report["operational"]["enabled_sources"],
            [{"provider": "lever", "board": "synthetic"}],
        )
        self.assertEqual(report["operational"]["storage"]["status"], "readable")
        self.assertIn(
            report["operational"]["latest_backup"]["status"], ("unknown", "missing")
        )

    def test_timezone_dst_boundary_is_explicit(self):
        schedule = ReportSchedule("America/New_York", "02:30")
        with self.assertRaises(WorkflowError) as error:
            schedule.cutoff(date(2026, 3, 8))
        self.assertEqual(error.exception.code, "invalid_report_cutoff")
        fallback = ReportSchedule("America/New_York", "01:30")
        begin, end = fallback.window(date(2026, 11, 2))
        self.assertEqual((end - begin).total_seconds(), 25 * 3600)

    def test_spawned_process_blocks_then_recovers_after_termination(self):
        import subprocess
        import sys
        import jobsearch_assistant.daily_reports as module

        code = """import pathlib, sys, jobsearch_assistant
jobsearch_assistant.__path__.insert(0,sys.argv[1])
from jobsearch_assistant.daily_reports import DailyReports
from datetime import datetime
reporter=DailyReports(pathlib.Path(sys.argv[2]),now=lambda:datetime.fromisoformat('2026-11-04T20:00:30+00:00'))
original=reporter._publish
def hold(report):
    pathlib.Path(sys.argv[3]).write_text('ready')
    sys.stdin.readline()
    return original(report)
reporter._publish=hold
reporter.generate()
"""
        ready = self.home / "ready"
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                code,
                str(Path(module.__file__).parent),
                str(self.home),
                str(ready),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            import time

            deadline = time.monotonic() + 10
            while (
                not ready.exists()
                and time.monotonic() < deadline
                and process.poll() is None
            ):
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            with self.assertRaises(WorkflowError) as error:
                self.reports.generate()
            self.assertEqual(error.exception.code, "run_locked")
            process.kill()
            process.wait(timeout=10)
            self.assertFalse((self.home / "reports/2026-11-04").exists())
            self.reports.generate()
            self.assertEqual(self.read()["summary"]["confirmed_real_submissions"], 0)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)

    def test_crash_after_rename_keeps_complete_report(self):
        self.observe()
        import jobsearch_assistant.daily_reports as module

        original = module._sync_directory

        def crash(path):
            if path == self.home / "reports":
                raise OSError("Synthetic crash after publish")
            return original(path)

        with (
            patch.object(module, "_sync_directory", side_effect=crash),
            self.assertRaises(WorkflowError),
        ):
            self.reports.generate()
        first = (self.home / "reports/2026-11-04/report.json").read_bytes()
        result = self.reports.generate()
        self.assertEqual(result["generated"], [])
        self.assertEqual(result["reused"], ["2026-11-04"])
        self.assertEqual(
            first, (self.home / "reports/2026-11-04/report.json").read_bytes()
        )


class DailyReportCliTests(unittest.TestCase):
    setUp = DailyReportTests.setUp

    def invoke(self, *arguments):
        import argparse
        import io
        from contextlib import redirect_stdout, redirect_stderr
        from jobsearch_assistant.daily_report_cli import (
            add_report_parsers,
            dispatch_reports,
        )

        parser = argparse.ArgumentParser()
        add_report_parsers(parser.add_subparsers(dest="command", required=True))
        args = parser.parse_args(arguments)
        output, error = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {"JOB_SEARCH_ASSISTANT_HOME": str(self.home)}),
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            code = dispatch_reports(args)
        return code, output.getvalue(), error.getvalue()

    def test_generate_and_summary_are_operational_and_redacted(self):
        code, output, error = self.invoke("reports", "generate")
        self.assertEqual(code, 0, error)
        result = json.loads(output)
        self.assertFalse(result["delivered"])
        day = result["generated"][0]
        code, output, error = self.invoke("reports", "show", day, "--summary")
        self.assertEqual(code, 0, error)
        summary = json.loads(output)
        self.assertEqual(summary["counts"]["confirmed_real_submissions"], 0)
        self.assertFalse(summary["delivered"])
        self.assertNotIn(str(self.home), output + error)

    def test_bad_inputs_redacted_and_policy_rejected(self):
        code, output, error = self.invoke(
            "reports", "generate", "--start-date", "PRIVATE BAD DATE"
        )
        self.assertEqual(code, 2)
        self.assertNotIn("PRIVATE", error)
        self.assertEqual(output, "")
        with patch.dict(os.environ, {"AUTO_SUBMIT": "true"}):
            code, output, error = self.invoke("reports", "generate")
        self.assertEqual(code, 2)
        self.assertIn("unsafe_runtime_policy", error)
