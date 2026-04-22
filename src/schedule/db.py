"""SQLite database utilities for scheduler persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS matches (
    event_id TEXT PRIMARY KEY,
    league_slug TEXT NOT NULL,
    league_name TEXT NOT NULL,
    competition_id TEXT NOT NULL,
    kickoff_utc TEXT NOT NULL,
    status_state TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    run_type TEXT NOT NULL,
    scheduled_for_utc TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    claimed_at TEXT NULL,
    finished_at TEXT NULL,
    error TEXT NULL,
    UNIQUE(event_id, run_type),
    FOREIGN KEY(event_id) REFERENCES matches(event_id)
);

CREATE TABLE IF NOT EXISTS run_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_run_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT NULL,
    output_path TEXT NULL,
    FOREIGN KEY(scheduled_run_id) REFERENCES scheduled_runs(id)
);

CREATE TABLE IF NOT EXISTS match_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    status_state TEXT NOT NULL,
    minute INTEGER NULL,
    home_score TEXT NULL,
    away_score TEXT NULL,
    source TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES matches(event_id)
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    snapshot_type TEXT NOT NULL,
    home_odds REAL NULL,
    draw_odds REAL NULL,
    away_odds REAL NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES matches(event_id)
);
"""


class ScheduleDatabase:
    """Handle SQLite connections and schema bootstrap for scheduler module."""

    def __init__(self, db_path: Path) -> None:
        """Initialize database path and ensure parent directory exists.

        Args:
            db_path: Target SQLite file path.
        """

        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        """Return configured SQLite file path."""

        return self._db_path

    def connect(self) -> sqlite3.Connection:
        """Open configured SQLite connection with row factory enabled."""

        connection = sqlite3.connect(self._db_path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA foreign_keys=ON;")
        connection.execute("PRAGMA busy_timeout=5000;")
        return connection

    def ensure_schema(self) -> None:
        """Create scheduler tables when missing."""

        with self.connect() as connection:
            connection.executescript(SCHEMA_SQL)

