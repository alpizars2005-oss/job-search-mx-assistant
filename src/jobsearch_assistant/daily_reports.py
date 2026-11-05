"""Private daily snapshots; file publication is the durable date registry.

No network transport exists here. Immutable report folders survive a restart
without a second database commit or an external delivery acknowledgement.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import quote

from .migrations import SCHEMA_VERSION
from .private_storage import (
    private_directory,
    private_path,
    read_private,
    sqlite_private,
    write_private,
)
from .resumes import ResumeStore
from .runtime_control import RunLock
from .sources.adapters import _job_url
from .sources.models import SourceConfig, SourceError
from .workflow_contracts import WorkflowError, canonical_json, require_dry_run

UTC = timezone.utc
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_ROWS = 10000
_CODE = re.compile(r"[a-z][a-z0-9_:.-]{0,100}\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_CLASSIFICATIONS = (
    "high_priority",
    "medium_priority",
    "manual_review",
    "rejected",
    "ineligible",
    "insufficient_information",
)


def _instant(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise WorkflowError("invalid_report_time")
    return value.astimezone(UTC)


def _date(value):
    if type(value) is date:
        return value
    if type(value) is not str or not _DATE.fullmatch(value):
        raise WorkflowError("invalid_report_date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise WorkflowError("invalid_report_date") from None


@dataclass(frozen=True)
class ReportSchedule:
    timezone_name: str = "America/Mexico_City"
    at: str = "14:00"

    def __post_init__(self):
        if (
            type(self.timezone_name) is not str
            or len(self.timezone_name) > 100
            or not re.fullmatch(r"[A-Za-z0-9_+/-]+", self.timezone_name)
            or ".." in self.timezone_name
            or type(self.at) is not str
            or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", self.at)
        ):
            raise WorkflowError("invalid_report_schedule")
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise WorkflowError("report_timezone_unavailable") from None

    @property
    def policy(self):
        return {"format_version": 1, "timezone": self.timezone_name, "at": self.at}

    def cutoff(self, day):
        zone = ZoneInfo(self.timezone_name)
        local = datetime.combine(day, time.fromisoformat(self.at), zone)
        utc = local.astimezone(UTC)
        # Nonexistent DST times fail explicitly; ambiguous times use fold=0.
        if utc.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
            raise WorkflowError("invalid_report_cutoff")
        return utc

    def latest_due(self, now):
        now = _instant(now)
        local_day = now.astimezone(ZoneInfo(self.timezone_name)).date()
        return (
            local_day
            if now >= self.cutoff(local_day)
            else local_day - timedelta(days=1)
        )

    def window(self, day):
        return self.cutoff(day - timedelta(days=1)), self.cutoff(day)

    def containing_day(self, instant):
        instant = _instant(instant)
        local_day = instant.astimezone(ZoneInfo(self.timezone_name)).date()
        return (
            local_day
            if instant < self.cutoff(local_day)
            else local_day + timedelta(days=1)
        )


def _rows(connection, sql, parameters=()):
    total = 0
    for count, row in enumerate(connection.execute(sql, parameters), 1):
        total += sum(
            len(value.encode("utf-8")) for value in row if isinstance(value, str)
        )
        if count > MAX_ROWS or total > MAX_INPUT_BYTES:
            raise WorkflowError("report_input_limit")
        yield row


def _codes(values):
    if not isinstance(values, list):
        return []
    return sorted(
        {value for value in values if type(value) is str and _CODE.fullmatch(value)}
    )


def _text(value, limit=1000):
    return value[:limit] if isinstance(value, str) else ""


def _job_detail(row, discovered):
    job = json.loads(row["job_snapshot_json"])
    if not isinstance(job, dict):
        raise WorkflowError("invalid_report_snapshot")
    source = job.get("source")
    url, url_status = None, "unknown"
    if job.get("url"):
        try:
            config = SourceConfig(source, job.get("source_board"), job.get("company"))
            url, _ = _job_url(config, job["url"], job.get("source_job_id"))
            url_status = "validated_origin_only"
        except (SourceError, ValueError, TypeError):
            url_status = "rejected"
    return {
        "vacancy_id": row["vacancy_id"],
        "company": _text(job.get("company")),
        "title": _text(job.get("title")),
        "source": source
        if source in ("greenhouse", "lever", "ashby", "manual")
        else "unknown",
        "source_job_id": _text(job.get("source_job_id"), 200),
        "url": url,
        "url_status": url_status,
        "independently_verified_live": False,
        "verification_status": job.get("verification_status")
        if job.get("verification_status") in ("listed", "unverified")
        else "unknown",
        "discovered_at": discovered.isoformat(),
        "discovery_time_basis": "first_automation_run_start",
    }


def _resume_inventory(home, candidates):
    root = private_path(home / "resumes")
    if not root.exists():
        return [], {"status": "no_masters", "unverified_claims": None}
    private_directory(root, harden=False)
    # Read without the constructor's directory creation. All public reads verify
    # immutable manifests, documents, masters and evidence through shared code.
    store = ResumeStore.__new__(ResumeStore)
    store.root = root
    master_paths = sorted((root / "masters").glob("*.json"))
    version_paths = sorted((root / "versions").glob("*.json"))
    if len(master_paths) > MAX_ROWS or len(version_paths) > MAX_ROWS:
        raise WorkflowError("report_input_limit")
    pending = 0
    for path in master_paths:
        master = store.get_master(path.stem)
        pending += sum(
            not claim["attested"] or not claim["evidence_ids"]
            for claim in master["claims"]
        )
    versions = []
    for path in version_paths:
        metadata = store.verify_version(path.stem)
        states = sorted(
            {
                item["workflow_state"]
                for item in candidates
                if item["resume_version_id"] == metadata["version_id"]
            }
        )
        versions.append(
            {
                key: metadata[key]
                for key in (
                    "version_id",
                    "sha256",
                    "language",
                    "format",
                    "created_at",
                    "vacancy_key",
                )
            }
        )
        versions[-1]["review_status"] = states or ["not_linked_for_review"]
        versions[-1]["integrity"] = "verified"
        versions[-1]["selected_claims_missing_evidence"] = 0
    return versions, {
        "status": "verified" if master_paths else "no_masters",
        "unverified_claims": pending if master_paths else None,
    }


def _latest_backup(home):
    try:
        from .storage import verify_bundle, backup_root
    except ImportError:
        return {"status": "unknown", "reason": "backup_verifier_unavailable"}
    root = backup_root(home)
    if not root.exists():
        return {"status": "missing"}
    private_directory(root, harden=False)
    latest, invalid = None, 0
    for candidate in sorted(root.iterdir()):
        try:
            manifest = verify_bundle(candidate)
            created = _instant(manifest["created_at"])
            if latest is None or created > latest[0]:
                latest = created, manifest
        except (OSError, ValueError, TypeError, KeyError):
            invalid += 1
    return (
        {
            "status": "verified",
            "created_at": latest[0].isoformat(),
            "invalid_bundles": invalid,
        }
        if latest
        else {"status": "unverified", "invalid_bundles": invalid}
    )


def _snapshot(home, start, end, generated_at, configs, timezone_name):
    connection = sqlite_private(
        home / "applications.sqlite3", read_only=True, timeout=0.1
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        marker = connection.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if marker is None or marker[0] != str(SCHEMA_VERSION):
            raise WorkflowError("schema_upgrade_required")
        new, latest, unchanged = {}, {}, 0
        for row in _rows(
            connection,
            """SELECT i.vacancy_id,i.evaluation_id,i.change_kind,i.classification,
                r.started_at,e.job_snapshot_json,e.evaluation_json
                FROM automation_items i JOIN automation_runs r ON r.id=i.run_id
                JOIN evaluations e ON e.id=i.evaluation_id
                WHERE julianday(r.started_at)>=julianday(?) AND julianday(r.started_at)<julianday(?)
                ORDER BY julianday(r.started_at),r.id,i.vacancy_id""",
            (start.isoformat(), end.isoformat()),
        ):
            observed = _instant(row["started_at"])
            if not start <= observed < end:
                continue
            if row["change_kind"] == "new" and row["vacancy_id"] not in new:
                new[row["vacancy_id"]] = _job_detail(row, observed)
            if row["change_kind"] == "unchanged":
                unchanged += 1
            result = json.loads(row["evaluation_json"])
            if not isinstance(result, dict) or not isinstance(
                result.get("requirements", []), list
            ):
                raise WorkflowError("invalid_report_snapshot")
            classification = (
                row["classification"]
                if row["classification"] in _CLASSIFICATIONS
                else "unknown"
            )
            requirements = result.get("requirements", [])
            latest[row["vacancy_id"]] = {
                "vacancy_id": row["vacancy_id"],
                "evaluation_id": row["evaluation_id"],
                "classification": classification,
                "score": result.get("score")
                if type(result.get("score")) is int
                else None,
                "algorithm_version": result.get("algorithm_version")
                if _CODE.fullmatch(str(result.get("algorithm_version", "")))
                else "unknown",
                "job": _job_detail(row, observed),
                "reason_codes": _codes(
                    [
                        item.get("reason_code")
                        for item in requirements
                        if isinstance(item, dict)
                        and item.get("status") in ("unmet", "unknown", "contradictory")
                    ]
                ),
                "pending_requirements": _codes(
                    [
                        item.get("name")
                        for item in requirements
                        if isinstance(item, dict)
                        and item.get("status") in ("unknown", "contradictory")
                    ]
                ),
            }
        candidates = [
            dict(row)
            for row in _rows(
                connection,
                """SELECT c.id,c.vacancy_id,c.resume_version_id,
            c.workflow_state,c.revision,c.company,c.outcome,c.next_step,c.follow_up_on,c.created_at,c.updated_at,a.status AS tracker_status
            FROM candidacies c JOIN applications a ON a.id=c.application_id ORDER BY c.id""",
            )
        ]
        auth_counts = dict(
            connection.execute(
                "SELECT status,COUNT(*) FROM candidacy_authorizations GROUP BY status"
            )
        )
        simulations, simulations_total = 0, 0
        for row in _rows(
            connection,
            "SELECT receipt_json,consumed_at FROM candidacy_authorizations WHERE status='consumed'",
        ):
            receipt = json.loads(row[0]) if row[0] else {}
            if not isinstance(receipt, dict):
                raise WorkflowError("invalid_report_snapshot")
            if receipt.get("submitted") is False and receipt.get("dry_run") is True:
                simulations_total += 1
                if row[1] and start <= _instant(row[1]) < end:
                    simulations += 1
        activity = [
            dict(row)
            for row in _rows(
                connection,
                """SELECT id,candidacy_id,revision,event_type,created_at FROM candidacy_events
            WHERE julianday(created_at)>=julianday(?) AND julianday(created_at)<julianday(?)
            ORDER BY id""",
                (start.isoformat(), end.isoformat()),
            )
        ]
        tracker_counts = dict(
            connection.execute(
                "SELECT status,COUNT(*) FROM applications GROUP BY status"
            )
        )
        last = connection.execute(
            "SELECT id,started_at,finished_at,status,recovered_runs,reports_json FROM automation_runs ORDER BY started_at DESC,id DESC LIMIT 1"
        ).fetchone()
        sources = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM automation_source_health ORDER BY provider"
            )
        ]
        http_states = [
            {"provider": row["provider"], **json.loads(row["state_json"])}
            for row in connection.execute(
                "SELECT * FROM automation_http_state ORDER BY provider"
            )
        ]
        duplicates = 0
        for row in _rows(
            connection,
            """SELECT started_at,reports_json FROM automation_runs
                WHERE julianday(started_at)>=julianday(?) AND julianday(started_at)<julianday(?)""",
            (start.isoformat(), end.isoformat()),
        ):
            if start <= _instant(row[0]) < end:
                duplicates += sum(
                    item.get("duplicates", 0)
                    for item in json.loads(row[1])
                    if isinstance(item, dict) and type(item.get("duplicates")) is int
                )
        connection.commit()
    finally:
        connection.close()
    versions, evidence = _resume_inventory(home, candidates)
    summary = {
        key: sum(item["classification"] == key for item in latest.values())
        for key in _CLASSIFICATIONS
    }
    summary.update(
        new_vacancies=len(new),
        evaluated_vacancies=len(latest),
        unchanged_observations=unchanged,
        provider_duplicates_avoided=duplicates,
        prepared_resume_versions=sum(
            start <= _instant(item["created_at"]) < end for item in versions
        ),
        resume_versions_total=len(versions),
        draft_candidacies=sum(item["workflow_state"] == "draft" for item in candidates),
        reviewed_pending_approval=sum(
            item["workflow_state"] == "reviewed" for item in candidates
        ),
        local_active_approvals=auth_counts.get("active", 0),
        local_simulations=simulations,
        local_simulations_total=simulations_total,
        drafts_created=sum(
            start <= _instant(item["created_at"]) < end for item in candidates
        ),
        approvals_recorded=sum(item["event_type"] == "approved" for item in activity),
        manually_recorded_applied=tracker_counts.get("applied", 0),
        interviews_recorded=tracker_counts.get("interview", 0),
        confirmed_real_submissions=0,
    )
    day = generated_at.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    actions = []
    if summary["insufficient_information"]:
        actions.append("confirm_eligibility")
    for item in candidates:
        if item["workflow_state"] == "draft":
            actions.append("review_draft")
        if item["workflow_state"] == "reviewed":
            actions.append("approve_or_reject_review")
        if item["follow_up_on"] and item["follow_up_on"] <= day:
            actions.append("follow_up_due")
    current = {
        "as_of": generated_at.isoformat(),
        "historical_as_of_cutoff": False,
        "resumes": versions,
        "evidence": evidence,
        "candidacies": candidates,
        "candidacy_activity_in_window": activity,
        "tracker_status_counts": tracker_counts,
        "follow_up_actions": sorted(set(actions)),
        "submission_receipt_support": "not_implemented",
    }
    disk = shutil.disk_usage(home)
    operational = {
        "as_of": generated_at.isoformat(),
        "last_run": dict(last) if last else None,
        "enabled_sources": [
            {"provider": config.provider, "board": config.board}
            for config in configs
            if config.enabled
        ],
        "sources": sources,
        "http_states": http_states,
        "storage": {"status": "readable", "free_bytes": disk.free},
        "latest_backup": _latest_backup(home),
    }
    if operational["last_run"]:
        operational["last_run"]["reports"] = json.loads(
            operational["last_run"].pop("reports_json")
        )
    return {
        "summary": summary,
        "summary_scope": {
            "window_activity": [
                "new_vacancies",
                "evaluated_vacancies",
                "unchanged_observations",
                "provider_duplicates_avoided",
                "prepared_resume_versions",
                "local_simulations",
                "drafts_created",
                "approvals_recorded",
                *_CLASSIFICATIONS,
            ],
            "current_at_generation": [
                "resume_versions_total",
                "draft_candidacies",
                "reviewed_pending_approval",
                "local_active_approvals",
                "manually_recorded_applied",
                "interviews_recorded",
            ],
            "cumulative_at_generation": ["local_simulations_total"],
            "confirmed_real_submissions": "always_zero_no_transport_or_external_receipt_support",
        },
        "vacancies": list(new.values()),
        "evaluations": list(latest.values()),
        "current_state": current,
        "operational": operational,
    }


def _markdown(report):
    def escape(value):
        value = html.escape(str(value), quote=True)
        return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", value).replace("\n", " ")

    summary = report["summary"]
    lines = [
        f"# Búsqueda laboral — {report['report_date']}",
        "",
        f"Zona: {report['timezone']} · corte: {report['scheduled_at']}.",
        f"Ventana: {report['window']['start']} ≤ descubrimiento < {report['window']['end']}.",
        f"Generado: {report['generated_at']} · retraso: {report['delay_seconds']} segundos.",
        "",
        "Reporte privado local. No entregado a ChatGPT Work ni leído por el usuario.",
        "",
        f"Nuevas vacantes: {summary['new_vacancies']}",
        f"Prioridad alta: {summary['high_priority']} · media: {summary['medium_priority']}.",
        f"Elegibilidad pendiente: {summary['insufficient_information']}.",
        f"Descartadas: {summary['rejected']} · no elegibles: {summary['ineligible']}.",
        f"Envíos reales confirmados: {summary['confirmed_real_submissions']}",
        f"Simulaciones locales en la ventana: {summary['local_simulations']} · registradas manualmente como applied: {summary['manually_recorded_applied']}.",
        "",
        "## Vacantes descubiertas",
        "",
        "Los enlaces se validan por origen y estructura; no se comprobó vigencia independiente.",
        "",
    ]
    for item in report["vacancies"]:
        lines.append(
            f"- {escape(item['company'])} — {escape(item['title'])}; {escape(item['source'])}; {escape(item['discovered_at'])}"
        )
        if item["url"]:
            lines.append("  [Ver oferta](" + quote(item["url"], safe="/:?=&%") + ")")
    lines.extend(["", "## Compatibilidad", ""])
    for item in report["evaluations"]:
        lines.append(
            f"- Vacante {item['vacancy_id']} ({escape(item['job']['company'])} — {escape(item['job']['title'])}): {item['classification']}; motivos: {escape(', '.join(item['reason_codes'])) or 'sin exclusión confirmada'}."
        )
    current = report["current_state"]
    lines.extend(
        [
            "",
            "## CV, candidaturas y seguimiento",
            "",
            "Estado actual al generar, también en reportes recuperados; no reconstruye el pasado.",
            f"Versiones verificadas: {len(current['resumes'])}; evidencia: {current['evidence']['status']}.",
            f"Borradores: {summary['draft_candidacies']} · revisadas pendientes de aprobación: {summary['reviewed_pending_approval']} · aprobaciones activas locales: {summary['local_active_approvals']}.",
            f"Entrevistas registradas: {summary['interviews_recorded']}.",
        ]
    )
    for item in current["resumes"]:
        lines.append(
            f"- CV {item['version_id']} · SHA256 {item['sha256']} · {item['language']} · revisión: {escape(', '.join(item['review_status']))}."
        )
    for item in current["candidacies"]:
        lines.append(
            f"- Candidatura {item['id']}: {item['workflow_state']} / tracker {item['tracker_status']}; seguimiento {escape(item['follow_up_on'])}; resultado {escape(item['outcome'])}; siguiente paso {escape(item['next_step'])}."
        )
    lines.extend(
        [
            "",
            "## Salud operativa",
            "",
            f"Almacenamiento: {report['operational']['storage']['status']}; respaldo: {report['operational']['latest_backup']['status']}.",
            f"Fuentes habilitadas: {len(report['operational']['enabled_sources'])}; duplicados del proveedor evitados: {summary['provider_duplicates_avoided']}.",
            "Más evidencia operativa y estados de fuentes en report.json.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def _sync_directory(path):
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class DailyReports:
    def __init__(self, home, *, schedule=None, now=None):
        self.home = private_path(home)
        self.root = self.home / "reports"
        self.schedule = schedule or ReportSchedule()
        self.now = now or (lambda: datetime.now(UTC))

    def _policy(self, *, create):
        path = self.root / "schedule.json"
        if not path.exists():
            if not create:
                raise WorkflowError("report_not_found")
            write_private(
                path,
                canonical_json(self.schedule.policy).encode("utf-8"),
                overwrite=False,
            )
        payload = json.loads(read_private(path, 4096, harden=False).decode("utf-8"))
        if payload != self.schedule.policy:
            raise WorkflowError("report_schedule_changed")

    def _read(self, day):
        directory = private_directory(self.root / day.isoformat(), harden=False)
        try:
            manifest = json.loads(
                read_private(directory / "manifest.json", 4096, harden=False)
            )
            if (
                set(manifest) != {"format_version", "report_date", "files"}
                or manifest["format_version"] != 1
                or manifest["report_date"] != day.isoformat()
            ):
                raise ValueError()
            if set(manifest["files"]) != {"report.json", "report.md"}:
                raise ValueError()
            blobs = {
                name: read_private(directory / name, MAX_REPORT_BYTES, harden=False)
                for name in manifest["files"]
            }
            if any(
                hashlib.sha256(blob).hexdigest() != manifest["files"][name]
                for name, blob in blobs.items()
            ):
                raise ValueError()
            report = json.loads(blobs["report.json"])
            if (
                report["report_date"] != day.isoformat()
                or report["format_version"] != 1
                or report["timezone"] != self.schedule.timezone_name
                or report["scheduled_at"] != self.schedule.at
            ):
                raise ValueError()
            if {path.name for path in directory.iterdir()} != {
                "report.json",
                "report.md",
                "manifest.json",
            }:
                raise ValueError()
            return report
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            raise WorkflowError("report_integrity_error") from None

    def read(self, day, *, summary=False):
        try:
            day = _date(day)
            private_directory(self.root, harden=False)
            self._policy(create=False)
            report = self._read(day)
            if summary:
                return {
                    "report_date": report["report_date"],
                    "timezone": report["timezone"],
                    "generated_at": report["generated_at"],
                    "delayed": report["delayed"],
                    "counts": report["summary"],
                    "delivered": False,
                    "read": False,
                }
            return report
        except WorkflowError:
            raise
        except (OSError, ValueError, TypeError):
            raise WorkflowError("report_storage_error") from None

    def _publish(self, report):
        day = _date(report["report_date"])
        folder = self.root / day.isoformat()
        if os.path.lexists(folder):
            self._read(day)
            return False
        pending = private_directory(self.root / (".pending-" + uuid.uuid4().hex))
        try:
            blobs = {
                "report.json": canonical_json(report).encode("utf-8"),
                "report.md": _markdown(report),
            }
            if any(len(blob) > MAX_REPORT_BYTES for blob in blobs.values()):
                raise WorkflowError("report_output_limit")
            for name, blob in blobs.items():
                write_private(pending / name, blob, overwrite=False)
            manifest = {
                "format_version": 1,
                "report_date": day.isoformat(),
                "files": {
                    name: hashlib.sha256(blob).hexdigest()
                    for name, blob in blobs.items()
                },
            }
            write_private(
                pending / "manifest.json",
                canonical_json(manifest).encode("utf-8"),
                overwrite=False,
            )
            _sync_directory(pending)
            if os.path.lexists(folder):
                raise WorkflowError("report_publication_conflict")
            os.rename(pending, folder)
            _sync_directory(self.root)
            return True
        finally:
            if pending.exists():
                # Delete only this invocation's unpublished files, never historical data.
                for path in pending.iterdir():
                    path.unlink()
                pending.rmdir()

    def generate(self, *, start_date=None, max_reports=31, configs=()):
        require_dry_run()
        if type(max_reports) is not int or not 1 <= max_reports <= 366:
            raise WorkflowError("invalid_report_limit")
        start_date = _date(start_date) if start_date is not None else None
        now = _instant(self.now())
        try:
            private_directory(self.home)
            with RunLock(self.home / "automation.lock"):
                private_directory(self.root)
                self._policy(create=True)
                latest_due = self.schedule.latest_due(now)
                connection = sqlite_private(
                    self.home / "applications.sqlite3", read_only=True, timeout=0.1
                )
                try:
                    first_row = connection.execute(
                        "SELECT started_at FROM automation_runs ORDER BY julianday(started_at) LIMIT 1"
                    ).fetchone()
                    first = first_row[0] if first_row else None
                finally:
                    connection.close()
                first_day = self.schedule.containing_day(first) if first else latest_due
                earliest = start_date or min(first_day, latest_due)
                existing = []
                for path in self.root.iterdir():
                    if _DATE.fullmatch(path.name):
                        day = _date(path.name)
                        self._read(day)
                        existing.append(day)
                if existing and start_date is None:
                    earliest = min(earliest, min(existing))
                missing, reused = [], []
                current = earliest
                while current <= latest_due:
                    (reused if current in existing else missing).append(current)
                    current += timedelta(days=1)
                    if (current - earliest).days > 36600:
                        raise WorkflowError("report_history_limit")
                generated = []
                for day in missing[:max_reports]:
                    start, end = self.schedule.window(day)
                    delay = max(0, int((now - end).total_seconds()))
                    report = {
                        "format_version": 1,
                        "report_date": day.isoformat(),
                        "timezone": self.schedule.timezone_name,
                        "scheduled_at": self.schedule.at,
                        "window": {
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                            "end_exclusive": True,
                        },
                        "generated_at": now.isoformat(),
                        "delayed": delay > 60,
                        "delay_seconds": delay,
                        "delivery": {
                            "generated": True,
                            "stored": True,
                            "delivered": False,
                            "read": False,
                        },
                        **_snapshot(
                            self.home,
                            start,
                            end,
                            now,
                            configs,
                            self.schedule.timezone_name,
                        ),
                    }
                    self._publish(report)
                    generated.append(day.isoformat())
                return {
                    "generated": generated,
                    "reused": [day.isoformat() for day in reused],
                    "remaining": len(missing) - len(generated),
                    "delivered": False,
                    "submitted": False,
                }
        except WorkflowError:
            raise
        except (
            OSError,
            sqlite3.Error,
            ValueError,
            TypeError,
            KeyError,
            UnicodeError,
            AttributeError,
            RecursionError,
            OverflowError,
        ):
            raise WorkflowError("report_storage_error") from None
