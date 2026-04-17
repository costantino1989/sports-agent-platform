"""Grouping helpers for weekly scheduled matches output."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment]

from src.models.weekly_models import (
    WeeklyDataTree,
    WeeklyLeagueScheduleModel,
    WeeklyMatchModel,
)

def _resolve_italy_timezone() -> tzinfo | None:
    """Resolve Europe/Rome timezone when available in runtime tz database.

    Returns:
        ZoneInfo timezone for Europe/Rome when available, otherwise None.
    """

    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo("Europe/Rome")
    except ZoneInfoNotFoundError:
        return None


ITALY_TIMEZONE = _resolve_italy_timezone()


class WeeklyDataGrouper:
    """Group weekly matches by date, league, and kickoff time."""

    def group_matches(
        self,
        matches: list[tuple[str, str, WeeklyMatchModel]],
    ) -> WeeklyDataTree:
        """Group and sort matches by date, league slug, and time.

        Args:
            matches: Flat list of tuples ``(league_slug, league_name, match)``.

        Returns:
            Nested dictionary in the format:
            date -> league -> {description, matches_by_time}.
        """

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
        """Extract normalized Italy date/time keys from one match.

        Args:
            match: Weekly match model.

        Returns:
            Tuple of Italy date key (YYYY-MM-DD) and time key (HH:MM).
        """

        date_value = match.event.date or match.competition.date or ""
        parsed_datetime = self._parse_italy_datetime(date_value)
        if parsed_datetime:
            return parsed_datetime.date().isoformat(), parsed_datetime.strftime("%H:%M")
        if len(date_value) >= 10:
            return date_value[:10], "00:00"
        return "unknown-date", "00:00"

    def _localize_match_dates(self, match: WeeklyMatchModel) -> WeeklyMatchModel:
        """Return a copy of match with event/competition dates in Italy timezone.

        Args:
            match: Weekly match model.

        Returns:
            Match copy with localized event and competition date fields.
        """

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
        """Convert an ISO-like datetime string to Italy timezone ISO format.

        Args:
            value: Date-time string from ESPN payload.

        Returns:
            Italy timezone ISO string when conversion succeeds; otherwise original value.
        """

        if value is None:
            return None
        parsed = self._parse_italy_datetime(value=value)
        if parsed is None:
            return value
        return parsed.isoformat()

    def _parse_italy_datetime(self, value: str) -> datetime | None:
        """Parse an ISO-like datetime string and normalize it to Italy timezone.

        Args:
            value: Date-time string from ESPN payload.

        Returns:
            Italy timezone datetime when parse succeeds; otherwise None.
        """

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
        """Convert a UTC datetime into Italy local time.

        Args:
            utc_datetime: A timezone-aware UTC datetime.

        Returns:
            Datetime converted to Italy local time.
        """

        if ITALY_TIMEZONE is not None:
            return utc_datetime.astimezone(ITALY_TIMEZONE)
        return self._convert_without_zoneinfo(utc_datetime=utc_datetime)

    def _convert_without_zoneinfo(self, utc_datetime: datetime) -> datetime:
        """Convert UTC to Italy time using EU DST rules without zoneinfo.

        Args:
            utc_datetime: A timezone-aware UTC datetime.

        Returns:
            Italy-local datetime with either CET or CEST offset.
        """

        offset_hours = 2 if self._is_italy_dst(utc_datetime=utc_datetime) else 1
        fallback_timezone = timezone(timedelta(hours=offset_hours))
        return utc_datetime.astimezone(fallback_timezone)

    def _is_italy_dst(self, utc_datetime: datetime) -> bool:
        """Return whether Italy DST is active for a UTC datetime.

        Args:
            utc_datetime: A timezone-aware UTC datetime.

        Returns:
            True when DST (CEST) is active, otherwise False.
        """

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
        """Return the calendar date of the last Sunday for a month.

        Args:
            year: Target year.
            month: Target month.

        Returns:
            Date object representing the month's last Sunday.
        """

        if month == 12:
            first_of_next_month = date(year + 1, 1, 1)
        else:
            first_of_next_month = date(year, month + 1, 1)
        last_day_of_month = first_of_next_month - timedelta(days=1)
        days_since_sunday = (last_day_of_month.weekday() + 1) % 7
        return last_day_of_month - timedelta(days=days_since_sunday)
