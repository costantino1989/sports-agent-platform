"""Action that collects scheduled matches for the current week."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeAlias

from src.espn import EspnSoccerClient
from src.models.leagues import LEAGUES, LeagueDefinition
from src.models.weekly_models import (
    WeeklyCompetitionModel,
    WeeklyEventModel,
    WeeklyMatchModel,
    WeeklyMatchesPayloadModel,
    WeeklyTeamModel,
)
from src.utils import get_logger
from src.utils.timing import log_execution_time
from src.weekly.fetching import WeeklyScoreboardCollector
from src.weekly.filtering import WeeklyUpcomingFilter
from src.weekly.grouping import WeeklyDataGrouper

JsonDict: TypeAlias = dict[str, Any]
LOGGER = get_logger()


class WeeklyMatchesAction:
    """Collect current-week scheduled matches and persist them to JSON.

    Attributes:
        _collector: Concurrent scoreboard collector.
        _upcoming_filter: Filter used to keep only upcoming matches.
        _grouper: Weekly match grouper used to structure output data.
    """

    def __init__(
        self,
        client: EspnSoccerClient,
        collector: WeeklyScoreboardCollector | None = None,
        upcoming_filter: WeeklyUpcomingFilter | None = None,
        grouper: WeeklyDataGrouper | None = None,
    ) -> None:
        """Initialize action dependencies.

        Args:
            client: ESPN HTTP client.
            collector: Weekly scoreboard collector. Default implementation is used when omitted.
            upcoming_filter: Upcoming match filter. Default implementation is used when omitted.
            grouper: Weekly match grouper. When omitted, default implementation is used.
        """

        self._collector = collector or WeeklyScoreboardCollector(client=client)
        self._upcoming_filter = upcoming_filter or WeeklyUpcomingFilter()
        self._grouper = grouper or WeeklyDataGrouper()

    @log_execution_time
    def run(self, output_path: Path) -> WeeklyMatchesPayloadModel:
        """Collect and store scheduled matches for the current UTC week.

        Args:
            output_path: Destination JSON path.

        Returns:
            Weekly matches payload written to disk.

        Raises:
            OSError: If writing the output file fails.
        """

        week_dates = self._current_week_dates_utc()
        LOGGER.info(
            f"Collecting weekly matches from {week_dates[0].isoformat()} to "
            f"{week_dates[-1].isoformat()}."
        )
        payload = WeeklyMatchesPayloadModel(
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            week_start_utc=week_dates[0].isoformat(),
            week_end_utc=week_dates[-1].isoformat(),
        )
        now_utc = datetime.now(timezone.utc)
        seen_keys: set[str] = set()
        weekly_matches: list[tuple[str, str, WeeklyMatchModel]] = []

        fetch_results = self._collector.collect(leagues=LEAGUES, week_dates=week_dates)
        for result in fetch_results:
            if result.error:
                LOGGER.warn(
                    f"Scoreboard fetch failed for {result.task.league.slug} "
                    f"{result.task.date_key}: {result.error}"
                )
                payload.fetch_errors.append(
                    f"{result.task.league.slug} {result.task.date_key}: {result.error}"
                )
                continue
            scoreboard = result.scoreboard
            if scoreboard is None:
                continue
            matches = self._extract_matches(
                league=result.task.league,
                scoreboard_payload=scoreboard,
                seen_keys=seen_keys,
                now_utc=now_utc,
            )
            weekly_matches.extend(
                (
                    result.task.league.slug,
                    result.task.league.display_name,
                    match,
                )
                for match in matches
            )

        payload.data = self._grouper.group_matches(matches=weekly_matches)
        payload.match_count = len(weekly_matches)
        self._write_json(output_path=output_path, payload=payload)
        LOGGER.info(
            f"Weekly collection completed with {payload.match_count} upcoming matches "
            f"and {len(payload.fetch_errors)} fetch errors."
        )
        return payload

    def _current_week_dates_utc(self) -> list[date]:
        """Return Monday..Sunday dates for the current UTC week.

        Returns:
            List of seven dates from Monday to Sunday in UTC.
        """

        today = datetime.now(timezone.utc).date()
        week_start = today - timedelta(days=today.weekday())
        return [week_start + timedelta(days=offset) for offset in range(7)]

    def _extract_matches(
        self,
        league: LeagueDefinition,
        scoreboard_payload: JsonDict,
        seen_keys: set[str],
        now_utc: datetime,
    ) -> list[WeeklyMatchModel]:
        """Extract deduplicated matches from one scoreboard payload.

        Args:
            league: League metadata used for collection.
            scoreboard_payload: Raw scoreboard payload.
            seen_keys: Set used to prevent duplicate event-competition entries.
            now_utc: Current UTC timestamp used for upcoming-match filtering.

        Returns:
            List of weekly match models extracted from payload.
        """

        matches: list[WeeklyMatchModel] = []
        events = scoreboard_payload.get("events", [])
        if not isinstance(events, list):
            return matches
        for event in events:
            if not isinstance(event, dict):
                continue
            competitions = event.get("competitions", [])
            if not isinstance(competitions, list):
                continue
            for competition in competitions:
                if not isinstance(competition, dict):
                    continue
                if not self._upcoming_filter.is_upcoming_match(
                    event=event,
                    competition=competition,
                    now_utc=now_utc,
                ):
                    continue
                dedupe_key = self._build_dedupe_key(
                    league_slug=league.slug,
                    event=event,
                    competition=competition,
                )
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                matches.append(
                    WeeklyMatchModel(
                        event=self._build_event_model(event=event),
                        competition=self._build_competition_model(competition=competition),
                        teams=self._build_team_models(competition=competition),
                    )
                )
        return matches

    def _build_dedupe_key(
        self,
        league_slug: str,
        event: JsonDict,
        competition: JsonDict,
    ) -> str:
        """Build a stable dedupe key for event/competition combinations.

        Args:
            league_slug: ESPN league slug.
            event: Event payload dictionary.
            competition: Competition payload dictionary.

        Returns:
            Stable deduplication key string.
        """

        event_ref = event.get("id") or event.get("uid") or event.get("name") or "unknown-event"
        competition_ref = (
            competition.get("id")
            or competition.get("uid")
            or competition.get("date")
            or "unknown-competition"
        )
        return f"{league_slug}:{event_ref}:{competition_ref}"

    def _build_event_model(self, event: JsonDict) -> WeeklyEventModel:
        """Map raw event payload into weekly event model.

        Args:
            event: Event dictionary from scoreboard payload.

        Returns:
            Weekly event model.
        """

        return WeeklyEventModel(
            id=event.get("id"),
            uid=event.get("uid"),
            date=event.get("date"),
            name=event.get("name"),
            short_name=event.get("shortName"),
            status=event.get("status"),
        )

    def _build_competition_model(self, competition: JsonDict) -> WeeklyCompetitionModel:
        """Map raw competition payload into weekly competition model.

        Args:
            competition: Competition dictionary from scoreboard payload.

        Returns:
            Weekly competition model.
        """

        return WeeklyCompetitionModel(
            id=competition.get("id"),
            uid=competition.get("uid"),
            date=competition.get("date"),
            status=competition.get("status"),
        )

    def _build_team_models(self, competition: JsonDict) -> list[WeeklyTeamModel]:
        """Map competition competitors into weekly team models.

        Args:
            competition: Competition dictionary from scoreboard payload.

        Returns:
            Weekly team models for all competitors.
        """

        team_models: list[WeeklyTeamModel] = []
        competitors = competition.get("competitors", [])
        if not isinstance(competitors, list):
            return team_models
        for competitor in competitors:
            if not isinstance(competitor, dict):
                continue
            team = competitor.get("team", {})
            if not isinstance(team, dict):
                team = {}
            team_models.append(
                WeeklyTeamModel(
                    side=competitor.get("homeAway"),
                    competitor_id=competitor.get("id"),
                    competitor_uid=competitor.get("uid"),
                    team_id=team.get("id"),
                    team_uid=team.get("uid"),
                    team_slug=team.get("slug"),
                    abbreviation=team.get("abbreviation"),
                    display_name=team.get("displayName"),
                    score=competitor.get("score"),
                )
            )
        return team_models

    def _write_json(self, output_path: Path, payload: WeeklyMatchesPayloadModel) -> None:
        """Persist weekly payload to disk as UTF-8 JSON.

        Args:
            output_path: Destination JSON file path.
            payload: Weekly matches payload model to serialize.
        """

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
