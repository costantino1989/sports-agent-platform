"""Tests for the today's-matches page data builder."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.models.schedule import MatchScheduleRecord
from src.prediction.today import build_today_data
from src.schedule.repositories.status_repo import MatchStatus

ROME = ZoneInfo("Europe/Rome")
NOW = datetime(2026, 7, 5, 20, 0, tzinfo=ROME)


def _rec(event_id: str, *, slug: str, kickoff: datetime, home="Home", away="Away"):
    return MatchScheduleRecord(
        event_id=event_id,
        league_slug=slug,
        league_name=slug.upper(),
        competition_id=f"c{event_id}",
        kickoff_utc=kickoff,
        home_team=home,
        away_team=away,
        payload_json="{}",
        updated_at=NOW,
    )


class TestBuildTodayData:
    def test_only_todays_matches_are_included(self) -> None:
        today = _rec("t", slug="ita.1", kickoff=NOW + timedelta(hours=1))
        tomorrow = _rec("m", slug="ita.1", kickoff=NOW + timedelta(days=1))
        rows = build_today_data([today, tomorrow], {}, now=NOW)
        assert [row["eventId"] for row in rows] == ["t"]

    def test_rows_sorted_by_kickoff(self) -> None:
        late = _rec("late", slug="ita.1", kickoff=NOW + timedelta(hours=3))
        early = _rec("early", slug="ita.1", kickoff=NOW + timedelta(hours=1))
        rows = build_today_data([late, early], {}, now=NOW)
        assert [row["eventId"] for row in rows] == ["early", "late"]

    def test_upcoming_unknown_league_is_in_programma(self) -> None:
        row = build_today_data(
            [_rec("t", slug="ita.1", kickoff=NOW + timedelta(hours=1))], {}, now=NOW
        )[0]
        assert row["statusKind"] == "upcoming"
        assert "21:00" in row["time"]  # 20:00 + 1h, Rome time

    def test_skipped_no_play_by_play_shows_reason(self) -> None:
        rec = _rec("t", slug="usa.usl.1", kickoff=NOW - timedelta(minutes=10))
        statuses = {"t": MatchStatus("skip", "no_play_by_play", NOW.isoformat())}
        row = build_today_data([rec], statuses, now=NOW)[0]
        assert row["statusKind"] == "skipped"
        assert "play-by-play" in row["reason"].lower()

    def test_bet_locked_status(self) -> None:
        rec = _rec("t", slug="ita.1", kickoff=NOW - timedelta(minutes=30))
        statuses = {"t": MatchStatus("predict", "locked_bet", NOW.isoformat())}
        row = build_today_data([rec], statuses, now=NOW)[0]
        assert row["statusKind"] == "bet"

    def test_no_usable_odds_status(self) -> None:
        rec = _rec("t", slug="usa.usl.1", kickoff=NOW - timedelta(minutes=30))
        statuses = {"t": MatchStatus("predict", "no_usable_odds", NOW.isoformat())}
        row = build_today_data([rec], statuses, now=NOW)[0]
        assert row["statusKind"] == "no-book"
        assert "betfair" in row["reason"].lower() or "bet365" in row["reason"].lower()

    def test_upcoming_match_of_uncovered_league_flagged_likely_skip(self) -> None:
        # An earlier USL match today was skipped for no play-by-play; a later USL
        # match not yet evaluated should be flagged as a likely skip.
        earlier = _rec("done", slug="usa.usl.1", kickoff=NOW - timedelta(minutes=30))
        later = _rec("next", slug="usa.usl.1", kickoff=NOW + timedelta(hours=1))
        statuses = {"done": MatchStatus("skip", "no_play_by_play", NOW.isoformat())}
        rows = build_today_data([earlier, later], statuses, now=NOW)
        by_id = {row["eventId"]: row for row in rows}
        assert by_id["next"]["statusKind"] == "likely-skip"
        assert "play-by-play" in by_id["next"]["reason"].lower()

    def test_upcoming_match_of_covered_league_flagged_likely_tracked(self) -> None:
        earlier = _rec("done", slug="bra.1", kickoff=NOW - timedelta(minutes=30))
        later = _rec("next", slug="bra.1", kickoff=NOW + timedelta(hours=1))
        statuses = {"done": MatchStatus("predict", "goal_against_pick", NOW.isoformat())}
        rows = build_today_data([earlier, later], statuses, now=NOW)
        by_id = {row["eventId"]: row for row in rows}
        assert by_id["next"]["statusKind"] == "likely-tracked"

    def test_stable_tracking_of_long_finished_match_shows_conclusa(self) -> None:
        # A match kicked off 4h ago can no longer be "in tracking": it is over.
        # ESPN status lag left its last decision frozen at skip/stable, but the
        # page must not show it as still being followed live.
        rec = _rec("t", slug="fifa.world", kickoff=NOW - timedelta(hours=4))
        statuses = {"t": MatchStatus("skip", "stable", NOW.isoformat())}
        row = build_today_data([rec], statuses, now=NOW)[0]
        assert row["statusKind"] == "done"
        assert row["statusLabel"] == "Conclusa"

    def test_recent_stable_tracking_still_in_tracking(self) -> None:
        # Guard: a match still within its live window keeps the tracking label.
        rec = _rec("t", slug="ita.1", kickoff=NOW - timedelta(minutes=30))
        statuses = {"t": MatchStatus("skip", "stable", NOW.isoformat())}
        row = build_today_data([rec], statuses, now=NOW)[0]
        assert row["statusKind"] == "tracked"
        assert "stabile" in row["statusLabel"].lower()

    def test_no_book_tracking_of_long_finished_match_shows_conclusa(self) -> None:
        rec = _rec("t", slug="usa.usl.1", kickoff=NOW - timedelta(hours=4))
        statuses = {"t": MatchStatus("predict", "no_usable_odds", NOW.isoformat())}
        row = build_today_data([rec], statuses, now=NOW)[0]
        assert row["statusKind"] == "done"

    def test_long_started_match_without_status_shows_conclusa(self) -> None:
        # Started 5h ago, never evaluated (e.g. cron gap): it is over, not pending.
        rec = _rec("t", slug="ita.1", kickoff=NOW - timedelta(hours=5))
        row = build_today_data([rec], {}, now=NOW)[0]
        assert row["statusKind"] == "done"
