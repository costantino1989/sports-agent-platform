"""Selection of matches to build dossiers for.

Unions two sources, deduplicated by event id:
- pending scheduled runs due at their 30'/60' checkpoints, and
- matches that have already kicked off but whose markdown file has not been
  generated yet (so a started match gets a dossier regardless of the minute).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.dossier.naming import build_dossier_filename
from src.models.live_models import MatchRecordModel

if TYPE_CHECKING:
    from src.schedule.repositories import MatchRepository, RunRepository


def select_matches_to_build(
    run_repo: "RunRepository",
    match_repo: "MatchRepository",
    markdown_dir: Path,
    now_utc: datetime,
) -> list[MatchRecordModel]:
    """Return the matches a build run should generate dossiers for.

    Args:
        run_repo: Repository exposing pending due runs.
        match_repo: Repository exposing started matches.
        markdown_dir: Directory where dossier markdown files are written.
        now_utc: Current time in UTC.

    Returns:
        Deduplicated match records: all due runs, plus started matches that do
        not yet have a generated markdown file.
    """

    selected: dict[str, MatchRecordModel] = {}
    for match in run_repo.get_pending_runs_due():
        event_id = match.event.id
        if event_id:
            selected[event_id] = match
    for match in match_repo.get_started_matches(now_utc=now_utc):
        event_id = match.event.id
        if not event_id or event_id in selected:
            continue
        if (markdown_dir / build_dossier_filename(match)).exists():
            continue
        selected[event_id] = match
    return list(selected.values())
