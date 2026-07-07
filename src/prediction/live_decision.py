"""Decide whether to skip or re-run a prediction for a live match.

A confident prediction is expensive to recompute (the LLM call dominates), so it
is only re-evaluated when something can plausibly change the outcome: the score
moves against the pick, a red card appears, or a bounded number of skip cycles
have elapsed as a safety net.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PredictionAction(Enum):
    """Action to take for a match this cycle."""

    PREDICT = "predict"
    SKIP = "skip"
    DONE = "done"


@dataclass(frozen=True)
class MatchState:
    """Current live state from the cheap probe."""

    home_score: int
    away_score: int
    red_cards: int
    minute: int
    finished: bool


@dataclass(frozen=True)
class LastPrediction:
    """Previously persisted prediction and the state it was made on."""

    predicted_result: str
    success_probability: int
    home_score: int
    away_score: int
    red_cards: int
    cycles_since_full: int


def should_lock(model_prob: int, lock_confidence: int) -> bool:
    """Return whether a prediction is confident enough to lock as the bet.

    Args:
        model_prob: Model success probability, 0-100.
        lock_confidence: Confidence at or above which the bet is locked.

    Returns:
        True when the prediction should be locked (and no longer recomputed).
    """

    return model_prob >= lock_confidence


def should_lock_bet(
    model_prob: int,
    odds: float | None,
    lock_confidence: int,
    lock_odds: float,
) -> bool:
    """Return whether the bet should be locked now.

    Locks when the model is confident enough, or when the predicted outcome's
    odds have fallen to the near-floor level (outcome effectively decided, so
    further predictions add nothing — just decide the bet).

    Args:
        model_prob: Model success probability, 0-100.
        odds: Decimal odds of the predicted outcome, or None if unknown.
        lock_confidence: Confidence at or above which to lock.
        lock_odds: Odds at or below which to lock (near the min-odds floor).

    Returns:
        True when the bet should be locked.
    """

    if model_prob >= lock_confidence:
        return True
    return odds is not None and odds <= lock_odds


def required_confidence(minute: int, base_confidence: int) -> int:
    """Confidence needed to lock, relaxed as the match nears full time.

    Late in a match the outcome is more settled, so a somewhat lower confidence
    is accepted. This does NOT assume the leader holds — it only lowers our bar;
    the model's own evidence-based probability (weighing score, time and the run
    of play) and the positive-EV filter still decide whether a bet is placed.

    Args:
        minute: Current match minute.
        base_confidence: Early-match confidence threshold (e.g. 80).

    Returns:
        The confidence threshold to apply at this minute (80 -> 70 -> 60).
    """

    if minute >= 75:
        return base_confidence - 20
    if minute >= 60:
        return base_confidence - 10
    return base_confidence


def _goal_against_pick(last: LastPrediction, current: MatchState) -> bool:
    """Return whether a new goal moved the scoreline against the pick."""

    new_home = current.home_score - last.home_score
    new_away = current.away_score - last.away_score
    if last.predicted_result == "1":
        return new_away > 0
    if last.predicted_result == "2":
        return new_home > 0
    # A draw pick ("X") is broken by any new goal.
    return new_home > 0 or new_away > 0


def decide_action(
    last: LastPrediction | None,
    current: MatchState,
    force_refresh_every: int,
) -> tuple[PredictionAction, str]:
    """Decide the action for one match this cycle.

    After the first prediction a match is re-predicted only when something can
    move the outcome — a goal against the pick or a red card — or on the periodic
    force-refresh. It is NOT recomputed every cycle just because confidence is
    low: re-running the model on unchanged data adds nothing but cost.

    Args:
        last: Previously persisted prediction, or None if never predicted.
        current: Current probed match state.
        force_refresh_every: Re-predict after this many consecutive skip cycles.

    Returns:
        Pair of the chosen action and a short reason code.
    """

    if current.finished:
        return PredictionAction.DONE, "match_finished"
    if last is None:
        return PredictionAction.PREDICT, "no_prior"
    if _goal_against_pick(last, current) or current.red_cards > last.red_cards:
        return PredictionAction.PREDICT, "material_change"
    if last.cycles_since_full + 1 >= force_refresh_every:
        return PredictionAction.PREDICT, "forced_refresh"
    return PredictionAction.SKIP, "stable"
