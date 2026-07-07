"""Match persistence repository for scheduler module."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.models.live_models import MatchRecordModel
from src.models.schedule import MatchScheduleRecord


class MatchRepository:
    """Read/write repository for `matches` and `match_snapshots` tables."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize repository with active SQLite connection.

        Args:
            connection: SQLite connection with row factory configured.
        """

        self._connection = connection

    def upsert_matches(self, records: list[MatchScheduleRecord]) -> int:
        """Insert or update scheduler match rows.

        Args:
            records: Match rows to upsert.

        Returns:
            Number of processed records.
        """

        if not records:
            return 0
        params: list[tuple] = []
        for record in records:
            try:
                kickoff_iso = record.kickoff_utc.astimezone(
                    ZoneInfo("Europe/Rome")
                ).isoformat()
            except Exception:
                kickoff_iso = record.kickoff_utc.isoformat()
            params.append(
                (
                    record.event_id,
                    record.league_slug,
                    record.league_name,
                    record.competition_id,
                    kickoff_iso,
                    record.home_team,
                    record.away_team,
                    record.payload_json,
                    record.updated_at.isoformat(),
                )
            )
        self._connection.executemany(
            """
            INSERT INTO matches (
                event_id, league_slug, league_name, competition_id, kickoff_utc,
                home_team, away_team, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                league_slug=excluded.league_slug,
                league_name=excluded.league_name,
                competition_id=excluded.competition_id,
                kickoff_utc=excluded.kickoff_utc,
                home_team=excluded.home_team,
                away_team=excluded.away_team,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            params,
        )
        return len(records)

    def count_matches(self) -> int:
        """Return the number of persisted match rows.

        Used as a cheap health check: an empty table means the scheduler never
        synced (fresh DB, manual wipe, or corruption), which the live-tracking
        flow can self-heal by triggering a sync instead of waiting for the next
        scheduled one.

        Returns:
            Total count of rows in the matches table.
        """

        row = self._connection.execute("SELECT COUNT(*) FROM matches").fetchone()
        return int(row[0]) if row is not None else 0

    def get_match(self, event_id: str) -> MatchScheduleRecord | None:
        """Fetch one persisted match by event id.

        Args:
            event_id: ESPN event identifier.

        Returns:
            Persisted match row when found.
        """

        row = self._connection.execute(
            """
            SELECT event_id, league_slug, league_name, competition_id, kickoff_utc,
                   home_team, away_team, payload_json, updated_at
            FROM matches
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return MatchScheduleRecord(
            event_id=row["event_id"],
            league_slug=row["league_slug"],
            league_name=row["league_name"],
            competition_id=row["competition_id"],
            kickoff_utc=self._parse_iso_datetime(row["kickoff_utc"]),
            home_team=row["home_team"],
            away_team=row["away_team"],
            payload_json=row["payload_json"],
            updated_at=self._parse_iso_datetime(row["updated_at"]),
        )

    def list_scheduled_matches(self) -> list[MatchScheduleRecord]:
        """Return every persisted scheduled match, ordered by kickoff.

        Used by the "today" dashboard page to list the day's fixtures. Reuses the
        same lightweight row shape as :meth:`get_match`.

        Returns:
            All persisted match rows.
        """

        rows = self._connection.execute(
            """
            SELECT event_id, league_slug, league_name, competition_id, kickoff_utc,
                   home_team, away_team, payload_json, updated_at
            FROM matches
            ORDER BY kickoff_utc
            """
        ).fetchall()
        return [
            MatchScheduleRecord(
                event_id=row["event_id"],
                league_slug=row["league_slug"],
                league_name=row["league_name"],
                competition_id=row["competition_id"],
                kickoff_utc=self._parse_iso_datetime(row["kickoff_utc"]),
                home_team=row["home_team"],
                away_team=row["away_team"],
                payload_json=row["payload_json"],
                updated_at=self._parse_iso_datetime(row["updated_at"]),
            )
            for row in rows
        ]

    def get_match_record(self, event_id: str) -> MatchRecordModel | None:
        """Return the parsed match record for one event, ignoring any window.

        Unlike :meth:`get_started_matches`, this is not bounded by kickoff time,
        so a locked bet whose match has aged out of the active window can still
        be probed and settled.

        Args:
            event_id: ESPN event identifier.

        Returns:
            The parsed match record, or ``None`` when missing/unparsable.
        """

        row = self._connection.execute(
            "SELECT payload_json FROM matches WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return self._parse_match_payload(row["payload_json"])

    def get_started_matches(
        self, now_utc: datetime, active_window_hours: int | None = None
    ) -> list[MatchRecordModel]:
        """Return match records whose kickoff is at or before ``now_utc``.

        Used to build dossiers for matches that have already started, regardless
        of the 30'/60' checkpoints. Rows with missing or unparsable payloads are
        skipped.

        Args:
            now_utc: Current time in UTC.
            active_window_hours: When set, also exclude matches that kicked off
                more than this many hours ago (so finished matches are not
                re-probed indefinitely by the live loop).

        Returns:
            Match records for started matches.
        """

        earliest = (
            now_utc - timedelta(hours=active_window_hours)
            if active_window_hours is not None
            else None
        )
        rows = self._connection.execute(
            "SELECT kickoff_utc, payload_json FROM matches"
        ).fetchall()
        started: list[MatchRecordModel] = []
        for row in rows:
            try:
                kickoff = self._parse_iso_datetime(row["kickoff_utc"])
            except (ValueError, TypeError):
                continue
            if kickoff > now_utc:
                continue
            if earliest is not None and kickoff < earliest:
                continue
            match_model = self._parse_match_payload(row["payload_json"])
            if match_model is not None:
                started.append(match_model)
        return started

    @staticmethod
    def _parse_match_payload(raw_payload: str) -> MatchRecordModel | None:
        """Validate a stored match payload into a record, or ``None`` on error."""

        try:
            return MatchRecordModel.model_validate(json.loads(raw_payload))
        except (ValueError, TypeError):
            try:
                return MatchRecordModel.model_validate_json(raw_payload)
            except ValueError:
                return None

    @staticmethod
    def _parse_iso_datetime(raw_value: str) -> datetime:
        """Parse ISO datetime from DB text column.

        Args:
            raw_value: ISO datetime string.

        Returns:
            Timezone-aware UTC datetime.
        """

        parsed = datetime.fromisoformat(raw_value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
