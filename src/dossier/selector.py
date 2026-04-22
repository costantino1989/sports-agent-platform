"""Select today's eligible in-progress matches for markdown generation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, TypeAlias

from src.espn import EspnSoccerClient
from src.models.leagues import LEAGUES, LeagueDefinition
from src.models.live_models import (
    ApiReferencesModel,
    CompetitionModel,
    EventModel,
    LeagueModel,
    MatchRecordModel,
    TeamIdentifiersModel,
    VenueIdentifiersModel,
)
from src.utils import get_logger
from src.schedule.weekly import WeeklyScoreboardCollector

JsonDict: TypeAlias = dict[str, Any]

SUMMARY_URL_TEMPLATE = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/summary?event={event_id}"
)
CORE_COMPETITION_URL_TEMPLATE = (
    "https://sports.core.api.espn.com/v2/sports/soccer/leagues/{league_slug}/events/"
    "{event_id}/competitions/{competition_id}"
)
MIN_STARTED_MINUTES = 10

LOGGER = get_logger()


class TodayInProgressSelector:
    """Select today's in-progress matches started at least ten minutes ago.

    Attributes:
        _collector: Weekly collector reused for concurrent scoreboard requests.
        _min_started_minutes: Minimum elapsed minutes from kickoff.
    """

    def __init__(
        self,
        client: EspnSoccerClient,
        collector: WeeklyScoreboardCollector | None = None,
        min_started_minutes: int = MIN_STARTED_MINUTES,
    ) -> None:
        """Initialize selector dependencies.

        Args:
            client: Shared ESPN HTTP client.
            collector: Optional preconfigured collector.
            min_started_minutes: Minimum elapsed minutes from kickoff.
        """

        self._collector = collector or WeeklyScoreboardCollector(client=client)
        self._min_started_minutes = min_started_minutes

    def run(self) -> list[MatchRecordModel]:
        """Collect today's eligible matches for markdown generation.

        Returns:
            Match records ready to be consumed by dossier generation.
        """

        now_utc = datetime.now(timezone.utc)
        today_utc = now_utc.date()
        fetch_results = self._collector.collect(leagues=LEAGUES, week_dates=[today_utc])
        selected_matches: list[MatchRecordModel] = []
        seen_keys: set[str] = set()

        for result in fetch_results:
            if result.error:
                LOGGER.warn(
                    f"Skipping league '{result.task.league.slug}' for date "
                    f"{result.task.date_key}: {result.error}"
                )
                continue
            scoreboard = result.scoreboard
            if scoreboard is None:
                continue
            selected_matches.extend(
                self._extract_matches(
                    league=result.task.league,
                    scoreboard_payload=scoreboard,
                    now_utc=now_utc,
                    today_utc=today_utc,
                    seen_keys=seen_keys,
                )
            )

        LOGGER.info(
            f"Selected {len(selected_matches)} eligible in-progress matches for markdowns."
        )
        return selected_matches

    def _extract_matches(
        self,
        league: LeagueDefinition,
        scoreboard_payload: JsonDict,
        now_utc: datetime,
        today_utc: date,
        seen_keys: set[str],
    ) -> list[MatchRecordModel]:
        """Extract eligible matches from one scoreboard payload.

        Args:
            league: League definition related to the scoreboard.
            scoreboard_payload: Raw scoreboard payload.
            now_utc: Current UTC timestamp.
            today_utc: Current UTC date.
            seen_keys: Deduplication key set.

        Returns:
            Eligible match records.
        """

        selected: list[MatchRecordModel] = []
        events = scoreboard_payload.get("events", [])
        if not isinstance(events, list):
            return selected
        for event in events:
            if not isinstance(event, dict):
                continue
            competitions = event.get("competitions", [])
            if not isinstance(competitions, list):
                continue
            for competition in competitions:
                if not isinstance(competition, dict):
                    continue
                if not self._is_eligible_match(
                    event=event,
                    competition=competition,
                    now_utc=now_utc,
                    today_utc=today_utc,
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
                selected.append(
                    self._build_match_record(
                        league=league,
                        event=event,
                        competition=competition,
                    )
                )
        return selected

    def _is_eligible_match(
        self,
        event: JsonDict,
        competition: JsonDict,
        now_utc: datetime,
        today_utc: date,
    ) -> bool:
        """Return whether a match qualifies for dossier generation.

        Args:
            event: Event payload dictionary.
            competition: Competition payload dictionary.
            now_utc: Current UTC timestamp.
            today_utc: Current UTC date.

        Returns:
            True when the match is in progress and started at least ten minutes ago.
        """

        states = {
            self._extract_status_state(event.get("status")),
            self._extract_status_state(competition.get("status")),
        }
        if "in" not in states:
            return False
        kickoff = self._extract_kickoff_datetime(event=event, competition=competition)
        if kickoff is None:
            return False
        if kickoff.date() != today_utc:
            return False
        threshold = now_utc - timedelta(minutes=self._min_started_minutes)
        return kickoff <= threshold

    @staticmethod
    def _extract_status_state(status: Any) -> str | None:
        """Extract status type state from an ESPN status payload.

        Args:
            status: Status payload.

        Returns:
            Lowercased state when present.
        """

        if not isinstance(status, dict):
            return None
        status_type = status.get("type")
        if not isinstance(status_type, dict):
            return None
        state = status_type.get("state")
        if not isinstance(state, str):
            return None
        return state.lower()

    def _extract_kickoff_datetime(
        self,
        event: JsonDict,
        competition: JsonDict,
    ) -> datetime | None:
        """Extract kickoff datetime from event and competition payloads.

        Args:
            event: Event dictionary.
            competition: Competition dictionary.

        Returns:
            Parsed kickoff datetime in UTC when available.
        """

        for raw_value in (event.get("date"), competition.get("date")):
            parsed = self._parse_datetime(value=raw_value)
            if parsed:
                return parsed
        return None

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        """Parse one ISO datetime value from ESPN payloads.

        Args:
            value: Raw date value.

        Returns:
            Parsed UTC datetime when valid.
        """

        if not isinstance(value, str) or not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _build_dedupe_key(
        league_slug: str,
        event: JsonDict,
        competition: JsonDict,
    ) -> str:
        """Build deduplication key for event and competition payloads.

        Args:
            league_slug: ESPN league slug.
            event: Event dictionary.
            competition: Competition dictionary.

        Returns:
            Stable deduplication key.
        """

        event_ref = event.get("id") or event.get("uid") or event.get("name") or "unknown-event"
        competition_ref = (
            competition.get("id")
            or competition.get("uid")
            or competition.get("date")
            or "unknown-competition"
        )
        return f"{league_slug}:{event_ref}:{competition_ref}"

    def _build_match_record(
        self,
        league: LeagueDefinition,
        event: JsonDict,
        competition: JsonDict,
    ) -> MatchRecordModel:
        """Build one match record from scoreboard event and competition payloads.

        Args:
            league: League definition for current match.
            event: Event dictionary from ESPN scoreboard.
            competition: Competition dictionary nested in event.

        Returns:
            Normalized match record model.
        """

        event_id = str(event.get("id", ""))
        competition_id = str(competition.get("id", ""))
        competitors = competition.get("competitors", [])
        event_model = EventModel.model_validate(event)
        competition_payload = dict(competition)
        competition_payload["venue"] = self._extract_venue_identifiers(competition.get("venue", {}))
        competition_model = CompetitionModel.model_validate(competition_payload)

        return MatchRecordModel(
            league=LeagueModel(slug=league.slug, name=league.display_name),
            event=event_model,
            competition=competition_model,
            teams=[self._extract_team_identifiers(team) for team in competitors],
            api_refs=ApiReferencesModel(
                summary=SUMMARY_URL_TEMPLATE.format(
                    league_slug=league.slug,
                    event_id=event_id,
                ),
                core_competition=CORE_COMPETITION_URL_TEMPLATE.format(
                    league_slug=league.slug,
                    event_id=event_id,
                    competition_id=competition_id,
                ),
            ),
        )

    @staticmethod
    def _extract_venue_identifiers(venue: JsonDict) -> VenueIdentifiersModel | None:
        """Extract typed venue identifiers from a competition payload.

        Args:
            venue: Venue dictionary from competition payload.

        Returns:
            Venue model when available.
        """

        if not venue:
            return None
        return VenueIdentifiersModel.model_validate(venue)

    @staticmethod
    def _extract_team_identifiers(competitor: JsonDict) -> TeamIdentifiersModel:
        """Extract typed team identifiers from one competitor payload.

        Args:
            competitor: Competitor dictionary from competition payload.

        Returns:
            Team identifiers model.
        """

        return TeamIdentifiersModel.model_validate(competitor)
