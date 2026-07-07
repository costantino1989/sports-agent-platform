"""Tests for the API-Football provider (odds + events)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.odds.apifootball import ApiFootballProvider

# One day's fixtures (as /fixtures?date returns them), one match, league 255.
_DAY_FIXTURES = [
    {
        "fixture": {"id": 1, "date": "2026-07-05T01:00:00+00:00"},
        "league": {"id": 255},
        "teams": {"home": {"name": "Tampa Bay Rowdies"}, "away": {"name": "Lexington"}},
    }
]
# That fixture's odds (as /odds?fixture returns them).
_FIXTURE_ODDS = [
    {
        "fixture": {"id": 1},
        "bookmakers": [
            {"name": "Betfair", "bets": [{"name": "Match Winner", "values": [
                {"value": "Home", "odd": "1.70"}, {"value": "Draw", "odd": "3.60"},
                {"value": "Away", "odd": "4.40"}]}]},
            {"name": "Bet365", "bets": [{"name": "Match Winner", "values": [
                {"value": "Home", "odd": "1.68"}, {"value": "Draw", "odd": "3.65"},
                {"value": "Away", "odd": "4.33"}]}]},
        ],
    }
]

KICKOFF = datetime(2026, 7, 5, 1, 0, tzinfo=timezone.utc)


def _provider(calls=None, fixtures=None, odds=None, events=None):
    calls = calls if calls is not None else []

    def http_get(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "fixtures":
            return fixtures if fixtures is not None else _DAY_FIXTURES
        if endpoint == "fixtures/events":
            return events or []
        if endpoint == "odds/live":
            return []  # no in-play match by default -> pre-match path
        return odds if odds is not None else _FIXTURE_ODDS

    return ApiFootballProvider(
        api_key="k", cache_minutes=3, preferred_bookmakers=("Bet365", "Betfair"),
        http_get=http_get, clock=lambda: KICKOFF, league_map={"usa.usl.1": 255},
    )


def _odds(prov):
    return prov.get_1x2_odds(
        league_slug="usa.usl.1", home_team="Tampa Bay Rowdies",
        away_team="Lexington", kickoff_utc=KICKOFF,
    )


class TestApiFootballOdds:
    def test_unmapped_league_returns_none_without_fetching(self) -> None:
        calls: list = []
        odds = _provider(calls).get_1x2_odds(
            league_slug="xyz.1", home_team="A", away_team="B", kickoff_utc=KICKOFF
        )
        assert odds is None and calls == []

    def test_no_kickoff_returns_none(self) -> None:
        assert _provider().get_1x2_odds(
            league_slug="usa.usl.1", home_team="Tampa Bay Rowdies",
            away_team="Lexington", kickoff_utc=None,
        ) is None

    def test_happy_path_prefers_bet365(self) -> None:
        odds = _odds(_provider())
        assert odds is not None
        assert (odds.home, odds.draw, odds.away) == (1.68, 3.65, 4.33)
        assert odds.bookmaker == "Bet365"

    def test_orientation_follows_espn_home_away(self) -> None:
        odds = _provider().get_1x2_odds(
            league_slug="usa.usl.1", home_team="Lexington",
            away_team="Tampa Bay Rowdies", kickoff_utc=KICKOFF,
        )
        assert odds is not None and odds.home == 4.33 and odds.away == 1.68

    def test_none_when_no_preferred_bookmaker(self) -> None:
        odds_1xbet = [{"fixture": {"id": 1}, "bookmakers": [
            {"name": "1xBet", "bets": [{"name": "Match Winner", "values": [
                {"value": "Home", "odd": "1.5"}, {"value": "Draw", "odd": "4"},
                {"value": "Away", "odd": "6"}]}]}]}]
        assert _odds(_provider(odds=odds_1xbet)) is None

    def test_none_when_fixture_not_found(self) -> None:
        assert _provider().get_1x2_odds(
            league_slug="usa.usl.1", home_team="Real Madrid",
            away_team="Barcelona", kickoff_utc=KICKOFF,
        ) is None

    def test_caches_fixtures_and_odds(self) -> None:
        calls: list = []
        prov = _provider(calls)
        _odds(prov)
        _odds(prov)
        # Each source fetched once (live feed, fixtures, pre-match odds), then cached.
        assert sorted({c[0] for c in calls}) == ["fixtures", "odds", "odds/live"]
        assert len(calls) == 3


class TestApiFootballLiveOdds:
    # /odds/live entry for fixture 1: live "Fulltime Result" (Home leading).
    _LIVE = [
        {
            "fixture": {"id": 1},
            "league": {"id": 255},
            "odds": [
                {"name": "Asian Handicap", "values": []},
                {"id": 59, "name": "Fulltime Result", "values": [
                    {"value": "Home", "odd": "1.30"},
                    {"value": "Draw", "odd": "5.00"},
                    {"value": "Away", "odd": "9.00"}]},
            ],
        }
    ]

    def _prov(self, live):
        def http_get(endpoint, params):
            if endpoint == "odds/live":
                return live
            if endpoint == "fixtures":
                return _DAY_FIXTURES
            return _FIXTURE_ODDS

        return ApiFootballProvider(
            api_key="k", cache_minutes=3, http_get=http_get,
            clock=lambda: KICKOFF, league_map={"usa.usl.1": 255},
        )

    def test_prefers_live_odds_when_in_play(self) -> None:
        odds = _odds(self._prov(self._LIVE))
        assert odds is not None
        assert (odds.home, odds.draw, odds.away) == (1.30, 5.00, 9.00)  # LIVE, not pre-match
        assert odds.bookmaker == "API-Football Live"

    def test_live_orientation_follows_espn_home(self) -> None:
        prov = self._prov(self._LIVE)
        odds = prov.get_1x2_odds(
            league_slug="usa.usl.1", home_team="Lexington",
            away_team="Tampa Bay Rowdies", kickoff_utc=KICKOFF,
        )
        assert odds.home == 9.00 and odds.away == 1.30  # swapped to ESPN sides

    def test_falls_back_to_prematch_when_not_live(self) -> None:
        # Empty live feed -> use pre-match Bet365 (1.68/3.65/4.33).
        odds = _odds(self._prov([]))
        assert odds.bookmaker == "Bet365" and odds.home == 1.68


class TestApiFootballEvents:
    def test_returns_parsed_events(self) -> None:
        events_resp = [
            {"time": {"elapsed": 12}, "team": {"name": "Lexington"},
             "player": {"name": "X. Zengue"}, "type": "Goal", "detail": "Normal Goal"},
            {"time": {"elapsed": 90, "extra": 3}, "team": {"name": "Tampa Bay Rowdies"},
             "player": {"name": "M. Myers"}, "type": "Card", "detail": "Yellow Card"},
        ]
        prov = _provider(events=events_resp)
        events = prov.fetch_events(
            league_slug="usa.usl.1", home_team="Tampa Bay Rowdies",
            away_team="Lexington", kickoff_utc=KICKOFF,
        )
        assert len(events) == 2
        assert events[0] == {"minute": 12, "team": "Lexington", "type": "Goal",
                             "detail": "Normal Goal", "player": "X. Zengue"}
        assert events[1]["minute"] == 93

    def test_empty_when_no_fixture(self) -> None:
        assert _provider().fetch_events(
            league_slug="xyz.1", home_team="A", away_team="B", kickoff_utc=KICKOFF
        ) == []
