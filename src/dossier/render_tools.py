"""Shared helpers for dossier markdown rendering."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, TypeAlias

JsonDict: TypeAlias = dict[str, Any]
JsonData: TypeAlias = JsonDict | list[Any]

REMOVED_KEYS = {"href", "$ref", "uid", "id"}


def sanitize_payload(payload: JsonData | None) -> JsonData | None:
    """Recursively remove low-value keys and empty values from payload data.

    Args:
        payload: JSON payload to sanitize.

    Returns:
        Sanitized payload with technical keys and empty branches removed.
    """

    if isinstance(payload, dict):
        sanitized: JsonDict = {}
        for key, value in payload.items():
            if key in REMOVED_KEYS:
                continue
            cleaned = sanitize_payload(value)
            if _is_empty_value(key=key, value=cleaned):
                continue
            sanitized[key] = cleaned
        return sanitized or None
    if isinstance(payload, list):
        sanitized_items = [sanitize_payload(item) for item in payload]
        filtered_items = [item for item in sanitized_items if item not in (None, [], {})]
        return filtered_items or None
    return payload


def find_dicts_with_keys(
    payload: JsonData | None,
    required_keys: set[str],
    limit: int = 100,
) -> list[JsonDict]:
    """Find nested dictionaries containing all required keys.

    Args:
        payload: JSON payload to inspect.
        required_keys: Keys that must all exist in a dictionary.
        limit: Maximum number of matches returned.

    Returns:
        List of matching dictionaries.
    """

    matches: list[JsonDict] = []
    if payload is None:
        return matches

    def walk(node: Any) -> None:
        if len(matches) >= limit:
            return
        if isinstance(node, dict):
            if required_keys.issubset(node.keys()):
                matches.append(node)
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return matches


def as_text(value: Any, default: str = "N/A") -> str:
    """Convert values into compact display strings.

    Args:
        value: Source value.
        default: Fallback text when value is missing.

    Returns:
        String representation suitable for markdown tables.
    """

    if value is None:
        return default
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or default
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a markdown table from headers and rows.

    Args:
        headers: Table headers.
        rows: Table rows.

    Returns:
        Markdown table string.
    """

    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header_line, separator_line, *body_lines])


def build_stat_map(stats: Any) -> dict[str, str]:
    """Convert ESPN statistic entries into a normalized lookup map.

    Args:
        stats: Source statistics collection.

    Returns:
        Dictionary where keys are normalized statistic names.
    """

    if not isinstance(stats, list):
        return {}
    stat_map: dict[str, str] = {}
    for item in stats:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("name") or item.get("abbreviation") or item.get("displayName")
        if not isinstance(raw_name, str):
            continue
        normalized_name = raw_name.replace(" ", "").replace("_", "").lower()
        value = item.get("displayValue")
        if value is None:
            value = item.get("value")
        stat_map[normalized_name] = as_text(value=value)
    return stat_map


def first_value(stat_map: dict[str, str], aliases: Iterable[str], default: str = "N/A") -> str:
    """Return first matching statistic value from normalized alias list.

    Args:
        stat_map: Normalized statistic map.
        aliases: Candidate aliases.
        default: Fallback when no alias matches.

    Returns:
        First matching value or default.
    """

    for alias in aliases:
        normalized_alias = alias.replace(" ", "").replace("_", "").lower()
        if normalized_alias in stat_map:
            return stat_map[normalized_alias]
    return default


def format_utc_datetime(value: Any) -> str:
    """Format ISO kickoff datetime into a stable UTC string."""

    if not isinstance(value, str) or not value.strip():
        return "N/A"
    candidate = value.strip()
    normalized = candidate.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return candidate
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _is_empty_value(key: str, value: Any) -> bool:
    """Return whether a key/value pair should be removed from rendering."""

    if value is None:
        return True
    if value == "":
        return True
    if value == []:
        return True
    if value == {}:
        return True
    if key == "notes" and value == []:
        return True
    return False
