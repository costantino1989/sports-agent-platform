"""Self-heal helper for the live-tracking flow.

The scheduler normally populates the matches table once a day (``--schedule-sync``
via cron at midnight). If that table is ever empty — a fresh database, a manual
wipe, or corruption — the live-tracking cron would find nothing to probe and the
whole pipeline would sit idle until the next scheduled sync. This helper lets the
live flow recover on its own: when the table is empty it triggers a sync before
the cycle, so recovery happens within one cron tick instead of at the next
midnight.
"""

from __future__ import annotations

from typing import Protocol

from src.utils import get_logger

LOGGER = get_logger()


class _CountsMatches(Protocol):
    def count_matches(self) -> int: ...


class _SyncResult(Protocol):
    synced_matches: int


class _Sync(Protocol):
    def __call__(self) -> _SyncResult: ...


def ensure_matches_available(match_repo: _CountsMatches, sync: _Sync) -> int:
    """Sync the schedule when the matches table is empty, otherwise do nothing.

    Args:
        match_repo: Repository exposing ``count_matches()``.
        sync: Callable that performs a schedule sync and returns a result with a
            ``synced_matches`` count (e.g. ``ScheduleDispatcherService.sync_only``).

    Returns:
        Number of matches synced during recovery, or ``0`` when the table already
        had matches and no sync was triggered.
    """

    if match_repo.count_matches() > 0:
        return 0
    LOGGER.warn(
        "Matches table is empty; running a recovery sync before the live cycle."
    )
    result = sync()
    LOGGER.info(f"Recovery sync populated {result.synced_matches} matches.")
    return result.synced_matches
