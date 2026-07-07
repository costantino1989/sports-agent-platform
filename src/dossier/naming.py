"""Shared naming for dossier markdown files.

Single source of truth for the dossier filename, imported by both the builder
(which writes the file) and the scheduler selection (which checks whether a
match already has a generated file), so the convention cannot drift.
"""

from __future__ import annotations

from src.models.live_models import MatchRecordModel


def build_dossier_filename(match: MatchRecordModel) -> str:
    """Build the stable markdown filename for one match.

    Args:
        match: Match record providing league slug and event id.

    Returns:
        Filename as ``<league_slug_dots_as_underscores>_<event_id>.md``.
    """

    league = match.league.slug.replace(".", "_")
    event_id = (match.event.id or "unknown").replace("/", "_")
    return f"{league}_{event_id}.md"
