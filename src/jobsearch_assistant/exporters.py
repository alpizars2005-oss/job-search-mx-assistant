from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

from .models import ApplicationRecord
from .private_storage import write_private


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value):
    """Return spreadsheet-safe CSV text without mutating stored application data."""
    if not isinstance(value, str):
        return value
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def export_csv(records: list[ApplicationRecord], output: Path) -> Path:
    with StringIO(newline='') as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "title",
                "company",
                "location",
                "url",
                "score",
                "recommendation",
                "status",
                "matched_skills",
                "missing_skills",
                "risks",
                "notes",
                "created_at",
                "updated_at",
            ],
        )
        writer.writeheader()
        for record in records:
            row = {
                "id": record.id,
                "title": record.job.title,
                "company": record.job.company,
                "location": record.job.location,
                "url": record.job.url,
                "score": record.evaluation.score,
                "recommendation": record.evaluation.recommendation,
                "status": record.status,
                "matched_skills": "; ".join(record.evaluation.matched_skills),
                "missing_skills": "; ".join(record.evaluation.missing_skills),
                "risks": "; ".join(record.evaluation.risks),
                "notes": record.notes,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
            writer.writerow({key: _csv_safe(value) for key, value in row.items()})
        write_private(output, handle.getvalue().encode('utf-8-sig'))
    return output


def export_json(records: list[ApplicationRecord], output: Path) -> Path:
    payload = []
    for record in records:
        payload.append(
            {
                "id": record.id,
                "job": {
                    "title": record.job.title,
                    "company": record.job.company,
                    "location": record.job.location,
                    "url": record.job.url,
                    "description": record.job.description,
                },
                "evaluation": record.evaluation.to_dict(),
                "status": record.status,
                "notes": record.notes,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )
    write_private(output, json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8'))
    return output
