"""Concurrent scoreboard fetching utilities for weekly match collection."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Any, TypeAlias

from src.espn import EspnApiError, EspnSoccerClient
from src.models.leagues import LeagueDefinition

JsonDict: TypeAlias = dict[str, Any]

SCOREBOARD_BY_DATE_URL_TEMPLATE = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/scoreboard"
    "?dates={date_key}"
)
DEFAULT_WEEKLY_WORKERS = 20


@dataclass(slots=True, frozen=True)
class ScoreboardFetchTask:
    """Represents one league/date scoreboard fetch task.

    Attributes:
        league: Target league definition.
        date_key: Date in YYYYMMDD format.
    """

    league: LeagueDefinition
    date_key: str


@dataclass(slots=True, frozen=True)
class ScoreboardFetchResult:
    """Represents one scoreboard fetch result.

    Attributes:
        task: Original fetch task metadata.
        scoreboard: Parsed scoreboard payload when successful.
        error: Fetch error message when request fails.
    """

    task: ScoreboardFetchTask
    scoreboard: JsonDict | None
    error: str | None = None


class WeeklyScoreboardCollector:
    """Collect scoreboards concurrently for league/date combinations.

    Attributes:
        _client: ESPN HTTP client used for network requests.
        _max_workers: Maximum number of worker threads.
    """

    def __init__(
        self,
        client: EspnSoccerClient,
        max_workers: int = DEFAULT_WEEKLY_WORKERS,
    ) -> None:
        """Initialize collector dependencies.

        Args:
            client: ESPN HTTP client.
            max_workers: Maximum number of worker threads.
        """

        self._client = client
        self._max_workers = max_workers

    def collect(
        self,
        leagues: tuple[LeagueDefinition, ...],
        week_dates: list[date],
    ) -> list[ScoreboardFetchResult]:
        """Fetch all scoreboards for weekly league/date combinations.

        Args:
            leagues: Leagues to query.
            week_dates: Week dates to query.

        Returns:
            Deterministically sorted fetch results.
        """

        tasks = self._build_tasks(leagues=leagues, week_dates=week_dates)
        if not tasks:
            return []
        if len(tasks) == 1:
            return [self._fetch_task(task=tasks[0])]

        workers = min(self._max_workers, len(tasks))
        results: list[ScoreboardFetchResult] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures: dict[Future[ScoreboardFetchResult], ScoreboardFetchTask] = {
                executor.submit(self._fetch_task, task): task for task in tasks
            }
            for future in as_completed(futures):
                results.append(future.result())

        return sorted(
            results,
            key=lambda result: (result.task.league.slug, result.task.date_key),
        )

    def _build_tasks(
        self,
        leagues: tuple[LeagueDefinition, ...],
        week_dates: list[date],
    ) -> list[ScoreboardFetchTask]:
        """Build scoreboard fetch tasks from leagues and week dates.

        Args:
            leagues: Leagues to query.
            week_dates: Week dates to query.

        Returns:
            Flat list of fetch tasks.
        """

        return [
            ScoreboardFetchTask(
                league=league,
                date_key=match_date.strftime("%Y%m%d"),
            )
            for league in leagues
            for match_date in week_dates
        ]

    def _fetch_task(self, task: ScoreboardFetchTask) -> ScoreboardFetchResult:
        """Fetch one scoreboard task and map errors to result object.

        Args:
            task: Scoreboard fetch task.

        Returns:
            Fetch result with payload or error.
        """

        url = SCOREBOARD_BY_DATE_URL_TEMPLATE.format(
            league_slug=task.league.slug,
            date_key=task.date_key,
        )
        try:
            payload = self._client.fetch_json(url=url)
        except EspnApiError as exc:
            return ScoreboardFetchResult(task=task, scoreboard=None, error=str(exc))
        if not isinstance(payload, dict):
            return ScoreboardFetchResult(
                task=task,
                scoreboard=None,
                error=(
                    "Unexpected payload type for scoreboard "
                    f"'{task.league.slug}' and date '{task.date_key}'."
                ),
            )
        return ScoreboardFetchResult(task=task, scoreboard=payload)
