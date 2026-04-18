"""Utilities for building concise player season-stat summaries."""

from __future__ import annotations

from typing import Any

from src.models.dossier import JsonData


def build_player_season_stats(athlete_data: JsonData | None, role: str) -> str:
    """Build concise season stats text from athlete statistics payload.

    Args:
        athlete_data: Athlete payload possibly containing a ``statistics`` block.
        role: Player role string (used to include goalkeeper-specific stats).

    Returns:
        Human-readable season stats summary.
    """

    stat_map = extract_player_stat_map(athlete_data=athlete_data)
    if not stat_map:
        return "No season stats available."
    fields = [
        ("Apps", ("appearances",)),
        ("Starts", ("starts",)),
        ("Minutes", ("minutes", "minutesPlayed")),
        ("Goals", ("goals",)),
        ("Assists", ("goalAssists", "assists")),
        ("Fouls", ("foulsCommitted",)),
        ("YC", ("yellowCards",)),
        ("RC", ("redCards",)),
    ]
    if "goalkeeper" in role.lower():
        fields.extend(
            [
                ("Goals conceded", ("goalsConceded",)),
                ("Saves", ("saves",)),
                ("Clean sheets", ("cleanSheet", "cleanSheets")),
            ]
        )
    parts: list[str] = []
    for label, aliases in fields:
        value = _first_available(stat_map=stat_map, aliases=aliases)
        if value is None:
            continue
        parts.append(f"{label}: {value}")
    return "; ".join(parts) if parts else "No season stats available."


def extract_player_stat_map(athlete_data: JsonData | None) -> dict[str, str]:
    """Extract normalized stat-name/value map from athlete payload.

    Args:
        athlete_data: Athlete payload possibly containing a ``statistics`` block.

    Returns:
        Dictionary keyed by normalized stat name and display value.
    """

    if not isinstance(athlete_data, dict):
        return {}
    statistics = athlete_data.get("statistics")
    if not isinstance(statistics, dict):
        return {}
    splits = statistics.get("splits")
    split_block = splits if isinstance(splits, dict) else statistics
    categories = split_block.get("categories") if isinstance(split_block, dict) else None
    if not isinstance(categories, list):
        return {}
    stat_map: dict[str, str] = {}
    for category in categories:
        if not isinstance(category, dict):
            continue
        stats = category.get("stats")
        if not isinstance(stats, list):
            continue
        for stat in stats:
            if not isinstance(stat, dict):
                continue
            raw_name = stat.get("name") or stat.get("displayName") or stat.get("abbreviation")
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            key = _normalize_key(raw_name)
            value = stat.get("displayValue")
            if value is None:
                value = stat.get("value")
            stat_map[key] = str(value) if value is not None else "N/A"
    return stat_map


def _first_available(stat_map: dict[str, str], aliases: tuple[str, ...]) -> str | None:
    """Return first available stat value for aliases."""

    for alias in aliases:
        key = _normalize_key(alias)
        if key in stat_map:
            return stat_map[key]
    return None


def _normalize_key(value: Any) -> str:
    """Normalize stat names into lookup keys."""

    text = str(value).strip().lower()
    return text.replace(" ", "").replace("_", "")
