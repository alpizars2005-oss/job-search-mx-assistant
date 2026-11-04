"""Transactional SQLite upgrades and consistent, non-overwriting snapshots."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SCHEMA_VERSION = 3


def backup_database(source: Path, destination: Path) -> Path:
    """Copy a committed SQLite snapshot, including WAL, to a new private file.

    The caller must not use a write-locked source connection for backup. A
    separate reader also lets a migration snapshot schema 1 while its writer
    reservation prevents another process from changing it.
    """
    source = Path(source).resolve(strict=True)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    reader = writer = None
    try:
        reader = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=30)
        writer = sqlite3.connect(destination, timeout=30)
        reader.backup(writer)
        if writer.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise sqlite3.DatabaseError('SQLite backup failed integrity verification')
        writer.close()
        writer = None
        return destination
    except BaseException:
        if writer is not None:
            writer.close()
            writer = None
        destination.unlink(missing_ok=True)
        raise
    finally:
        if writer is not None:
            writer.close()
        if reader is not None:
            reader.close()


def restore_backup(source: Path, destination: Path) -> Path:
    """Restore to a fresh destination; never replace a live or existing database."""
    return backup_database(source, destination)


def legacy_identity(url: str, company: str, title: str) -> str:
    """Normalize URL origin only: paths and queries can be case-sensitive."""
    if url.strip():
        try:
            parts = urlsplit(url.strip())
            normalized = urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                                     parts.path, parts.query, parts.fragment))
        except ValueError:
            normalized = url.strip()
        return json.dumps(['url', normalized], ensure_ascii=False)
    return json.dumps(['role', company.strip().casefold(), title.strip().casefold()],
                      ensure_ascii=False)


def _create_legacy_tables(connection: sqlite3.Connection) -> None:
    connection.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    connection.execute('''
        CREATE TABLE applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, company TEXT NOT NULL,
            location TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '', score INTEGER NOT NULL,
            recommendation TEXT NOT NULL, evaluation_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'saved', notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
    ''')
    connection.execute('CREATE INDEX idx_applications_status ON applications(status)')
    connection.execute('CREATE INDEX idx_applications_company_title ON applications(company, title)')


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    # Add tables only: historical IDs, JSON bytes and duplicates remain untouched.
    connection.execute('''
        CREATE TABLE application_identities (
            identity TEXT PRIMARY KEY,
            application_id INTEGER NOT NULL REFERENCES applications(id)
        )
    ''')
    connection.execute('''
        CREATE TABLE vacancies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL, source_board TEXT NOT NULL, source_job_id TEXT NOT NULL,
            job_json TEXT NOT NULL,
            UNIQUE(source, source_board, source_job_id)
        )
    ''')
    connection.execute('''
        CREATE TABLE evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vacancy_id INTEGER NOT NULL REFERENCES vacancies(id),
            algorithm_version TEXT NOT NULL, profile_fingerprint TEXT NOT NULL,
            input_fingerprint TEXT NOT NULL, job_snapshot_json TEXT NOT NULL,
            profile_snapshot_json TEXT NOT NULL, evaluation_json TEXT NOT NULL,
            UNIQUE(vacancy_id, algorithm_version, input_fingerprint)
        )
    ''')
    for row in connection.execute('SELECT id, url, company, title FROM applications ORDER BY id'):
        connection.execute(
            'INSERT OR IGNORE INTO application_identities(identity, application_id) VALUES (?, ?)',
            (legacy_identity(row[1], row[2], row[3]), row[0]),
        )


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    # All additions are independent of the unchanged historical tracker rows.
    connection.execute("""
        CREATE TABLE candidacies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL UNIQUE REFERENCES applications(id),
            vacancy_id INTEGER NOT NULL UNIQUE REFERENCES vacancies(id),
            resume_version_id TEXT NOT NULL,
            workflow_state TEXT NOT NULL CHECK(workflow_state IN ('draft','reviewed','approved','simulated')),
            revision INTEGER NOT NULL CHECK(revision >= 1),
            content TEXT NOT NULL, company TEXT NOT NULL,
            review_digest TEXT,
            outcome TEXT NOT NULL DEFAULT '', next_step TEXT NOT NULL DEFAULT '',
            follow_up_on TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE candidacy_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidacy_id INTEGER NOT NULL REFERENCES candidacies(id),
            revision INTEGER NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(candidacy_id, revision)
        )
    """)
    connection.execute("""
        CREATE TABLE candidacy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidacy_id INTEGER NOT NULL REFERENCES candidacies(id),
            revision INTEGER NOT NULL, event_type TEXT NOT NULL,
            snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE candidacy_authorizations (
            authorization_id TEXT PRIMARY KEY,
            candidacy_id INTEGER NOT NULL REFERENCES candidacies(id),
            revision INTEGER NOT NULL, review_digest TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active','invalidated','consumed')),
            created_at TEXT NOT NULL, consumed_at TEXT, receipt_json TEXT,
            UNIQUE(candidacy_id, revision)
        )
    """)
    for table in ('candidacy_revisions', 'candidacy_events'):
        for action in ('UPDATE', 'DELETE'):
            connection.execute(f"""
                CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table}
                BEGIN SELECT RAISE(ABORT, 'Immutable workflow history'); END
            """)
    connection.execute("""
        CREATE TRIGGER candidacy_authorizations_immutable_binding
        BEFORE UPDATE OF authorization_id, candidacy_id, revision, review_digest, snapshot_json, created_at
        ON candidacy_authorizations
        BEGIN SELECT RAISE(ABORT, 'Immutable authorization binding'); END
    """)
    connection.execute("""
        CREATE TRIGGER candidacy_authorizations_no_delete BEFORE DELETE ON candidacy_authorizations
        BEGIN SELECT RAISE(ABORT, 'Immutable authorization history'); END
    """)
    connection.execute("""
        CREATE TRIGGER candidacy_authorizations_terminal
        BEFORE UPDATE ON candidacy_authorizations WHEN OLD.status != 'active'
        BEGIN SELECT RAISE(ABORT, 'Terminal authorization state'); END
    """)


def initialize_database(path: Path) -> None:
    """Serialize initializers and commit schema+version together, or change nothing."""
    path = Path(path)
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('BEGIN IMMEDIATE')
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        if not tables:
            _create_legacy_tables(connection)
            _migrate_v1_to_v2(connection)
            _migrate_v2_to_v3(connection)
            connection.execute("INSERT INTO meta VALUES ('schema_version', ?)",
                               (str(SCHEMA_VERSION),))
        else:
            if 'meta' not in tables:
                raise ValueError('Unrecognized SQLite schema: missing version marker')
            marker = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if marker is None or marker[0] not in ('1', '2', str(SCHEMA_VERSION)):
                raise ValueError('Unsupported SQLite schema version')
            if marker[0] in ('1', '2'):
                destination = path.with_name(path.name + '.schema' + marker[0] + '-' + uuid.uuid4().hex + '.bak')
                backup_database(path, destination)
                if marker[0] == '1':
                    _migrate_v1_to_v2(connection)
                _migrate_v2_to_v3(connection)
                connection.execute("UPDATE meta SET value=? WHERE key='schema_version'",
                                   (str(SCHEMA_VERSION),))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
