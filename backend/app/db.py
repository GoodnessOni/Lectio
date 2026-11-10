"""SQLite persistence with a schema version table and a process write lock."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classes (
    id TEXT PRIMARY KEY,
    course_code TEXT NOT NULL,
    title TEXT NOT NULL,
    invite_token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
    class_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (class_id, display_name),
    FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lectures (
    id TEXT PRIMARY KEY,
    class_id TEXT NOT NULL,
    title TEXT NOT NULL,
    lecture_date TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_json TEXT,
    current_job_id TEXT,
    selection_json TEXT,
    cleanup_json TEXT,
    transcript_json TEXT,
    notes_json TEXT,
    questions_json TEXT,
    pending_recording_id TEXT,
    pending_mode TEXT,
    pending_explanation TEXT,
    export_size_bytes INTEGER,
    FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recordings (
    id TEXT PRIMARY KEY,
    lecture_id TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    file_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    duration_sec REAL NOT NULL,
    size_bytes INTEGER NOT NULL,
    quality_json TEXT,
    selected INTEGER NOT NULL DEFAULT 0,
    selection_reason TEXT,
    asset_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sort_index INTEGER NOT NULL,
    FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS photos (
    id TEXT PRIMARY KEY,
    lecture_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    timestamp_sec REAL NOT NULL,
    caption TEXT,
    asset_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    class_id TEXT NOT NULL,
    lecture_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    lecture_id TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    revision INTEGER NOT NULL,
    target_recording_id TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lectures_class ON lectures(class_id);
CREATE INDEX IF NOT EXISTS idx_recordings_lecture ON recordings(lecture_id);
CREATE INDEX IF NOT EXISTS idx_photos_lecture ON photos(lecture_id);
CREATE INDEX IF NOT EXISTS idx_jobs_lecture ON jobs(lecture_id);
CREATE INDEX IF NOT EXISTS idx_assets_class ON assets(class_id);
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None is autocommit. Critical sections use explicit BEGIN IMMEDIATE.
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


class QueryResult:
    """Snapshot of rows taken while the connection lock was held."""

    def __init__(self, rows: list[sqlite3.Row]):
        self._rows = list(rows)

    def fetchone(self) -> sqlite3.Row | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[sqlite3.Row]:
        return list(self._rows)


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.write_lock = threading.RLock()
        self._conn = _connect(path)
        self.migrate()

    def close(self) -> None:
        with self.write_lock:
            self._conn.close()

    def migrate(self) -> None:
        with self.write_lock:
            self._conn.executescript(SCHEMA)
            row = self._conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if row is None:
                from .ids import utc_now

                self._conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, utc_now()),
                )

    def execute(self, sql: str, params: Iterable[Any] = ()) -> "QueryResult":
        # Fetch immediately so no cursor is used after the connection lock is released.
        with self.write_lock:
            cur = self._conn.execute(sql, tuple(params))
            if cur.description is None:
                return QueryResult([])
            return QueryResult(cur.fetchall())

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> "QueryResult":
        with self.write_lock:
            cur = self._conn.executemany(sql, seq)
            if cur.description is None:
                return QueryResult([])
            return QueryResult(cur.fetchall())

    def commit(self) -> None:
        # Autocommit mode: kept for compatibility. Critical sections use COMMIT.
        with self.write_lock:
            try:
                self._conn.execute("COMMIT")
            except sqlite3.OperationalError:
                pass

    def immediate(self):
        return ImmediateTx(self)


class ImmediateTx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self) -> Database:
        self.db.write_lock.acquire()
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.db.execute("COMMIT")
            else:
                self.db.execute("ROLLBACK")
        finally:
            self.db.write_lock.release()


def dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)
