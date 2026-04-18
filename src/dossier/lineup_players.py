"""Utilities for lineup extraction."""

from __future__ import annotations

from src.models.dossier import JsonData, JsonDict


def extract_summary_rosters_by_team(summary_payload: JsonData | None) -> dict[str, JsonDict]:
    """Index summary roster blocks by team id.

    Args:
        summary_payload: Match summary payload.

    Returns:
        Mapping from team id to summary roster block.
    """

    if not isinstance(summary_payload, dict):
        return {}
    rosters = summary_payload.get("rosters")
    if not isinstance(rosters, list):
        return {}
    indexed: dict[str, JsonDict] = {}
    for item in rosters:
        if not isinstance(item, dict):
            continue
        team = item.get("team")
        if not isinstance(team, dict):
            continue
        team_id = str(team.get("id") or "")
        if not team_id:
            continue
        indexed[team_id] = item
    return indexed


def extract_formation(summary_roster: JsonDict | None) -> str | None:
    """Extract formation text from one summary roster block."""

    if not isinstance(summary_roster, dict):
        return None
    raw_formation = summary_roster.get("formation")
    if isinstance(raw_formation, str) and raw_formation.strip():
        return raw_formation.strip()
    return None


def extract_on_field_roster_entries(roster_entries: Any) -> list[JsonDict]:
    """Return only players currently on the field from a roster entry list."""

    if not isinstance(roster_entries, list):
        return []
    return [
        entry
        for entry in roster_entries
        if isinstance(entry, dict) and is_player_currently_on_field(entry)
    ]


def is_player_currently_on_field(player: JsonDict) -> bool:
    """Return whether a roster entry represents a player currently on field."""

    starter = player.get("starter") is True
    subbed_in = player.get("subbedIn") is True
    subbed_out = player.get("subbedOut") is True
    return (starter or subbed_in) and not subbed_out
