"""Persistence for the latest live-cycle decision per match.

Every live-tracking cycle classifies each started match (predicted, skipped with
a reason, done). The betting/prediction tables only record matches that produced
a prediction, so a match skipped for *no play-by-play* leaves no trace anywhere.
This table keeps the last decision for every event so the "today" dashboard page
can show, per match, whether it was skipped and why.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MatchStatus:
    """The latest live-cycle decision for one match."""

    action: str
    reason: str
    updated_at: str


class StatusRepository:
    """Read/write repository for the ``match_status`` table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize repository with active SQLite connection.

        Args:
            connection: SQLite connection with row factory configured.
        """

        self._connection = connection

    def upsert(
        self, event_id: str, action: str, reason: str, updated_at: datetime
    ) -> None:
        """Insert or update the latest decision for one match.

        Args:
            event_id: ESPN event identifier.
            action: Cycle action (``predict`` / ``skip`` / ``done``).
            reason: Machine-readable reason for the action.
            updated_at: Timestamp of the decision.
        """

        self._connection.execute(
            """
            INSERT INTO match_status (event_id, action, reason, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                action=excluded.action,
                reason=excluded.reason,
                updated_at=excluded.updated_at
            """,
            (event_id, action, reason, updated_at.isoformat()),
        )

    def list_all(self) -> dict[str, MatchStatus]:
        """Return the latest decision for every match, keyed by event id.

        Returns:
            Mapping of event id to its latest :class:`MatchStatus`.
        """

        rows = self._connection.execute(
            "SELECT event_id, action, reason, updated_at FROM match_status"
        ).fetchall()
        return {
            row["event_id"]: MatchStatus(
                action=row["action"],
                reason=row["reason"],
                updated_at=row["updated_at"],
            )
            for row in rows
        }
