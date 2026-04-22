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
    finished_in TEXT NULL,
    error TEXT NULL,
    UNIQUE(event_id, run_type),
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
