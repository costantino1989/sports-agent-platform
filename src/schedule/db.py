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

CREATE TABLE IF NOT EXISTS match_predictions (
    event_id TEXT PRIMARY KEY,
    predicted_result TEXT NOT NULL,
    success_probability INTEGER NOT NULL,
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    red_cards INTEGER NOT NULL,
    minute INTEGER NOT NULL,
    cycles_since_full INTEGER NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rationale TEXT NULL,
    evidence TEXT NULL,
    over_under_result TEXT NULL,
    over_under_line REAL NULL,
    over_under_probability INTEGER NULL
);

CREATE TABLE IF NOT EXISTS match_bets (
    event_id TEXT PRIMARY KEY,
    predicted_result TEXT NOT NULL,
    model_prob INTEGER NOT NULL,
    odds REAL NULL,
    locked_minute INTEGER NOT NULL,
    locked_at TEXT NOT NULL,
    final_home INTEGER NULL,
    final_away INTEGER NULL,
    outcome TEXT NULL,
    settled INTEGER NOT NULL,
    rationale TEXT NULL,
    evidence TEXT NULL,
    bookmaker TEXT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS match_status (
    event_id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Idempotent column additions for databases created before these columns existed.
MIGRATIONS_SQL: tuple[str, ...] = (
    "ALTER TABLE match_bets ADD COLUMN rationale TEXT",
    "ALTER TABLE match_bets ADD COLUMN evidence TEXT",
    "ALTER TABLE match_bets ADD COLUMN bookmaker TEXT",
    "ALTER TABLE match_predictions ADD COLUMN rationale TEXT",
    "ALTER TABLE match_predictions ADD COLUMN evidence TEXT",
    "ALTER TABLE match_bets ADD COLUMN synthetic INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE match_predictions ADD COLUMN over_under_result TEXT",
    "ALTER TABLE match_predictions ADD COLUMN over_under_line REAL",
    "ALTER TABLE match_predictions ADD COLUMN over_under_probability INTEGER",
)


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
        connection.executescript(SCHEMA_SQL)
        for statement in MIGRATIONS_SQL:
            try:
                connection.execute(statement)
            except sqlite3.OperationalError:
                pass  # column already exists
        return connection
