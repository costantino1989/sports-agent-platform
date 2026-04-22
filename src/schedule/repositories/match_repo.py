"""Match persistence repository for scheduler module."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.models.schedule import MatchScheduleRecord, MatchSnapshotRecord


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
                kickoff_iso = record.kickoff_utc.astimezone(ZoneInfo("Europe/Rome")).isoformat()
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

    def add_snapshot(self, snapshot: MatchSnapshotRecord) -> None:
        """Insert one append-only match snapshot row.

        Args:
            snapshot: Snapshot row to append.
        """

        self._connection.execute(
            """
            INSERT INTO match_snapshots (
                event_id, captured_at, status_state, minute, home_score, away_score,
                source, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.event_id,
                snapshot.captured_at.isoformat(),
                snapshot.status_state,
                snapshot.minute,
                snapshot.home_score,
                snapshot.away_score,
                snapshot.source,
                snapshot.payload_json,
            ),
        )

    def add_odds_snapshot(
        self,
        event_id: str,
        captured_at: datetime,
        provider: str,
        snapshot_type: str,
        home_odds: float | None,
        draw_odds: float | None,
        away_odds: float | None,
        payload_json: str,
    ) -> None:
        """Insert one append-only odds snapshot row.

        Args:
            event_id: ESPN event identifier.
            captured_at: Snapshot capture timestamp.
            provider: Odds provider label.
            snapshot_type: Odds snapshot type (Current/Open/Close).
            home_odds: Decimal home odds.
            draw_odds: Decimal draw odds.
            away_odds: Decimal away odds.
            payload_json: Serialized raw row payload.
        """

        self._connection.execute(
            """
            INSERT INTO odds_snapshots (
                event_id, captured_at, provider, snapshot_type,
                home_odds, draw_odds, away_odds, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                captured_at.isoformat(),
                provider,
                snapshot_type,
                home_odds,
                draw_odds,
                away_odds,
                payload_json,
            ),
        )

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

