"""Fill a dossier's play-by-play from API-Football when ESPN has none.

Some leagues (e.g. Ecuador Liga Pro, USL) are not covered by ESPN with live
events, so their dossier's section 6 is empty and the match gets skipped. When
API-Football has the events, this rebuilds section 6 from them so the match
becomes predictable. Mirrors ``attach_real_odds``: a post-render markdown patch.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.odds.dossier_odds import match_odds_query
from src.prediction.prompt_compact import has_play_by_play
from src.utils import get_logger

if TYPE_CHECKING:
    from src.models.live_models import MatchRecordModel
    from src.odds.apifootball import ApiFootballProvider

LOGGER = get_logger()


def enrich_play_by_play(markdown: str, events: list[dict]) -> str:
    """Rebuild section 6 from events; leave the markdown unchanged if none."""

    if not events:
        return markdown
    return _replace_section_six(markdown, _build_section_six(events))


def _build_section_six(events: list[dict]) -> str:
    """Render a section-6 play-by-play table from API-Football events."""

    rows = []
    for event in events:
        impact = "Score changed" if event.get("type", "").lower() == "goal" else ""
        player = event.get("player") or ""
        who = f" ({player})" if player else ""
        label = f"{event.get('type', '')}: {event.get('detail', '')}{who}".strip()
        rows.append(f"| {event['minute']}' | {event.get('team', '')} | {label} | {impact} |")
    return (
        "## 6. Current live statistics\n"
        "Play-by-play (via API-Football — ESPN had no live events):\n\n"
        "| Minute | Team | Event | Impact |\n"
        "| --- | --- | --- | --- |\n" + "\n".join(rows) + "\n"
    )


def _replace_section_six(markdown: str, new_section: str) -> str:
    """Replace an existing section 6 with ``new_section``, or insert it."""

    lines = markdown.splitlines(keepends=True)
    start = _find_heading(lines, "## 6.")
    block = new_section if new_section.endswith("\n") else new_section + "\n"
    if start is None:
        insert_at = _find_heading(lines, "## 7.")
        insert_at = insert_at if insert_at is not None else len(lines)
        lines.insert(insert_at, block + "\n")
        return "".join(lines)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("## ")),
        len(lines),
    )
    return "".join(lines[:start]) + block + "\n" + "".join(lines[end:])


def _find_heading(lines: list[str], prefix: str) -> int | None:
    """Index of the first line starting with ``prefix`` (ignoring indent)."""

    return next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith(prefix)), None
    )


def attach_events(
    markdown_path: Path | None,
    match: "MatchRecordModel",
    provider: "ApiFootballProvider | None",
) -> Path | None:
    """Enrich a dossier lacking play-by-play with API-Football events.

    No-op when the dossier already has play-by-play (ESPN covered it), when no
    provider is set, or when API-Football has no events. Always safe on IO error.
    """

    if markdown_path is None or provider is None:
        return markdown_path
    try:
        original = markdown_path.read_text(encoding="utf-8")
    except OSError as error:
        LOGGER.warn(f"Could not read dossier {markdown_path}: {error}")
        return markdown_path
    if has_play_by_play(original):
        return markdown_path  # ESPN already provided the play-by-play
    query = match_odds_query(match)
    events = provider.fetch_events(
        league_slug=query.league_slug,
        home_team=query.home_team,
        away_team=query.away_team,
        kickoff_utc=query.kickoff_utc,
    )
    merged = enrich_play_by_play(original, events)
    if merged == original:
        return markdown_path
    try:
        markdown_path.write_text(merged, encoding="utf-8")
    except OSError as error:
        LOGGER.warn(f"Could not enrich dossier {markdown_path}: {error}")
        return markdown_path
    LOGGER.info(
        f"Filled play-by-play from API-Football ({len(events)} events) "
        f"in {markdown_path.name}."
    )
    return markdown_path
