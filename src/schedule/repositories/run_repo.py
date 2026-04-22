"""Scheduled run repository with claim and completion operations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.schedule.models import RunStatus, RunType, ScheduledRunRecord

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
                    event_id, run_type, scheduled_for_utc, status, attempt_count,
                    claimed_at, finished_at, error
                ) VALUES (?, ?, ?, 'pending', 0, NULL, NULL, NULL)
                """,
                (event_id, run_type, scheduled_iso),
            )
            if cursor.rowcount > 0:
                created += 1
        return created

    def claim_due_run(self, now_utc: datetime) -> ScheduledRunRecord | None:
        """Atomically claim one due pending run.

        Args:
            now_utc: Current UTC timestamp.

        Returns:
            Claimed run record when available.
        """

        claimed_at = now_utc.isoformat()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            now_param = now_utc.astimezone(ZoneInfo("Europe/Rome")).isoformat()
        except Exception:
            now_param = now_utc.isoformat()
        row = self._connection.execute(
            """
            SELECT id, event_id, run_type, scheduled_for_utc, status, attempt_count,
                   claimed_at, finished_at, error
            FROM scheduled_runs
            WHERE status = 'pending' AND scheduled_for_utc <= ?
            ORDER BY scheduled_for_utc ASC, id ASC
            LIMIT 1
            """,
            (now_param,),
        ).fetchone()
        if row is None:
            self._connection.execute("COMMIT")
            return None
        self._connection.execute(
            """
            UPDATE scheduled_runs
            SET status = 'running',
                claimed_at = ?,
                attempt_count = attempt_count + 1
            WHERE id = ?
            """,
            (claimed_at, row["id"]),
        )
        claimed = self._connection.execute(
            """
            SELECT id, event_id, run_type, scheduled_for_utc, status, attempt_count,
                   claimed_at, finished_at, error
            FROM scheduled_runs
            WHERE id = ?
            """,
            (row["id"],),
        ).fetchone()
        self._connection.execute("COMMIT")
        if claimed is None:
            return None
        return self._map_run_row(claimed)

    def mark_done(self, run_id: int, finished_at: datetime) -> None:
        """Mark one run as done."""

        self._connection.execute(
            """
            UPDATE scheduled_runs
            SET status = 'done',
                finished_at = ?,
                error = NULL
            WHERE id = ?
            """,
            (finished_at.isoformat(), run_id),
        )

    def mark_failed(
        self,
        run_id: int,
        finished_at: datetime,
        error: str,
        max_attempts: int,
    ) -> RunStatus:
        """Mark one run as failed or requeue pending when retry is allowed.

        Args:
            run_id: Scheduled run identifier.
            finished_at: Attempt completion timestamp.
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
                finished_at = ?,
                error = ?
            WHERE id = ?
            """,
            (status, finished_at.isoformat(), error[:2000], run_id),
        )
        return status

    def mark_skipped(
        self,
        run_id: int,
        finished_at: datetime,
        reason: str,
    ) -> None:
        """Mark one run as skipped."""

        self._connection.execute(
            """
            UPDATE scheduled_runs
            SET status = 'skipped',
                finished_at = ?,
                error = ?
            WHERE id = ?
            """,
            (finished_at.isoformat(), reason[:2000], run_id),
        )

    def add_attempt(
        self,
        run_id: int,
        started_at: datetime,
        finished_at: datetime,
        status: RunStatus,
        error: str | None,
        output_path: str | None,
    ) -> None:
        """Insert one attempt execution row for auditability."""

        self._connection.execute(
            """
            INSERT INTO run_attempts (
                scheduled_run_id, started_at, finished_at, status, error, output_path
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                started_at.isoformat(),
                finished_at.isoformat(),
                status,
                error[:2000] if error else None,
                output_path,
            ),
        )

    def recover_stale_running(self, now_utc: datetime, stale_minutes: int) -> int:
        """Requeue stale running jobs older than configured threshold.

        Args:
            now_utc: Current UTC timestamp.
            stale_minutes: Stale threshold in minutes.

        Returns:
            Number of rows moved back to pending.
        """

        stale_before = now_utc - timedelta(minutes=stale_minutes)
        cursor = self._connection.execute(
            """
            UPDATE scheduled_runs
            SET status = 'pending',
                error = COALESCE(error, 'Recovered stale running job'),
                claimed_at = NULL
            WHERE status = 'running' AND claimed_at IS NOT NULL AND claimed_at < ?
            """,
            (stale_before.isoformat(),),
        )
        return cursor.rowcount

    def _map_run_row(self, row: sqlite3.Row) -> ScheduledRunRecord:
        """Map SQLite row to scheduled run dataclass."""

        return ScheduledRunRecord(
            run_id=row["id"],
            event_id=row["event_id"],
            run_type=row["run_type"],
            scheduled_for_utc=self._parse_iso_datetime(row["scheduled_for_utc"]),
            status=row["status"],
            attempt_count=int(row["attempt_count"]),
            claimed_at=self._parse_nullable_datetime(row["claimed_at"]),
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

