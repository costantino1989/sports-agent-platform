"""Ingestion service that persists weekly matches and scheduled runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone

# URL templates moved here to avoid circular import
SUMMARY_URL_TEMPLATE = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/summary?event={event_id}"
)
CORE_COMPETITION_URL_TEMPLATE = (
    "https://sports.core.api.espn.com/v2/sports/soccer/leagues/{league_slug}/events/"
    "{event_id}/competitions/{competition_id}"
)

from src.models.live_models import (
    ApiReferencesModel,
    CompetitionModel,
    EventModel,
    LeagueModel,
    MatchRecordModel,
    TeamIdentifiersModel,
    TeamModel,
)
from src.models.weekly_models import WeeklyLeagueScheduleModel, WeeklyMatchModel
from src.models.schedule import MatchScheduleRecord
from src.schedule.repositories import MatchRepository, RunRepository



class ScheduleIngestionService:
    """Persist weekly matches and ensure minute30/minute60 scheduled runs."""

    def __init__(
        self,
        weekly_action: WeeklyMatchesAction,
        match_repository: MatchRepository,
        run_repository: RunRepository,
    ) -> None:
        """Initialize ingestion dependencies.

        Args:
            weekly_action: Weekly collection action.
            match_repository: Match persistence repository.
            run_repository: Scheduled-run repository.
        """

        self._weekly_action = weekly_action
        self._match_repository = match_repository
        self._run_repository = run_repository

    def sync(self) -> tuple[int, int]:
        """Synchronize weekly matches into DB and ensure scheduled runs.

        Returns:
            Pair with number of upserted matches and ensured runs.
        """

        payload = self._weekly_action.collect_current_week()
        records = self._to_schedule_records(payload_data=payload.data)
        upserted_matches = self._match_repository.upsert_matches(records=records)
        ensured_runs = 0
        for record in records:
            ensured_runs += self._run_repository.ensure_runs_for_match(
                event_id=record.event_id,
                kickoff_utc=record.kickoff_utc,
            )
        return upserted_matches, ensured_runs

    def _to_schedule_records(
        self,
        payload_data: dict[str, dict[str, WeeklyLeagueScheduleModel]],
    ) -> list[MatchScheduleRecord]:
        """Convert weekly grouped payload into flat scheduler match records."""

        records: list[MatchScheduleRecord] = []
        now_utc = datetime.now(timezone.utc)
        for leagues_by_date in payload_data.values():
            for league_slug, league_payload in leagues_by_date.items():
                league_name = league_payload.description or league_slug
                matches_by_time = league_payload.matches_by_time
                for matches in matches_by_time.values():
                    for raw_match in matches:
                        schedule_record = self._build_schedule_record(
                            league_slug=league_slug,
                            league_name=league_name,
                            weekly_match=raw_match,
                            now_utc=now_utc,
                        )
                        if schedule_record is None:
                            continue
                        records.append(schedule_record)
        return records

    def _build_schedule_record(
        self,
        league_slug: str,
        league_name: str,
        weekly_match: WeeklyMatchModel,
        now_utc: datetime,
    ) -> MatchScheduleRecord | None:
        """Build one scheduler record from one weekly match model."""

        event_id = weekly_match.event.id
        competition_id = weekly_match.competition.id
        kickoff_utc = self._parse_datetime_to_europe_rome(
            weekly_match.event.date or weekly_match.competition.date
        )
        if not event_id or not competition_id or kickoff_utc is None:
            return None
        match_record = self._build_match_record(
            league_slug=league_slug,
            league_name=league_name,
            weekly_match=weekly_match,
            event_id=event_id,
            competition_id=competition_id,
        )
        status_state = self._extract_status_state(
            weekly_match.event.status,
            weekly_match.competition.status,
        )
        home_team = self._find_team_name(weekly_match=weekly_match, side="home")
        away_team = self._find_team_name(weekly_match=weekly_match, side="away")
        return MatchScheduleRecord(
            event_id=event_id,
            league_slug=league_slug,
            league_name=league_name,
            competition_id=competition_id,
            kickoff_utc=kickoff_utc,
            status_state=status_state,
            home_team=home_team,
            away_team=away_team,
            payload_json=json.dumps(
                match_record.model_dump(mode="json"),
                ensure_ascii=False,
            ),
            updated_at=now_utc,
        )

    @staticmethod
    def _build_match_record(
        league_slug: str,
        league_name: str,
        weekly_match: WeeklyMatchModel,
        event_id: str,
        competition_id: str,
    ) -> MatchRecordModel:
        """Map weekly match payload into dossier-compatible match record."""

        return MatchRecordModel(
            league=LeagueModel(slug=league_slug, name=league_name),
            event=EventModel(
                id=weekly_match.event.id,
                uid=weekly_match.event.uid,
                date=weekly_match.event.date,
                name=weekly_match.event.name,
                short_name=weekly_match.event.short_name,
                status=weekly_match.event.status,
            ),
            competition=CompetitionModel(
                id=weekly_match.competition.id,
                uid=weekly_match.competition.uid,
                date=weekly_match.competition.date,
                status=weekly_match.competition.status,
            ),
            teams=[
                TeamIdentifiersModel(
                    side=team.side,
                    competitor_id=team.competitor_id,
                    competitor_uid=team.competitor_uid,
                    team=TeamModel(
                        id=team.team_id,
                        uid=team.team_uid,
                        slug=team.team_slug,
                        abbreviation=team.abbreviation,
                        display_name=team.display_name,
                        name=team.display_name,
                    ),
                    score=team.score,
                )
                for team in weekly_match.teams
            ],
            api_refs=ApiReferencesModel(
                summary=SUMMARY_URL_TEMPLATE.format(
                    league_slug=league_slug,
                    event_id=event_id,
                ),
                core_competition=CORE_COMPETITION_URL_TEMPLATE.format(
                    league_slug=league_slug,
                    event_id=event_id,
                    competition_id=competition_id,
                ),
            ),
        )

    @staticmethod
    def _parse_datetime_to_europe_rome(raw_value: str | None) -> datetime | None:
        """Parse kickoff datetime into Europe/Rome timezone."""

        if raw_value is None:
            return None
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return None
        from zoneinfo import ZoneInfo
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Rome"))
        return parsed.astimezone(ZoneInfo("Europe/Rome"))

    @staticmethod
    def _extract_status_state(
        event_status: dict[str, object] | None,
        competition_status: dict[str, object] | None,
    ) -> str:
        """Extract one lowercase status state from weekly status objects."""

        for status in (event_status, competition_status):
            if not isinstance(status, dict):
                continue
            status_type = status.get("type")
            if not isinstance(status_type, dict):
                continue
            state = status_type.get("state")
            if isinstance(state, str) and state:
                return state.lower()
        return "unknown"

    @staticmethod
    def _find_team_name(weekly_match: WeeklyMatchModel, side: str) -> str:
        """Return team display name for requested side."""

        for team in weekly_match.teams:
            if team.side == side and team.display_name:
                return team.display_name
        if weekly_match.teams:
            fallback = weekly_match.teams[0].display_name
            if fallback:
                return fallback
        return "Unknown Team"

