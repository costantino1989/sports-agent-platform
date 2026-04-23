"""Scheduled run repository with claim and completion operations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.models.schedule import RunStatus, RunType, ScheduledRunRecord

RUN_OFFSETS_MINUTES: tuple[tuple[RunType, int], ...] = (
    ("minute30", 30),
    ("minute60", 60),
)


class RunRepository:
    """Read/write repository for `scheduled_runs` and `run_attempts` tables."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize repository with active SQLite connection."""

        self._connection = connection

    def ensure_runs_for_match(self, event_id: str, kickoff_utc: datetime) -> int:
        """Ensure minute-30 and minute-60 rows exist for one match.

        Args:
            event_id: ESPN event identifier.
            kickoff_utc: Kickoff UTC datetime.

        Returns:
            Number of newly inserted runs.
        """

        created = 0
        for run_type, offset_minutes in RUN_OFFSETS_MINUTES:
            scheduled_for = kickoff_utc + timedelta(minutes=offset_minutes)
            try:
                scheduled_iso = scheduled_for.astimezone(ZoneInfo("Europe/Rome")).isoformat()
            except Exception:
                scheduled_iso = scheduled_for.isoformat()
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO scheduled_runs (
                    event_id, run_type, scheduled_for_utc, status, finished_in, error
                ) VALUES (?, ?, ?, 'pending', 0, NULL)
                """,
                (event_id, run_type, scheduled_iso),
            )
            if cursor.rowcount > 0:
                created += 1
        return created

    def mark_done(self, run_id: int, finished_in: int) -> None:
        """Mark one run as done."""

        self._connection.execute(
            """
            UPDATE scheduled_runs
            SET status = 'done',
                finished_in = ?,
                error = NULL
            WHERE id = ?
            """,
            (finished_in, run_id),
        )

    def mark_failed(
            self,
            run_id: int,
            error: str,
            max_attempts: int,
    ) -> RunStatus:
        """Mark one run as failed or requeue pending when retry is allowed.

        Args:
            run_id: Scheduled run identifier.
            error: Error text.
            max_attempts: Maximum allowed attempts.

        Returns:
            Persisted terminal status (`pending` when requeued, `failed` otherwise).
        """

        row = self._connection.execute(
            "SELECT attempt_count FROM scheduled_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return "failed"
        status: RunStatus = "failed"
        if row["attempt_count"] < max_attempts:
            status = "pending"
        self._connection.execute(
            """
            UPDATE scheduled_runs
            SET status = ?,
                error = ?
            WHERE id = ?
            """,
            (status, error[:2000], run_id),
        )
        return status

    def mark_skipped(
            self,
            run_id: int,
            reason: str,
    ) -> None:
        """Mark one run as skipped."""

        self._connection.execute(
            """
            UPDATE scheduled_runs
            SET status = 'skipped',
                error = ?
            WHERE id = ?
            """,
            (reason[:2000], run_id),
        )

    def _map_run_row(self, row: sqlite3.Row) -> ScheduledRunRecord:
        """Map SQLite row to scheduled run dataclass."""

        return ScheduledRunRecord(
            run_id=row["id"],
            event_id=row["event_id"],
            run_type=row["run_type"],
            scheduled_for_utc=self._parse_iso_datetime(row["scheduled_for_utc"]),
            status=row["status"],

            finished_at=self._parse_nullable_datetime(row["finished_at"]),
            error=row["error"],
        )

    @staticmethod
    def _parse_iso_datetime(raw_value: str) -> datetime:
        """Parse non-null ISO datetime from DB text column."""

        parsed = datetime.fromisoformat(raw_value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _parse_nullable_datetime(self, raw_value: str | None) -> datetime | None:
        """Parse nullable ISO datetime from DB text column."""

        if raw_value is None:
            return None
        return self._parse_iso_datetime(raw_value)
