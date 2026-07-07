"""Tests for the weekly date window anchoring (local vs UTC boundary)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from src.schedule.weekly import local_week_dates

ROME = ZoneInfo("Europe/Rome")


class TestLocalWeekDates:
    def test_midnight_monday_rome_gives_current_week_not_previous(self) -> None:
        # 2026-07-06 00:00 CEST == 2026-07-05 22:00 UTC. Anchored to Rome it is
        # Monday, so the week must start today (Jul 6), not the finished week.
        now_utc = datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc)
        dates = local_week_dates(now_utc, ROME)
        assert dates[0] == date(2026, 7, 6)
        assert dates[-1] == date(2026, 7, 12)

    def test_returns_seven_consecutive_days_monday_to_sunday(self) -> None:
        now_utc = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)  # Wednesday
        dates = local_week_dates(now_utc, ROME)
        assert len(dates) == 7
        assert dates[0].weekday() == 0 and dates[-1].weekday() == 6
        assert dates[0] == date(2026, 7, 6)

    def test_falls_back_to_utc_when_no_timezone(self) -> None:
        now_utc = datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc)  # UTC Sunday
        dates = local_week_dates(now_utc, None)
        assert dates[0] == date(2026, 6, 29)  # UTC week (documents fallback)
