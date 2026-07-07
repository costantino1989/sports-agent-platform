"""Shared helpers for dossier markdown rendering."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, TypeAlias

JsonDict: TypeAlias = dict[str, Any]
JsonData: TypeAlias = JsonDict | list[Any]

REMOVED_KEYS = {"href", "$ref", "uid", "id"}


def extract_live_snapshot(
    summary_data: Any,
) -> tuple[list[JsonDict], JsonDict | None]:
    """Extract live competitors and status type from a summary payload.

    Reads the same ``header.competitions[0]`` block the live probe uses, so the
    dossier reflects the in-progress score/status rather than the pre-match
    record persisted at sync time (which stays "Scheduled / 0-0").

    Args:
        summary_data: Raw ESPN summary JSON (``MatchDossierData.summary.data``).

    Returns:
        Pair ``(competitors, status_type)`` where each competitor is a dict with
        ``side``, ``team_id``, ``team_name`` and ``score``. Both empty/None when
        the live header is unavailable (e.g. a genuine pre-match build).
    """

    if not isinstance(summary_data, dict):
        return [], None
    competitions = (summary_data.get("header") or {}).get("competitions") or []
    if not competitions:
        return [], None
    competition = competitions[0]
    competitors: list[JsonDict] = []
    for competitor in competition.get("competitors") or []:
        score = competitor.get("score")
        if score is None:
            continue
        team = competitor.get("team") or {}
        competitors.append(
            {
                "side": competitor.get("homeAway"),
                "team_id": str(team.get("id")) if team.get("id") is not None else "",
                "team_name": team.get("displayName") or "",
                "score": str(score),
            }
        )
    status_type = (competition.get("status") or {}).get("type")
    return competitors, status_type if isinstance(status_type, dict) else None


def prematch_odds_note(summary_data: Any) -> str:
    """Return a warning that section-8 odds are pre-match, when the match is live.

    ESPN's odds snapshot does not track the live score, so for an in-progress
    match the "Current" line still shows pre-kickoff prices. Left unlabelled, it
    contradicts the live score and pulls the model back toward the pre-match
    favourite. This note flags it explicitly; empty string before kickoff.

    Args:
        summary_data: Raw ESPN summary JSON.

    Returns:
        A one-line warning (with the live score echoed) when the match is in
        progress, otherwise an empty string.
    """

    competitors, status_type = extract_live_snapshot(summary_data)
    if not isinstance(status_type, dict) or status_type.get("state") != "in":
        return ""
    score = " - ".join(
        f"{c['team_name']} {c['score']}" for c in competitors if c["team_name"]
    )
    minute = str(status_type.get("detail") or status_type.get("description") or "").strip()
    minute_part = f" at {minute}" if minute else ""
    return (
        "⚠️ The odds below are a PRE-MATCH snapshot and do NOT reflect the live "
        f"score ({score}{minute_part}). Use them only as a pre-kickoff prior — the "
        "live score in section 1 and the play-by-play in section 6 take precedence."
    )


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
