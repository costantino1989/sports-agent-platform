"""Build the data for the predictions dashboard page (one card per prediction).

Turns persisted predictions (``match_predictions``) into cards: the model's 1X2
pick, its confidence, and the score/minute the call was made on. Where a bet was
locked for the match, its stored rationale/evidence enrich the card's analysis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.schedule.repositories.prediction_repo import PredictionRow


def build_predictions_data(
    predictions: list["PredictionRow"],
    matches_meta: dict[str, dict[str, Any]],
    bets_by_event: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build kickoff-sorted prediction cards from persisted predictions.

    Args:
        predictions: All persisted predictions.
        matches_meta: Per-event metadata (league/home/away/kickoff); predictions
            without an entry here (no current match) are dropped.
        bets_by_event: Per-event ``{rationale, evidence}`` from locked bets, when
            available, to enrich the card analysis.

    Returns:
        Kickoff-sorted list of prediction card dicts.
    """

    cards: list[dict[str, Any]] = []
    for prediction in predictions:
        meta = matches_meta.get(prediction.event_id)
        if meta is None:
            continue
        # "X at exactly 50%" is the fallback emitted when the model call fails
        # (e.g. no credits) — not a real prediction, so hide it.
        if prediction.predicted_result == "X" and prediction.success_probability == 50:
            continue
        bet = bets_by_event.get(prediction.event_id, {})
        cards.append(
            {
                "eventId": prediction.event_id,
                "league": meta.get("league_name") or meta.get("league_slug", ""),
                "leagueSlug": meta.get("league_slug", ""),
                "home": meta.get("home", ""),
                "away": meta.get("away", ""),
                "kickoffUtc": meta.get("kickoff_utc", ""),
                "predicted": prediction.predicted_result,
                "probability": prediction.success_probability,
                "scoreHome": prediction.home_score,
                "scoreAway": prediction.away_score,
                "minute": prediction.minute,
                "status": prediction.status,
                "outcome": _prediction_outcome(prediction, bet),
                "overUnder": prediction.over_under_result,
                "overUnderLine": prediction.over_under_line,
                "overUnderProbability": prediction.over_under_probability,
                "overUnderOutcome": _over_under_outcome(prediction),
                # Prefer the prediction's own (most current) reasoning; fall back
                # to a locked bet's stored rationale for older rows.
                "rationale": prediction.rationale or bet.get("rationale") or "",
                "evidence": list(prediction.evidence or bet.get("evidence") or []),
            }
        )
    # Most recent / most imminent kickoff first (descending), so live and upcoming
    # matches lead and older finished ones sink to the bottom.
    cards.sort(key=lambda card: card["kickoffUtc"], reverse=True)
    return cards


def _prediction_outcome(
    prediction: "PredictionRow", bet: dict[str, Any]
) -> str:
    """Return the pick's result: ``won``, ``lost``, or ``pending``.

    A settled bet's recorded result is authoritative (it may have been settled
    even when the prediction row still reads "live"). Otherwise, a finished match
    (``status == "done"``) is decided by comparing the pick to the final score;
    a match still in play is ``pending``.

    Args:
        prediction: The persisted prediction row.
        bet: The event's bet data (may carry a settled ``outcome``).

    Returns:
        One of ``"won"``, ``"lost"``, ``"pending"``.
    """

    bet_outcome = bet.get("outcome")
    if bet_outcome in ("won", "lost"):
        return bet_outcome
    if prediction.status != "done":
        return "pending"
    actual = _result_from_score(prediction.home_score, prediction.away_score)
    return "won" if actual == prediction.predicted_result else "lost"


def _over_under_outcome(prediction: "PredictionRow") -> str:
    """Return the Over/Under pick's result: ``won``, ``lost``, or ``pending``.

    Decided only for a finished match (final score in the row) with an O/U pick:
    the final total goals are compared to the line. Otherwise ``pending``.
    """

    if (
        prediction.status != "done"
        or prediction.over_under_result is None
        or prediction.over_under_line is None
    ):
        return "pending"
    total = prediction.home_score + prediction.away_score
    actual_over = total > prediction.over_under_line
    picked_over = prediction.over_under_result == "Over"
    return "won" if actual_over == picked_over else "lost"


def _result_from_score(home_score: int, away_score: int) -> str:
    """Map a final score to its 1X2 result code."""

    if home_score > away_score:
        return "1"
    if home_score < away_score:
        return "2"
    return "X"
