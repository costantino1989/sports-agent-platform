"""Unified weekly match logic for schedule module."""

from __future__ import annotations
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, TypeAlias

from src.espn import EspnApiError, EspnSoccerClient
from src.models.leagues import LEAGUES, LeagueDefinition
from src.models.weekly_models import (
    WeeklyCompetitionModel,
    WeeklyEventModel,
    WeeklyMatchModel,
    WeeklyMatchesPayloadModel,
    WeeklyTeamModel,
    WeeklyDataTree,
    WeeklyLeagueScheduleModel,
)
from src.utils import get_logger
from src.utils.timing import log_execution_time

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment]

JsonDict: TypeAlias = dict[str, Any]
LOGGER = get_logger()

# --- Scoreboard Fetching ---
@dataclass(slots=True, frozen=True)
class ScoreboardFetchTask:
    league: LeagueDefinition
    date_key: str

@dataclass(slots=True, frozen=True)
class ScoreboardFetchResult:
    task: ScoreboardFetchTask
    scoreboard: JsonDict | None
    error: str | None = None

SCOREBOARD_BY_DATE_URL_TEMPLATE = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/scoreboard"
    "?dates={date_key}"
)
DEFAULT_WEEKLY_WORKERS = 20

class WeeklyScoreboardCollector:
    def __init__(self, client: EspnSoccerClient, max_workers: int = DEFAULT_WEEKLY_WORKERS) -> None:
        self._client = client
        self._max_workers = max_workers

    def collect(self, leagues: tuple[LeagueDefinition, ...], week_dates: list[date]) -> list[ScoreboardFetchResult]:
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
        return sorted(results, key=lambda result: (result.task.league.slug, result.task.date_key))

    def _build_tasks(self, leagues: tuple[LeagueDefinition, ...], week_dates: list[date]) -> list[ScoreboardFetchTask]:
        return [
            ScoreboardFetchTask(league=league, date_key=match_date.strftime("%Y%m%d"))
            for league in leagues
            for match_date in week_dates
        ]

    def _fetch_task(self, task: ScoreboardFetchTask) -> ScoreboardFetchResult:
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
                    f"Unexpected payload type for scoreboard '{task.league.slug}' and date '{task.date_key}'."
                ),
            )
        return ScoreboardFetchResult(task=task, scoreboard=payload)

# --- Filtering ---
class WeeklyUpcomingFilter:
    def is_upcoming_match(self, event: JsonDict, competition: JsonDict, now_utc: datetime) -> bool:
        event_status = event.get("status")
        competition_status = competition.get("status")
        states = {
            self._extract_status_state(event_status),
            self._extract_status_state(competition_status),
        }
        if "post" in states or "in" in states:
            return False
        if self._extract_status_completed(event_status):
            return False
        if self._extract_status_completed(competition_status):
            return False
        kickoff = self._extract_kickoff_datetime(event=event, competition=competition)
        if kickoff is None:
            return "pre" in states
        return kickoff > now_utc

    def _extract_status_state(self, status: Any) -> str | None:
        if not isinstance(status, dict):
            return None
        type_obj = status.get("type")
        if not isinstance(type_obj, dict):
            return None
        state = type_obj.get("state")
        return state.lower() if isinstance(state, str) else None

    def _extract_status_completed(self, status: Any) -> bool:
        if not isinstance(status, dict):
            return False
        type_obj = status.get("type")
        if not isinstance(type_obj, dict):
            return False
        completed = type_obj.get("completed")
        return bool(completed)

    def _extract_kickoff_datetime(self, event: JsonDict, competition: JsonDict) -> datetime | None:
        for obj in (event, competition):
            value = obj.get("date")
            dt = self._parse_datetime(value)
            if dt:
                return dt
        return None

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

# --- Grouping ---
def _resolve_italy_timezone() -> tzinfo | None:
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo("Europe/Rome")
    except ZoneInfoNotFoundError:
        return None

ITALY_TIMEZONE = _resolve_italy_timezone()


def local_week_dates(now_utc: datetime, local_tz: tzinfo | None) -> list[date]:
    """Return the 7 dates (Monday..Sunday) of the week containing ``now_utc``.

    The week is anchored to the local calendar day, not UTC: the cron runs at
    00:00 Europe/Rome (22:00 UTC the day before), so anchoring to UTC would sync
    the week that just ended. When no timezone is available, falls back to UTC.

    Args:
        now_utc: The current instant (timezone-aware, typically UTC).
        local_tz: The local timezone to anchor the week to, or ``None`` for UTC.

    Returns:
        Seven consecutive ``date`` objects from the Monday to the Sunday of the
        local week containing ``now_utc``.
    """
    reference = now_utc.astimezone(local_tz) if local_tz is not None else now_utc
    today = reference.date()
    week_start = today - timedelta(days=today.weekday())
    return [week_start + timedelta(days=offset) for offset in range(7)]

class WeeklyDataGrouper:
    def group_matches(self, matches: list[tuple[str, str, WeeklyMatchModel]]) -> WeeklyDataTree:
        grouped: dict[str, dict[str, WeeklyLeagueScheduleModel]] = {}
        for league_slug, league_name, match in matches:
            localized_match = self._localize_match_dates(match=match)
            date_key, time_key = self._extract_date_time_keys(match=localized_match)
            league_bucket = grouped.setdefault(date_key, {}).setdefault(
                league_slug,
                WeeklyLeagueScheduleModel(
                    description=league_name,
                    matches_by_time={},
                ),
            )
            league_bucket.matches_by_time.setdefault(time_key, []).append(localized_match)
        ordered: WeeklyDataTree = {}
        for date_key in sorted(grouped):
            leagues = grouped[date_key]
            ordered[date_key] = {}
            for league_slug in sorted(leagues):
                league_bucket = leagues[league_slug]
                sorted_times: dict[str, list[WeeklyMatchModel]] = {}
                for time_key in sorted(league_bucket.matches_by_time):
                    sorted_times[time_key] = sorted(
                        league_bucket.matches_by_time[time_key],
                        key=lambda item: (
                            item.event.date or "",
                            item.event.id or "",
                            item.event.name or "",
                        ),
                    )
                ordered[date_key][league_slug] = WeeklyLeagueScheduleModel(
                    description=league_bucket.description,
                    matches_by_time=sorted_times,
                )
        return ordered

    def _extract_date_time_keys(self, match: WeeklyMatchModel) -> tuple[str, str]:
        date_value = match.event.date or match.competition.date or ""
        parsed_datetime = self._parse_italy_datetime(date_value)
        if parsed_datetime:
            return parsed_datetime.date().isoformat(), parsed_datetime.strftime("%H:%M")
        if len(date_value) >= 10:
            return date_value[:10], "00:00"
        return "unknown-date", "00:00"

    def _localize_match_dates(self, match: WeeklyMatchModel) -> WeeklyMatchModel:
        event_date = self._to_italy_iso(value=match.event.date)
        competition_date = self._to_italy_iso(value=match.competition.date)
        if event_date == match.event.date and competition_date == match.competition.date:
            return match
        return WeeklyMatchModel(
            event=match.event.model_copy(update={"date": event_date}),
            competition=match.competition.model_copy(update={"date": competition_date}),
            teams=match.teams,
        )

    def _to_italy_iso(self, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = self._parse_italy_datetime(value=value)
        if parsed is None:
            return value
        return parsed.isoformat()

    def _parse_italy_datetime(self, value: str) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        utc_datetime = parsed.astimezone(timezone.utc)
        return self._to_italy_timezone(utc_datetime=utc_datetime)

    def _to_italy_timezone(self, utc_datetime: datetime) -> datetime:
        if ITALY_TIMEZONE is not None:
            return utc_datetime.astimezone(ITALY_TIMEZONE)
        return self._convert_without_zoneinfo(utc_datetime=utc_datetime)

    def _convert_without_zoneinfo(self, utc_datetime: datetime) -> datetime:
        offset_hours = 2 if self._is_italy_dst(utc_datetime=utc_datetime) else 1
        fallback_timezone = timezone(timedelta(hours=offset_hours))
        return utc_datetime.astimezone(fallback_timezone)

    def _is_italy_dst(self, utc_datetime: datetime) -> bool:
        year = utc_datetime.year
        march_last_sunday = self._last_sunday_of_month(year=year, month=3)
        october_last_sunday = self._last_sunday_of_month(year=year, month=10)
        dst_start_utc = datetime(
            year=year,
            month=3,
            day=march_last_sunday.day,
            hour=1,
            tzinfo=timezone.utc,
        )
        dst_end_utc = datetime(
            year=year,
            month=10,
            day=october_last_sunday.day,
            hour=1,
            tzinfo=timezone.utc,
        )
        return dst_start_utc <= utc_datetime < dst_end_utc

    def _last_sunday_of_month(self, year: int, month: int) -> date:
        if month == 12:
            first_of_next_month = date(year + 1, 1, 1)
        else:
            first_of_next_month = date(year, month + 1, 1)
        last_day_of_month = first_of_next_month - timedelta(days=1)
        days_since_sunday = (last_day_of_month.weekday() + 1) % 7
        return last_day_of_month - timedelta(days=days_since_sunday)

# --- Main Weekly Action ---
class WeeklyMatchesAction:
    def __init__(
        self,
        client: EspnSoccerClient,
        collector: WeeklyScoreboardCollector | None = None,
        upcoming_filter: WeeklyUpcomingFilter | None = None,
        grouper: WeeklyDataGrouper | None = None,
    ) -> None:
        self._collector = collector or WeeklyScoreboardCollector(client=client)
        self._upcoming_filter = upcoming_filter or WeeklyUpcomingFilter()
        self._grouper = grouper or WeeklyDataGrouper()

    @log_execution_time
    def run(self, output_path: Path) -> WeeklyMatchesPayloadModel:
        payload = self.collect_current_week()
        self._write_json(output_path=output_path, payload=payload)
        LOGGER.info(
            f"Weekly collection completed with {payload.match_count} upcoming matches "
            f"and {len(payload.fetch_errors)} fetch errors."
        )
        return payload

    def collect_current_week(self) -> WeeklyMatchesPayloadModel:
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
        return payload

    @staticmethod
    def _current_week_dates_utc() -> list[date]:
        return local_week_dates(datetime.now(timezone.utc), ITALY_TIMEZONE)

    def _extract_matches(
        self,
        league: LeagueDefinition,
        scoreboard_payload: JsonDict,
        seen_keys: set[str],
        now_utc: datetime,
    ) -> list[WeeklyMatchModel]:
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

    @staticmethod
    def _build_dedupe_key(
        league_slug: str,
        event: JsonDict,
        competition: JsonDict,
    ) -> str:
        event_ref = event.get("id") or event.get("uid") or event.get("name") or "unknown-event"
        competition_ref = (
            competition.get("id")
            or competition.get("uid")
            or competition.get("date")
            or "unknown-competition"
        )
        return f"{league_slug}:{event_ref}:{competition_ref}"

    @staticmethod
    def _build_event_model(event: JsonDict) -> WeeklyEventModel:
        return WeeklyEventModel(
            id=event.get("id"),
            uid=event.get("uid"),
            date=event.get("date"),
            name=event.get("name"),
            short_name=event.get("shortName"),
            status=event.get("status"),
        )

    @staticmethod
    def _build_competition_model(competition: JsonDict) -> WeeklyCompetitionModel:
        return WeeklyCompetitionModel(
            id=competition.get("id"),
            uid=competition.get("uid"),
            date=competition.get("date"),
            status=competition.get("status"),
        )

    @staticmethod
    def _build_team_models(competition: JsonDict) -> list[WeeklyTeamModel]:
        teams = competition.get("competitors", [])
        if not isinstance(teams, list):
            return []
        return [
            WeeklyTeamModel(
                side=team.get("homeAway"),
                competitor_id=team.get("id"),
                competitor_uid=team.get("uid"),
                team_id=team.get("team", {}).get("id"),
                team_uid=team.get("team", {}).get("uid"),
                team_slug=team.get("team", {}).get("slug"),
                abbreviation=team.get("team", {}).get("abbreviation"),
                display_name=team.get("team", {}).get("displayName"),
                score=team.get("score"),
            )
            for team in teams if isinstance(team, dict)
        ]
