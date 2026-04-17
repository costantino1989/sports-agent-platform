"""Helpers for formatting and extracting head-to-head match details."""

from __future__ import annotations

from typing import Any

from src.models.dossier import JsonDict


def extract_event_status(event: JsonDict) -> str:
    """Extract final status detail for one schedule event."""

    status = event.get("status")
    detail = _extract_status_detail(status=status)
    if detail != "N/A":
        return detail
    competition = _extract_primary_competition(event=event)
    if competition is None:
        return "N/A"
    return _extract_status_detail(status=competition.get("status"))


def extract_event_score(event: JsonDict) -> str:
    """Extract human-readable scoreline for one schedule event."""

    competition = _extract_primary_competition(event=event)
    if competition is None:
        return "N/A"
    competitors = competition.get("competitors", [])
    if not isinstance(competitors, list) or len(competitors) < 2:
        return "N/A"
    home = competitors[0]
    away = competitors[1]
    home_name = _extract_competitor_display_name(competitor=home)
    away_name = _extract_competitor_display_name(competitor=away)
    home_score = _extract_score_display_value(
        score=(home.get("score") if isinstance(home, dict) else None)
    )
    away_score = _extract_score_display_value(
        score=(away.get("score") if isinstance(away, dict) else None)
    )
    if home_score == "N/A" and away_score == "N/A":
        return "N/A"
    return f"{home_name} {home_score} - {away_score} {away_name}"


def extract_event_phase(event: JsonDict) -> str:
    """Extract competition phase and leg details for one event."""

    competition = _extract_primary_competition(event=event)
    if competition is None:
        return "N/A"
    season_type = event.get("seasonType")
    phase_name = None
    if isinstance(season_type, dict):
        raw_phase = season_type.get("name") or season_type.get("abbreviation")
        if isinstance(raw_phase, str) and raw_phase.strip():
            phase_name = raw_phase.strip()
    leg = competition.get("leg")
    leg_name = None
    if isinstance(leg, dict):
        raw_leg = leg.get("displayValue")
        if isinstance(raw_leg, str) and raw_leg.strip():
            leg_name = raw_leg.strip()
    if phase_name and leg_name:
        return f"{phase_name} - {leg_name}"
    if phase_name:
        return phase_name
    if leg_name:
        return leg_name
    return "N/A"


def _extract_primary_competition(event: JsonDict) -> JsonDict | None:
    """Extract the primary competition object from a schedule event."""

    competitions = event.get("competitions")
    if not isinstance(competitions, list) or not competitions:
        return None
    competition = competitions[0]
    if not isinstance(competition, dict):
        return None
    return competition


def _extract_status_detail(status: Any) -> str:
    """Extract detail/description text from a status object."""

    if not isinstance(status, dict):
        return "N/A"
    status_type = status.get("type")
    if isinstance(status_type, dict):
        for key in ("detail", "description", "name"):
            value = status_type.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("detail", "displayClock", "name"):
        value = status.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "N/A"


def _extract_competitor_display_name(competitor: Any) -> str:
    """Extract competitor team display name from one competitor object."""

    if not isinstance(competitor, dict):
        return "Team"
    team = competitor.get("team")
    if isinstance(team, dict):
        display_name = team.get("displayName") or team.get("shortDisplayName") or team.get("name")
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()
    fallback = competitor.get("displayName")
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return "Team"


def _extract_score_display_value(score: Any) -> str:
    """Extract score display value from score object or scalar value."""

    if isinstance(score, dict):
        display = score.get("displayValue")
        if display is not None:
            return str(display)
        value = score.get("value")
        if isinstance(value, (int, float)):
            return str(int(value)) if float(value).is_integer() else str(value)
    if isinstance(score, (int, float)):
        return str(int(score)) if float(score).is_integer() else str(score)
    if isinstance(score, str) and score.strip():
        return score.strip()
    return "N/A"
