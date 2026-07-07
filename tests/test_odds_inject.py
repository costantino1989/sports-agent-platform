"""Tests for injecting real market odds into a dossier's section 8."""

from __future__ import annotations

from datetime import datetime, timezone

from src.models.live_models import (
    ApiReferencesModel,
    CompetitionModel,
    EventModel,
    LeagueModel,
    MatchRecordModel,
    TeamIdentifiersModel,
    TeamModel,
)
from src.odds.dossier_odds import (
    extract_bookmaker_row,
    inject_market_odds,
    match_odds_query,
    merge_best_odds,
)
from src.odds.models import MatchOdds
from src.prediction.betting import parse_predicted_odds, select_predicted_odds

_ESPN_DOSSIER = (
    "## 7. News\nsomething\n\n"
    "## 8. Odds\n"
    "Complete market view using ESPN odds snapshots.\n\n"
    "1X2 odds (decimal):\n\n"
    "| Provider | Snapshot | 1 (Home) | X (Draw) | 2 (Away) |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| ESPN BET | Current | 9.9 | 8.8 | 7.7 |\n\n"
    "## 9. Single match details\nx\n"
)

_ODDS = MatchOdds(home=5.4, draw=3.4, away=1.9, bookmaker="betfair_ex_eu", last_update="t")

# An ESPN section 8 with two providers, DraftKings first then Bet 365.
_ESPN_MULTI = (
    "## 8. Odds\n"
    "1X2 odds (decimal):\n\n"
    "| Provider | Snapshot | 1 (Home) | X (Draw) | 2 (Away) |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| DraftKings | Current | 2.1 | 3.1 | 3.9 |\n"
    "| Bet 365 | Current | 2.0 | 3.2 | 4.1 |\n\n"
    "## 9. x\n"
)


class TestInjectMarketOdds:
    def test_betfair_row_takes_precedence_over_espn(self) -> None:
        merged = inject_market_odds(_ESPN_DOSSIER, _ODDS)
        # The predicted-odds parser must now return the Betfair price, not ESPN's.
        assert parse_predicted_odds(merged, "1") == 5.4
        assert parse_predicted_odds(merged, "X") == 3.4
        assert parse_predicted_odds(merged, "2") == 1.9
        assert "Betfair" in merged
        assert "9.9" in merged  # ESPN block retained as secondary reference

    def test_missing_section_8_appends_block(self) -> None:
        merged = inject_market_odds("## 1. Snapshot\nx\n", _ODDS)
        assert parse_predicted_odds(merged, "2") == 1.9


class TestExtractBookmakerRow:
    def test_extracts_bet365_row_ignoring_draftkings(self) -> None:
        odds = extract_bookmaker_row(_ESPN_MULTI, ["Bet 365"])
        assert odds is not None
        assert (odds.home, odds.draw, odds.away) == (2.0, 3.2, 4.1)  # Bet 365 row
        assert odds.bookmaker == "Bet 365"

    def test_matches_bet365_written_without_space(self) -> None:
        odds = extract_bookmaker_row(_ESPN_MULTI, ["bet365"])
        assert odds is not None and odds.home == 2.0

    def test_returns_none_when_provider_absent(self) -> None:
        assert extract_bookmaker_row(_ESPN_MULTI, ["Pinnacle"]) is None


class TestMergeBestOdds:
    def test_prefers_betfair_when_present(self) -> None:
        merged = merge_best_odds(_ESPN_MULTI, _ODDS, ["Bet 365"])
        assert parse_predicted_odds(merged, "1") == 5.4     # Betfair wins

    def test_falls_back_to_bet365_when_no_betfair(self) -> None:
        merged = merge_best_odds(_ESPN_MULTI, None, ["Bet 365"])
        assert parse_predicted_odds(merged, "1") == 2.0     # Bet 365, not DraftKings
        assert parse_predicted_odds(merged, "2") == 4.1

    def test_unchanged_when_no_betfair_and_no_fallback_provider(self) -> None:
        merged = merge_best_odds(_ESPN_MULTI, None, ["Pinnacle"])
        # No preferred row injected -> parser keeps ESPN's first row (DraftKings).
        assert parse_predicted_odds(merged, "1") == 2.1


def _match() -> MatchRecordModel:
    return MatchRecordModel(
        league=LeagueModel(slug="fifa.world", name="World Cup"),
        event=EventModel(id="e1", date="2026-07-04T17:00Z"),
        competition=CompetitionModel(id="c"),
        teams=[
            TeamIdentifiersModel(homeAway="home", team=TeamModel(displayName="Canada")),
            TeamIdentifiersModel(homeAway="away", team=TeamModel(displayName="Morocco")),
        ],
        api_refs=ApiReferencesModel(summary="s", core_competition="c"),
    )


class TestParsePrefersLiveOdds:
    # ESPN lists a pre-match row and a separate live-odds row, both "Current".
    _ESPN_LIVE = (
        "## 8. Odds\n"
        "1X2 odds (decimal):\n\n"
        "| Provider | Snapshot | 1 (Home) | X (Draw) | 2 (Away) |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| DraftKings | Current | 1.6 | 3.9 | 5.0 |\n"
        "| DraftKings - Live Odds | Current | 8.0 | 5.25 | 1.29 |\n\n"
    )

    def test_live_row_preferred_over_prematch(self) -> None:
        # Away is winning; the live row (1.29) must win over the stale 5.0.
        assert parse_predicted_odds(self._ESPN_LIVE, "2") == 1.29
        assert parse_predicted_odds(self._ESPN_LIVE, "1") == 8.0

    def test_injected_exchange_still_wins_over_espn_live(self) -> None:
        # A Betfair Exchange row injected at the top must stay the chosen odds.
        merged = inject_market_odds(self._ESPN_LIVE, _ODDS)  # bookmaker betfair_ex_eu
        assert parse_predicted_odds(merged, "1") == 5.4  # Betfair home price

    def test_plain_current_used_when_no_live_row(self) -> None:
        assert parse_predicted_odds(_ESPN_MULTI, "1") == 2.1  # first plain Current


class TestSelectPredictedOdds:
    def test_returns_value_and_bookmaker_of_chosen_row(self) -> None:
        pick = select_predicted_odds(_ESPN_MULTI, "1")
        assert pick == (2.1, "DraftKings")  # first plain Current

    def test_reports_live_provider(self) -> None:
        markdown = (
            "1X2 odds (decimal):\n\n"
            "| Provider | Snapshot | 1 (Home) | X (Draw) | 2 (Away) |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| DraftKings | Current | 1.6 | 3.9 | 5.0 |\n"
            "| DraftKings - Live Odds | Current | 8.0 | 5.25 | 1.29 |\n"
        )
        pick = select_predicted_odds(markdown, "2")
        assert pick == (1.29, "DraftKings - Live Odds")

    def test_reports_injected_exchange_bookmaker(self) -> None:
        merged = inject_market_odds(_ESPN_MULTI, _ODDS)  # betfair_ex_eu -> Betfair Exchange
        odds, bookmaker = select_predicted_odds(merged, "1")
        assert odds == 5.4
        assert "Betfair" in bookmaker

    def test_returns_none_when_no_odds(self) -> None:
        assert select_predicted_odds("no table here", "1") is None


class TestSelectOnlyAllowedBookmakers:
    _ESPN_DK_ONLY = (
        "1X2 odds (decimal):\n\n"
        "| Provider | Snapshot | 1 (Home) | X (Draw) | 2 (Away) |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| DraftKings | Current | 1.6 | 3.9 | 5.0 |\n"
        "| DraftKings - Live Odds | Current | 8.0 | 5.25 | 1.29 |\n"
    )
    _HINTS = ("betfair", "bet365")

    def test_none_when_only_disallowed_bookmakers(self) -> None:
        # DraftKings is not Betfair/Bet365 -> no usable odds.
        assert select_predicted_odds(self._ESPN_DK_ONLY, "2", self._HINTS) is None

    def test_picks_betfair_when_allowed(self) -> None:
        merged = inject_market_odds(self._ESPN_DK_ONLY, _ODDS)  # Betfair Exchange
        odds, book = select_predicted_odds(merged, "1", self._HINTS)
        assert odds == 5.4 and "Betfair" in book

    def test_picks_bet365_row_when_allowed(self) -> None:
        markdown = self._ESPN_DK_ONLY + "| Bet 365 | Current | 2.0 | 3.2 | 4.1 |\n"
        odds, book = select_predicted_odds(markdown, "1", self._HINTS)
        assert odds == 2.0 and "365" in book

    def test_no_hints_keeps_old_behaviour(self) -> None:
        # Without hints, any provider is allowed (backward compatible).
        assert select_predicted_odds(self._ESPN_DK_ONLY, "2") == (1.29, "DraftKings - Live Odds")


class TestMatchOddsQuery:
    def test_extracts_league_teams_kickoff(self) -> None:
        query = match_odds_query(_match())
        assert query.league_slug == "fifa.world"
        assert query.home_team == "Canada"
        assert query.away_team == "Morocco"
        assert query.kickoff_utc == datetime(2026, 7, 4, 17, 0, tzinfo=timezone.utc)

    def test_missing_date_yields_none_kickoff(self) -> None:
        match = _match()
        match.event.date = None
        assert match_odds_query(match).kickoff_utc is None

    def test_resolves_names_from_name_and_order_when_side_missing(self) -> None:
        # Persisted records carry the name in ``name`` (not ``display_name``) and
        # have ``side`` unset; home/away must still resolve (by team order).
        match = MatchRecordModel(
            league=LeagueModel(slug="swe.1", name="Allsvenskan"),
            event=EventModel(id="e1", date="2026-07-05T12:00Z"),
            competition=CompetitionModel(id="c"),
            teams=[
                TeamIdentifiersModel(team=TeamModel(name="Kalmar FF")),
                TeamIdentifiersModel(team=TeamModel(name="Örgryte IS")),
            ],
            api_refs=ApiReferencesModel(summary="s", core_competition="c"),
        )
        query = match_odds_query(match)
        assert query.home_team == "Kalmar FF"   # first team = home
        assert query.away_team == "Örgryte IS"  # second team = away

    def test_side_takes_precedence_over_order(self) -> None:
        # When side IS present it wins, even if the order is reversed.
        match = MatchRecordModel(
            league=LeagueModel(slug="swe.1", name="Allsvenskan"),
            event=EventModel(id="e1", date="2026-07-05T12:00Z"),
            competition=CompetitionModel(id="c"),
            teams=[
                TeamIdentifiersModel(homeAway="away", team=TeamModel(name="Away FC")),
                TeamIdentifiersModel(homeAway="home", team=TeamModel(name="Home FC")),
            ],
            api_refs=ApiReferencesModel(summary="s", core_competition="c"),
        )
        query = match_odds_query(match)
        assert query.home_team == "Home FC"
        assert query.away_team == "Away FC"
