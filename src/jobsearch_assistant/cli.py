from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .config import (
    data_home,
    database_path,
    ensure_workspace,
    load_profile,
    load_settings,
    save_settings,
)
from .database import ApplicationDatabase
from .evaluator import evaluate_job
from .exporters import export_csv, export_json
from .models import VALID_STATUSES, ApplicationRecord, JobPosting
from .search_queries import build_browser_urls, build_search_queries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobsearch", description="Bilingual job-search assistant")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="Create the local workspace")
    init_parser.add_argument("--language", choices=("en", "es"), default="es")

    analyze = sub.add_parser("analyze", help="Analyze a job posting from a text file")
    analyze.add_argument("file", type=Path)
    analyze.add_argument("--title", default="Untitled role")
    analyze.add_argument("--company", default="Unknown company")
    analyze.add_argument("--location", default="")
    analyze.add_argument("--url", default="")
    analyze.add_argument("--save", action="store_true")
    analyze.add_argument("--json", action="store_true", dest="as_json")
    analyze.add_argument("--language", choices=("es", "en"), help="Override the saved UI language")

    applications = sub.add_parser("applications", help="Manage tracked applications")
    app_sub = applications.add_subparsers(dest="application_command", required=True)
    app_list = app_sub.add_parser("list", help="List applications")
    app_list.add_argument("--status", choices=VALID_STATUSES)
    app_update = app_sub.add_parser("update", help="Update application status")
    app_update.add_argument("id", type=int)
    app_update.add_argument("--status", choices=VALID_STATUSES)
    app_update.add_argument("--notes")

    profile = sub.add_parser("profile", help="Show, import, or export the local profile")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    profile_sub.add_parser("show")
    profile_import = profile_sub.add_parser("import")
    profile_import.add_argument("file", type=Path)
    profile_export = profile_sub.add_parser("export")
    profile_export.add_argument("file", type=Path)

    export = sub.add_parser("export", help="Export tracked applications")
    export.add_argument("--format", choices=("csv", "json"), required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--status", choices=VALID_STATUSES)

    search = sub.add_parser("search-queries", help="Generate safe portal search queries")
    search.add_argument("--portal", default="linkedin")
    search.add_argument("--urls", action="store_true")

    settings = sub.add_parser("settings", help="Change application settings")
    settings.add_argument("--language", choices=("en", "es"), required=True)

    discover = sub.add_parser("discover", help="Read explicitly enabled public ATS job boards")
    discover.add_argument("--config", type=Path, help="Separate JSON source configuration")
    discover.add_argument("--language", choices=("es", "en"), default="es")
    discover.add_argument("--save", action="store_true", help="Persist and evaluate discovered vacancies locally")

    vacancies = sub.add_parser("vacancies", help="Read or evaluate stored source vacancies offline")
    vacancy_sub = vacancies.add_subparsers(dest="vacancy_command", required=True)
    vacancy_sub.add_parser("list", help="List normalized vacancies as JSON")
    vacancy_evaluate = vacancy_sub.add_parser("evaluate", help="Evaluate a stored vacancy with the current profile")
    vacancy_evaluate.add_argument("id", type=int)
    vacancy_evaluate.add_argument("--json", action="store_true", dest="as_json")
    vacancy_evaluate.add_argument("--language", choices=("es", "en"))

    database = sub.add_parser("database", help="Create consistent backups or restore to a new file")
    database_sub = database.add_subparsers(dest="database_command", required=True)
    for name in ("backup", "restore"):
        operation = database_sub.add_parser(name)
        operation.add_argument("--source", type=Path, required=True)
        operation.add_argument("--output", type=Path, required=True, help="Must not already exist")

    sub.add_parser("doctor", help="Check the local installation")
    sub.add_parser("gui", help="Open the desktop interface")
    return parser


def _db() -> ApplicationDatabase:
    ensure_workspace()
    return ApplicationDatabase(database_path())


def command_init(args: argparse.Namespace) -> int:
    home = ensure_workspace(args.language)
    save_settings({"language": args.language})
    _db()
    print(f"Workspace: {home}")
    return 0


def command_analyze(args: argparse.Namespace) -> int:
    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 2
    description = args.file.read_text(encoding="utf-8", errors="replace")
    job = JobPosting(
        title=args.title,
        company=args.company,
        location=args.location,
        url=args.url,
        description=description,
    )
    result = evaluate_job(load_profile(), job)
    if args.as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        from .matching import explain_evaluation

        print(explain_evaluation(result, args.language or load_settings()["language"]))
    if args.save:
        database = _db()
        duplicate_id = database.find_duplicate(job)
        if duplicate_id is not None:
            print(f"Duplicate application already exists: #{duplicate_id}",
                  file=sys.stderr if args.as_json else sys.stdout)
        else:
            record_id = database.add(ApplicationRecord(id=None, job=job, evaluation=result))
            print(f"Saved application #{record_id}", file=sys.stderr if args.as_json else sys.stdout)
    return 0


def command_applications(args: argparse.Namespace) -> int:
    database = _db()
    if args.application_command == "list":
        records = database.list(args.status)
        if not records:
            print("No applications found.")
            return 0
        print("ID | Score | Status | Company | Title")
        print("-" * 72)
        for item in records:
            print(
                f"{item.id} | {item.evaluation.score:>3} | {item.status:<10} | "
                f"{item.job.company} | {item.job.title}"
            )
        return 0
    if args.status is None and args.notes is None:
        print("Provide --status and/or --notes.", file=sys.stderr)
        return 2
    updated = database.update(args.id, status=args.status, notes=args.notes)
    if not updated:
        print(f"Application not found: {args.id}", file=sys.stderr)
        return 2
    changes = []
    if args.status is not None:
        changes.append(f"status={args.status}")
    if args.notes is not None:
        changes.append("notes=updated")
    print(f"Application #{args.id}: {', '.join(changes)}")
    return 0


def command_profile(args: argparse.Namespace) -> int:
    from .config import profile_path, save_profile
    from .models import CandidateProfile

    if args.profile_command == "show":
        print(json.dumps(load_profile().to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.profile_command == "import":
        if not args.file.exists():
            print(f"File not found: {args.file}", file=sys.stderr)
            return 2
        try:
            payload = json.loads(args.file.read_text(encoding="utf-8"))
            save_profile(CandidateProfile.from_dict(payload))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"Invalid profile: {exc}", file=sys.stderr)
            return 2
        print(profile_path())
        return 0
    output = args.file
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(load_profile().to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(output.resolve())
    return 0


def command_export(args: argparse.Namespace) -> int:
    records = _db().list(args.status)
    output = export_csv(records, args.output) if args.format == "csv" else export_json(records, args.output)
    print(output.resolve())
    return 0


def command_search_queries(args: argparse.Namespace) -> int:
    profile = load_profile()
    values = build_browser_urls(profile, args.portal) if args.urls else build_search_queries(profile)
    for value in values:
        print(value)
    return 0


def command_doctor() -> int:
    errors: list[str] = []
    try:
        home = ensure_workspace()
        settings = load_settings()
        database = _db()
        database.summary()
    except (OSError, ValueError, sqlite3.Error) as exc:
        errors.append(str(exc))
        home = data_home()
        settings = {"language": "unknown"}
    print(f"Python: {sys.version.split()[0]}")
    print(f"Platform: {platform.platform()}")
    print(f"Data home: {home}")
    print(f"Language: {settings['language']}")
    print(f"Status: {'FAIL' if errors else 'OK'}")
    for error in errors:
        print(f"- {error}")
    return 1 if errors else 0


def command_discover(args: argparse.Namespace) -> int:
    from .sources.config import load_source_config
    from .sources.discovery import DiscoveryEngine
    from .sources.http import SafeHttpClient

    try:
        configs, policy = load_source_config(args.config)
    except ValueError:
        message = ("Configuración de fuentes inválida" if args.language == "es"
                   else "Invalid source configuration")
        print(message, file=sys.stderr)
        return 2
    result = DiscoveryEngine(SafeHttpClient(policy)).run(configs)
    payload = result.to_dict()
    if args.save:
        from .matching import evaluate_match

        database, profile = _db(), load_profile()
        saved = []
        for job in result.jobs:
            vacancy_id = database.upsert_vacancy(job)
            evaluation = evaluate_match(profile, job)
            evaluation_id = database.save_evaluation(vacancy_id, profile, evaluation, job=job)
            saved.append({"vacancy_id": vacancy_id, "evaluation_id": evaluation_id,
                          "evaluation": evaluation.to_dict()})
        payload["saved"] = saved
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 1 if any(report.status in {"error", "paused", "partial"}
                    for report in result.reports) else 0


def command_vacancies(args: argparse.Namespace) -> int:
    from .matching import evaluate_match, explain_evaluation

    database = _db()
    if args.vacancy_command == "list":
        print(json.dumps(database.list_vacancies(), ensure_ascii=True, indent=2))
        return 0
    job = database.get_vacancy(args.id)
    if job is None:
        print(f"Vacancy not found / Vacante no encontrada: {args.id}", file=sys.stderr)
        return 2
    profile = load_profile()
    result = evaluate_match(profile, job)
    evaluation_id = database.save_evaluation(args.id, profile, result, job=job)
    if args.as_json:
        print(json.dumps({"vacancy_id": args.id, "evaluation_id": evaluation_id,
                          "evaluation": result.to_dict()}, ensure_ascii=True, indent=2))
    else:
        print(explain_evaluation(result, args.language or load_settings()["language"]))
        print(f"Evaluation / Evaluación #{evaluation_id}")
    return 0


def command_database(args: argparse.Namespace) -> int:
    from .migrations import backup_database, restore_backup

    operation = backup_database if args.database_command == "backup" else restore_backup
    output = operation(args.source, args.output)
    print(output.resolve())
    return 0


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        # Only --save opts in to private profile/database access.
        try:
            code = command_discover(args)
        except (OSError, ValueError, sqlite3.Error):
            print("Local persistence failed / Falló la persistencia local", file=sys.stderr)
            code = 2
        raise SystemExit(code)
    if args.command == "database":
        # Never initialize/migrate the source just to back it up or restore it.
        try:
            code = command_database(args)
        except (OSError, ValueError, sqlite3.Error):
            print("Backup/restore failed; use a valid source and a new destination. / "
                  "Falló el respaldo/restauración; usa un origen válido y un destino nuevo.", file=sys.stderr)
            code = 2
        raise SystemExit(code)
    ensure_workspace()
    if args.command == "init":
        code = command_init(args)
    elif args.command == "analyze":
        code = command_analyze(args)
    elif args.command == "applications":
        code = command_applications(args)
    elif args.command == "vacancies":
        try:
            code = command_vacancies(args)
        except (OSError, ValueError, sqlite3.Error):
            print("Local vacancy operation failed / Falló la operación local de vacantes", file=sys.stderr)
            code = 2
    elif args.command == "profile":
        code = command_profile(args)
    elif args.command == "export":
        code = command_export(args)
    elif args.command == "search-queries":
        code = command_search_queries(args)
    elif args.command == "settings":
        save_settings({"language": args.language})
        print(args.language)
        code = 0
    elif args.command == "doctor":
        code = command_doctor()
    elif args.command == "gui":
        from .gui import main as gui_main

        gui_main()
        code = 0
    else:
        code = 2
    raise SystemExit(code)
