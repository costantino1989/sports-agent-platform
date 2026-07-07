"""Persistence for locked bets and their settlement, keyed by event.

A bet is locked once the prediction is confident enough; it is then left alone
until the match finishes and it is settled (won/lost) against the final score.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Bet:
    """A locked bet and, once the match ends, its settlement."""

    event_id: str
    predicted_result: str
    model_prob: int
    odds: float | None
    locked_minute: int
    final_home: int | None
    final_away: int | None
    outcome: str | None
    settled: bool
    rationale: str | None = None
    evidence: list[str] = field(default_factory=list)
    bookmaker: str | None = None
    synthetic: bool = False


class BetRepository:
    """Read/write repository for the ``match_bets`` table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize repository with active SQLite connection.

        Args:
            connection: SQLite connection with row factory configured.
        """

        self._connection = connection

    def is_locked(self, event_id: str) -> bool:
        """Return whether a bet has already been locked for a match."""

        row = self._connection.execute(
            "SELECT 1 FROM match_bets WHERE event_id = ?", (event_id,)
        ).fetchone()
        return row is not None

    def lock(
        self,
        event_id: str,
        predicted_result: str,
        model_prob: int,
        odds: float | None,
        minute: int,
        locked_at: datetime,
        rationale: str | None = None,
        evidence: list[str] | None = None,
        bookmaker: str | None = None,
        synthetic: bool = False,
    ) -> None:
        """Record a locked, unsettled bet for a match (with its analysis).

        ``synthetic`` marks a bet priced with a conservative placeholder odds
        (no real bookmaker available) so it can be reported separately.
        """

        self._connection.execute(
            """
            INSERT OR IGNORE INTO match_bets (
                event_id, predicted_result, model_prob, odds, locked_minute,
                locked_at, final_home, final_away, outcome, settled, rationale,
                evidence, bookmaker, synthetic
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, ?, ?, ?, ?)
            """,
            (
                event_id,
                predicted_result,
                model_prob,
                odds,
                minute,
                locked_at.isoformat(),
                rationale,
                json.dumps(evidence or [], ensure_ascii=False),
                bookmaker,
                1 if synthetic else 0,
            ),
        )

    def settle(
        self, event_id: str, final_home: int, final_away: int, outcome: str
    ) -> None:
        """Record the final score and won/lost outcome of a locked bet."""

        self._connection.execute(
            """
            UPDATE match_bets
            SET final_home = ?, final_away = ?, outcome = ?, settled = 1
            WHERE event_id = ?
            """,
            (final_home, final_away, outcome, event_id),
        )

    def get(self, event_id: str) -> Bet | None:
        """Return the bet for a match, or None when none is locked."""

        row = self._connection.execute(
            "SELECT * FROM match_bets WHERE event_id = ?", (event_id,)
        ).fetchone()
        return self._to_bet(row) if row is not None else None

    def list_settled(self) -> list[Bet]:
        """Return all settled bets, oldest lock first."""

        rows = self._connection.execute(
            "SELECT * FROM match_bets WHERE settled = 1 ORDER BY locked_at"
        ).fetchall()
        return [self._to_bet(row) for row in rows]

    def list_all(self) -> list[Bet]:
        """Return all locked bets (settled and pending), oldest lock first."""

        rows = self._connection.execute(
            "SELECT * FROM match_bets ORDER BY locked_at"
        ).fetchall()
        return [self._to_bet(row) for row in rows]

    @staticmethod
    def _to_bet(row: sqlite3.Row) -> Bet:
        """Map a row to a :class:`Bet`."""

        raw_evidence = row["evidence"]
        try:
            evidence = json.loads(raw_evidence) if raw_evidence else []
        except (ValueError, TypeError):
            evidence = []
        return Bet(
            event_id=row["event_id"],
            predicted_result=row["predicted_result"],
            model_prob=row["model_prob"],
            odds=row["odds"],
            locked_minute=row["locked_minute"],
            final_home=row["final_home"],
            final_away=row["final_away"],
            outcome=row["outcome"],
            settled=bool(row["settled"]),
            rationale=row["rationale"],
            evidence=evidence if isinstance(evidence, list) else [],
            bookmaker=row["bookmaker"],
            synthetic=bool(row["synthetic"]),
        )
