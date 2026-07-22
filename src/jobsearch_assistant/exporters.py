from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import ApplicationRecord


def export_csv(records: list[ApplicationRecord], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
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
            writer.writerow(
                {
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
            )
    return output


def export_json(records: list[ApplicationRecord], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
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
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output
