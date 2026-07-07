"""Characterization tests for the weekly upcoming-match filter."""

from __future__ import annotations

from datetime import datetime, timezone

from src.schedule.weekly import WeeklyUpcomingFilter

NOW = datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc)


def _status(state: str, completed: bool = False) -> dict:
    return {"type": {"state": state, "completed": completed}}


class TestIsUpcomingMatch:
    """Tests for WeeklyUpcomingFilter.is_upcoming_match."""

    def setup_method(self) -> None:
        self.filter = WeeklyUpcomingFilter()

    def test_future_pre_match_is_upcoming(self) -> None:
        event = {"status": _status("pre"), "date": "2026-04-22T18:00Z"}
        assert self.filter.is_upcoming_match(event, {}, NOW) is True

    def test_in_progress_is_not_upcoming(self) -> None:
        event = {"status": _status("in"), "date": "2026-04-22T18:00Z"}
        assert self.filter.is_upcoming_match(event, {}, NOW) is False

    def test_post_match_is_not_upcoming(self) -> None:
        event = {"status": _status("post"), "date": "2026-04-22T09:00Z"}
        assert self.filter.is_upcoming_match(event, {}, NOW) is False

    def test_completed_flag_excludes_match(self) -> None:
        event = {"status": _status("pre", completed=True), "date": "2026-04-22T18:00Z"}
        assert self.filter.is_upcoming_match(event, {}, NOW) is False

    def test_past_kickoff_is_not_upcoming(self) -> None:
        event = {"status": _status("pre"), "date": "2026-04-22T09:00Z"}
        assert self.filter.is_upcoming_match(event, {}, NOW) is False

    def test_missing_kickoff_falls_back_to_pre_state(self) -> None:
        event = {"status": _status("pre")}
        assert self.filter.is_upcoming_match(event, {}, NOW) is True

    def test_missing_kickoff_without_pre_state_is_not_upcoming(self) -> None:
        assert self.filter.is_upcoming_match({}, {}, NOW) is False

    def test_kickoff_read_from_competition_when_event_missing(self) -> None:
        event = {"status": _status("pre")}
        competition = {"date": "2026-04-22T18:00Z"}
        assert self.filter.is_upcoming_match(event, competition, NOW) is True
