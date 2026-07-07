"""Persistence for the last prediction and match state, keyed by event.

Lets the live loop decide whether a confident prediction can be skipped by
comparing the current probed state against the state the last prediction was
made on.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from src.prediction.live_decision import LastPrediction


@dataclass(frozen=True, slots=True)
class PredictionRow:
    """A persisted prediction with the state it was made on (for display)."""

    event_id: str
    predicted_result: str
    success_probability: int
    home_score: int
    away_score: int
    minute: int
    status: str
    updated_at: str
    rationale: str = ""
    evidence: list[str] = field(default_factory=list)
    over_under_result: str | None = None
    over_under_line: float | None = None
    over_under_probability: int | None = None


class PredictionRepository:
    """Read/write repository for the ``match_predictions`` table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize repository with active SQLite connection.

        Args:
            connection: SQLite connection with row factory configured.
        """

        self._connection = connection

    def get_last(self, event_id: str) -> LastPrediction | None:
        """Return the last persisted prediction for a match, or None.

        Args:
            event_id: ESPN event identifier.

        Returns:
            Last prediction with the state it was made on, when present.
        """

        row = self._connection.execute(
            """
            SELECT predicted_result, success_probability, home_score, away_score,
                   red_cards, cycles_since_full
            FROM match_predictions
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return LastPrediction(
            predicted_result=row["predicted_result"],
            success_probability=row["success_probability"],
            home_score=row["home_score"],
            away_score=row["away_score"],
            red_cards=row["red_cards"],
            cycles_since_full=row["cycles_since_full"],
        )

    def list_all(self) -> list[PredictionRow]:
        """Return every persisted prediction (for the predictions dashboard)."""

        rows = self._connection.execute(
            """
            SELECT event_id, predicted_result, success_probability, home_score,
                   away_score, minute, status, updated_at, rationale, evidence,
                   over_under_result, over_under_line, over_under_probability
            FROM match_predictions
            """
        ).fetchall()
        return [
            PredictionRow(
                event_id=row["event_id"],
                predicted_result=row["predicted_result"],
                success_probability=row["success_probability"],
                home_score=row["home_score"],
                away_score=row["away_score"],
                minute=row["minute"],
                status=row["status"],
                updated_at=row["updated_at"],
                rationale=row["rationale"] or "",
                evidence=self._decode_evidence(row["evidence"]),
                over_under_result=row["over_under_result"],
                over_under_line=row["over_under_line"],
                over_under_probability=row["over_under_probability"],
            )
            for row in rows
        ]

    @staticmethod
    def _decode_evidence(raw_evidence: str | None) -> list[str]:
        """Decode the JSON-encoded evidence list, tolerating bad/absent data."""

        if not raw_evidence:
            return []
        try:
            decoded = json.loads(raw_evidence)
        except (ValueError, TypeError):
            return []
        return decoded if isinstance(decoded, list) else []

    def upsert(
        self,
        event_id: str,
        predicted_result: str,
        success_probability: int,
        home_score: int,
        away_score: int,
        red_cards: int,
        minute: int,
        cycles_since_full: int,
        status: str,
        updated_at: datetime,
        rationale: str | None = None,
        evidence: list[str] | None = None,
        over_under_result: str | None = None,
        over_under_line: float | None = None,
        over_under_probability: int | None = None,
    ) -> None:
        """Insert or update the prediction/state row for one match.

        ``rationale``, ``evidence`` and the ``over_under_*`` fields are only
        supplied on a fresh prediction. On skip/done cycles they are passed as
        ``None`` and preserved (via ``COALESCE``), so the reasoning and the
        Over/Under pick stay visible while the state updates.
        """

        encoded_evidence = None if evidence is None else json.dumps(
            evidence, ensure_ascii=False
        )
        self._connection.execute(
            """
            INSERT INTO match_predictions (
                event_id, predicted_result, success_probability, home_score,
                away_score, red_cards, minute, cycles_since_full, status,
                updated_at, rationale, evidence, over_under_result,
                over_under_line, over_under_probability
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                predicted_result=excluded.predicted_result,
                success_probability=excluded.success_probability,
                home_score=excluded.home_score,
                away_score=excluded.away_score,
                red_cards=excluded.red_cards,
                minute=excluded.minute,
                cycles_since_full=excluded.cycles_since_full,
                status=excluded.status,
                updated_at=excluded.updated_at,
                rationale=COALESCE(excluded.rationale, match_predictions.rationale),
                evidence=COALESCE(excluded.evidence, match_predictions.evidence),
                over_under_result=COALESCE(
                    excluded.over_under_result, match_predictions.over_under_result),
                over_under_line=COALESCE(
                    excluded.over_under_line, match_predictions.over_under_line),
                over_under_probability=COALESCE(
                    excluded.over_under_probability,
                    match_predictions.over_under_probability)
            """,
            (
                event_id,
                predicted_result,
                success_probability,
                home_score,
                away_score,
                red_cards,
                minute,
                cycles_since_full,
                status,
                updated_at.isoformat(),
                rationale,
                encoded_evidence,
                over_under_result,
                over_under_line,
                over_under_probability,
            ),
        )
