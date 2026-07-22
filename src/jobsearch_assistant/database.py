from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ApplicationRecord, EvaluationResult, JobPosting, VALID_STATUSES

SCHEMA_VERSION = 1


class ApplicationDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    score INTEGER NOT NULL,
                    recommendation TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'saved',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_applications_status
                ON applications(status);

                CREATE INDEX IF NOT EXISTS idx_applications_company_title
                ON applications(company, title);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def add(self, record: ApplicationRecord) -> int:
        if record.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {record.status}")
        payload = json.dumps(record.evaluation.to_dict(), ensure_ascii=False)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO applications(
                    title, company, location, url, description,
                    score, recommendation, evaluation_json,
                    status, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job.title,
                    record.job.company,
                    record.job.location,
                    record.job.url,
                    record.job.description,
                    record.evaluation.score,
                    record.evaluation.recommendation,
                    payload,
                    record.status,
                    record.notes,
                    record.created_at,
                    record.updated_at,
                ),
            )
            return int(cursor.lastrowid)

    def list(self, status: str | None = None) -> list[ApplicationRecord]:
        query = "SELECT * FROM applications"
        params: tuple[Any, ...] = ()
        if status:
            if status not in VALID_STATUSES:
                raise ValueError(f"Invalid status: {status}")
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY updated_at DESC, id DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def update(self, record_id: int, status: str | None = None, notes: str | None = None) -> bool:
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        assignments: list[str] = []
        values: list[Any] = []
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
        if notes is not None:
            assignments.append("notes = ?")
            values.append(notes)
        if not assignments:
            return False
        assignments.append("updated_at = ?")
        values.append(datetime.now(timezone.utc).isoformat(timespec="seconds"))
        values.append(record_id)
        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE applications SET {', '.join(assignments)} WHERE id = ?",
                tuple(values),
            )
            return cursor.rowcount > 0

    def update_status(self, record_id: int, status: str) -> bool:
        return self.update(record_id, status=status)

    def find_duplicate(self, job: JobPosting) -> int | None:
        with self.connect() as connection:
            if job.url.strip():
                row = connection.execute(
                    "SELECT id FROM applications WHERE lower(trim(url)) = lower(trim(?)) LIMIT 1",
                    (job.url,),
                ).fetchone()
                if row:
                    return int(row["id"])
            row = connection.execute(
                """
                SELECT id FROM applications
                WHERE lower(trim(company)) = lower(trim(?))
                  AND lower(trim(title)) = lower(trim(?))
                LIMIT 1
                """,
                (job.company, job.title),
            ).fetchone()
            return int(row["id"]) if row else None

    def summary(self) -> dict[str, int]:
        result = {status: 0 for status in VALID_STATUSES}
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM applications GROUP BY status"
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        for row in rows:
            result[row["status"]] = int(row["count"])
        result["total"] = int(total)
        return result

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ApplicationRecord:
        evaluation_data = json.loads(row["evaluation_json"])
        evaluation = EvaluationResult(**evaluation_data)
        job = JobPosting(
            title=row["title"],
            company=row["company"],
            location=row["location"],
            url=row["url"],
            description=row["description"],
        )
        return ApplicationRecord(
            id=int(row["id"]),
            job=job,
            evaluation=evaluation,
            status=row["status"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
