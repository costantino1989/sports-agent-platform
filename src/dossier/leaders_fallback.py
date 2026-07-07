"""Season-leaders fallback sourced from the event summary payload.

For some leagues the dedicated core leaders endpoint
(`.../seasons/<year>/leaders`) is unavailable, yet the event summary already
includes a `leaders` block. When the core payload is empty, this module
normalizes `summary.leaders` into the category shape the renderer expects.
"""

from __future__ import annotations

from typing import Any

from src.models.dossier import EndpointPayload


def summary_leaders_categories(summary_data: Any) -> list[dict[str, Any]] | None:
    """Flatten ``summary.leaders`` into leader categories with team attached.

    The summary groups leaders per team as
    ``[{team, leaders: [{name, displayName, leaders: [{athlete, ...}]}]}]``.
    This flattens it to the per-category dicts the renderer walks, propagating
    the owning team onto each individual leader.

    Args:
        summary_data: Parsed summary payload.

    Returns:
        List of category dicts, or ``None`` when no leaders are present.
    """

    if not isinstance(summary_data, dict):
        return None
    team_blocks = summary_data.get("leaders")
    if not isinstance(team_blocks, list) or not team_blocks:
        return None

    categories: list[dict[str, Any]] = []
    for team_block in team_blocks:
        if not isinstance(team_block, dict):
            continue
        team = team_block.get("team")
        for category in team_block.get("leaders", []) or []:
            if not isinstance(category, dict):
                continue
            enriched_leaders = []
            for leader in category.get("leaders", []) or []:
                if isinstance(leader, dict):
                    leader = {**leader, "team": leader.get("team") or team}
                enriched_leaders.append(leader)
            categories.append({**category, "leaders": enriched_leaders})
    return categories or None


def resolve_leaders_payload(
    leaders: EndpointPayload, summary: EndpointPayload
) -> EndpointPayload:
    """Return the leaders payload, falling back to summary leaders when empty.

    Args:
        leaders: Payload from the core leaders endpoint.
        summary: Event summary payload (may embed a ``leaders`` block).

    Returns:
        The original payload when it has data, otherwise a payload built from
        ``summary.leaders`` when available, otherwise the original payload.
    """

    if leaders.has_data():
        return leaders
    categories = summary_leaders_categories(summary.data)
    if not categories:
        return leaders
    return EndpointPayload(data=categories)
