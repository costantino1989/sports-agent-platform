"""Cheap live-state probe parsed from an ESPN event summary payload.

Used before deciding whether a confident prediction can be skipped: it extracts
only the score, minute, finished flag, and red-card count — no full dossier.
"""

from __future__ import annotations

import re
from typing import Any

from src.prediction.live_decision import MatchState


def _to_int(value: Any) -> int:
    """Best-effort integer from a string/int score or stat value."""

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _minute_from_detail(status_type: dict[str, Any]) -> int:
    """Extract the leading minute integer from the status detail text."""

    for key in ("detail", "shortDetail", "description"):
        text = status_type.get(key)
        if isinstance(text, str):
            match = re.search(r"\d+", text)
            if match:
                return int(match.group(0))
    return 0


def _count_red_cards(summary: dict[str, Any]) -> int:
    """Sum red cards across both teams from the boxscore, best-effort."""

    total = 0
    teams = (summary.get("boxscore") or {}).get("teams") or []
    for team in teams:
        for stat in team.get("statistics", []) or []:
            if isinstance(stat, dict) and stat.get("name") == "redCards":
                total += _to_int(stat.get("displayValue"))
    return total


def parse_match_state(summary: dict[str, Any]) -> MatchState | None:
    """Parse a :class:`MatchState` from an ESPN summary payload.

    Args:
        summary: ESPN event summary JSON.

    Returns:
        Parsed match state, or None when scores are unavailable.
    """

    if not isinstance(summary, dict):
        return None
    competitions = (summary.get("header") or {}).get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]
    competitors = competition.get("competitors") or []

    scores: dict[str, int] = {}
    for competitor in competitors:
        side = competitor.get("homeAway")
        if side in ("home", "away"):
            scores[side] = _to_int(competitor.get("score"))
    if "home" not in scores or "away" not in scores:
        return None

    status_type = (competition.get("status") or {}).get("type") or {}
    finished = bool(status_type.get("completed")) or status_type.get("state") == "post"

    return MatchState(
        home_score=scores["home"],
        away_score=scores["away"],
        red_cards=_count_red_cards(summary),
        minute=_minute_from_detail(status_type),
        finished=finished,
    )
