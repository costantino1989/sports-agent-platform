"""Utilities for extracting and filtering schedule event payloads."""

from __future__ import annotations

from src.models.dossier import JsonData, JsonDict


def extract_schedule_events(payload: JsonData | None) -> list[JsonDict]:
    """Extract schedule event entries from arbitrary nested payload."""

    events: list[JsonDict] = []
    if isinstance(payload, dict):
        direct_events = payload.get("events")
        if isinstance(direct_events, list):
            return [item for item in direct_events if isinstance(item, dict)]
    _collect_event_nodes(node=payload, collected=events)
    return events


def extract_competitor_ids(event: JsonDict) -> set[str]:
    """Extract competitor team IDs from an event dictionary."""

    competitor_ids: set[str] = set()
    competitions = event.get("competitions")
    if not isinstance(competitions, list):
        return competitor_ids
    for competition in competitions:
        competitors = competition.get("competitors", []) if isinstance(competition, dict) else []
        for competitor in competitors:
            team = competitor.get("team", {}) if isinstance(competitor, dict) else {}
            team_id = team.get("id")
            if team_id is not None:
                competitor_ids.add(str(team_id))
    return competitor_ids


def _collect_event_nodes(node: JsonData | None, collected: list[JsonDict]) -> None:
    """Recursively collect event-like dictionaries from nested payload."""

    if isinstance(node, dict):
        if "competitions" in node and "date" in node:
            collected.append(node)
        for value in node.values():
            _collect_event_nodes(value, collected)
        return
    if isinstance(node, list):
        for item in node:
            _collect_event_nodes(item, collected)
