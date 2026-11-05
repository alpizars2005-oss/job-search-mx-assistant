"""Daily private report commands; generating never transmits report content."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .automation_cli import _private_home
from .daily_reports import DailyReports, ReportSchedule
from .sources.config import load_source_config
from .workflow_contracts import WorkflowError


def add_report_parsers(sub):
    reports = sub.add_parser(
        "reports", help="Generate or inspect immutable private daily reports"
    )
    commands = reports.add_subparsers(dest="report_command", required=True)
    generate = commands.add_parser(
        "generate", help="Recover due daily reports locally; never sends anything"
    )
    generate.add_argument("--config", type=Path)
    generate.add_argument(
        "--start-date", help="First due local date YYYY-MM-DD to recover"
    )
    generate.add_argument("--max-reports", type=int, default=31)
    show = commands.add_parser(
        "show", help="Read private local report; --summary prints only aggregate counts"
    )
    show.add_argument("date")
    show.add_argument("--summary", action="store_true")
    for command in (generate, show):
        command.add_argument("--timezone", default="America/Mexico_City")
        command.add_argument(
            "--at",
            default="14:00",
            help="Daily local cutoff HH:MM; immutable once initialized",
        )


def dispatch_reports(args):
    try:
        schedule = ReportSchedule(timezone_name=args.timezone, at=args.at)
        reports = DailyReports(_private_home(), schedule=schedule)
        if args.report_command == "generate":
            configs, _ = load_source_config(args.config)
            result = reports.generate(
                start_date=args.start_date,
                max_reports=args.max_reports,
                configs=configs,
            )
        else:
            result = reports.read(args.date, summary=args.summary)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except WorkflowError as error:
        print(json.dumps({"error": error.code}), file=sys.stderr)
        return 3 if error.code == "run_locked" else 2
    except KeyboardInterrupt:
        print(json.dumps({"error": "report_interrupted"}), file=sys.stderr)
        return 130
    except (OSError, ValueError, TypeError):
        print(json.dumps({"error": "report_storage_error"}), file=sys.stderr)
        return 2
