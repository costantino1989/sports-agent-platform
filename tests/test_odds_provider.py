"""Tests for real-odds retrieval via The Odds API (Betfair Exchange)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.odds.models import MatchOdds
from src.odds.theoddsapi import TheOddsApiProvider

# One event in the exact shape The Odds API returns (trimmed). Note the outcome
# names are the *team names*, and betfair marks Morocco (the away side per ESPN)
# as its "home_team" — a deliberate swap to prove we map by team name, not side.
_EVENT = {
    "id": "abc",
    "commence_time": "2026-07-04T17:00:00Z",
    "home_team": "Morocco",
    "away_team": "Canada",
    "bookmakers": [
        {
            "key": "pinnacle",
            "last_update": "2026-07-04T16:40:00Z",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Canada", "price": 5.5},
                        {"name": "Morocco", "price": 1.9},
                        {"name": "Draw", "price": 3.3},
                    ],
                }
            ],
        },
        {
            "key": "betfair_ex_eu",
            "last_update": "2026-07-04T16:47:29Z",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Canada", "price": 5.6},
                        {"name": "Morocco", "price": 1.89},
                        {"name": "Draw", "price": 3.35},
                    ],
                }
            ],
        },
    ],
}


class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def _provider(events, clock, calls):
    def http_get(sport_key, region, market):
        calls.append(sport_key)
        return events

    return TheOddsApiProvider(
        api_key="k",
        region="eu",
        bookmaker="betfair_ex_eu",
        cache_minutes=3,
        http_get=http_get,
        clock=clock,
        league_map={"fifa.world": "soccer_fifa_world_cup"},
    )


class TestMatchOdds:
    def test_for_result_maps_codes(self) -> None:
        odds = MatchOdds(home=2.0, draw=3.0, away=4.0, bookmaker="b", last_update="t")
        assert odds.for_result("1") == 2.0
        assert odds.for_result("X") == 3.0
        assert odds.for_result("2") == 4.0
        assert odds.for_result("?") is None


class TestTheOddsApiProvider:
    def _clock(self):
        return _FakeClock(datetime(2026, 7, 4, 17, 0, tzinfo=timezone.utc))

    def test_maps_outcomes_to_espn_home_away_not_bookmaker_side(self) -> None:
        # ESPN says Canada is home, Morocco away. Betfair labels Morocco as home.
        # We must attach Canada's price to "1" and Morocco's to "2" regardless.
        calls: list[str] = []
        prov = _provider(_EVENT and [_EVENT], self._clock(), calls)
        odds = prov.get_1x2_odds(
            league_slug="fifa.world",
            home_team="Canada",
            away_team="Morocco",
            kickoff_utc=datetime(2026, 7, 4, 17, 0, tzinfo=timezone.utc),
        )
        assert odds is not None
        assert odds.home == 5.6      # Canada (ESPN home) -> "1"
        assert odds.away == 1.89     # Morocco (ESPN away) -> "2"
        assert odds.draw == 3.35
        assert odds.bookmaker == "betfair_ex_eu"

    def test_unmapped_league_returns_none_without_fetching(self) -> None:
        calls: list[str] = []
        prov = _provider([_EVENT], self._clock(), calls)
        odds = prov.get_1x2_odds(
            league_slug="chn.1", home_team="A", away_team="B", kickoff_utc=None
        )
        assert odds is None
        assert calls == []           # no credit spent on unmapped leagues

    def test_no_matching_event_returns_none(self) -> None:
        calls: list[str] = []
        prov = _provider([_EVENT], self._clock(), calls)
        odds = prov.get_1x2_odds(
            league_slug="fifa.world",
            home_team="Brazil",
            away_team="Spain",
            kickoff_utc=None,
        )
        assert odds is None

    def test_missing_bookmaker_returns_none(self) -> None:
        event = {**_EVENT, "bookmakers": [_EVENT["bookmakers"][0]]}  # only pinnacle
        calls: list[str] = []
        prov = _provider([event], self._clock(), calls)
        odds = prov.get_1x2_odds(
            league_slug="fifa.world",
            home_team="Canada",
            away_team="Morocco",
            kickoff_utc=None,
        )
        assert odds is None

    def test_fuzzy_team_name_match(self) -> None:
        calls: list[str] = []
        prov = _provider([_EVENT], self._clock(), calls)
        # ESPN often adds suffixes / different casing.
        odds = prov.get_1x2_odds(
            league_slug="fifa.world",
            home_team="canada ",
            away_team="Morocco national team",
            kickoff_utc=None,
        )
        assert odds is not None and odds.home == 5.6

    def test_shared_token_does_not_swap_or_drop_sides(self) -> None:
        # Two clubs sharing a generic token ("IF") must not be confused: the
        # bijective assignment gives each side its best-matching outcome.
        event = {
            "commence_time": "2026-07-05T14:30:00Z",
            "home_team": "IF Elfsborg",
            "away_team": "Hammarby IF",
            "bookmakers": [
                {
                    "key": "betfair_ex_eu",
                    "last_update": "t",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Hammarby IF", "price": 1.92},
                                {"name": "IF Elfsborg", "price": 4.2},
                                {"name": "Draw", "price": 3.9},
                            ],
                        }
                    ],
                }
            ],
        }
        prov = _provider([event], self._clock(), [])
        odds = prov.get_1x2_odds(
            league_slug="fifa.world",
            home_team="IF Elfsborg",
            away_team="Hammarby IF",
            kickoff_utc=None,
        )
        assert odds is not None
        assert odds.home == 4.2      # IF Elfsborg
        assert odds.away == 1.92     # Hammarby IF
        assert odds.draw == 3.9

    def _bf_event(self, home, away, when, ho, dr, ao):
        return {
            "commence_time": when,
            "home_team": home,
            "away_team": away,
            "bookmakers": [{
                "key": "betfair_ex_eu", "last_update": "t",
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": home, "price": ho},
                    {"name": away, "price": ao},
                    {"name": "Draw", "price": dr},
                ]}],
            }],
        }

    def test_links_by_kickoff_when_names_disambiguate_simultaneous(self) -> None:
        # Two Allsvenskan matches at the SAME time: names pick the right one.
        kalmar = self._bf_event("Kalmar FF", "Örgryte IS", "2026-07-05T12:00:00Z", 1.02, 32.0, 11.5)
        goteborg = self._bf_event("IFK Goteborg", "AIK", "2026-07-05T12:00:00Z", 40.0, 6.0, 1.22)
        prov = _provider([kalmar, goteborg], self._clock(), [])
        odds = prov.get_1x2_odds(
            league_slug="fifa.world", home_team="IFK Göteborg", away_team="AIK",
            kickoff_utc=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        )
        assert odds is not None and odds.away == 1.22   # AIK, the Göteborg match

    def test_does_not_link_to_same_time_neighbour_with_unrelated_names(self) -> None:
        # Our match is NOT in the feed; a different match kicks off at the same
        # time. We must NOT link to it (no wrong odds).
        neighbour = self._bf_event("Malmo FF", "Djurgarden", "2026-07-05T12:00:00Z", 1.5, 4.0, 6.0)
        prov = _provider([neighbour], self._clock(), [])
        odds = prov.get_1x2_odds(
            league_slug="fifa.world", home_team="Kalmar FF", away_team="Örgryte IS",
            kickoff_utc=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        )
        assert odds is None

    def test_recovers_by_kickoff_when_one_name_differs(self) -> None:
        # Unique same-time event; the away name shares NO token with ESPN's (so
        # name-pair matching fails), but the home name confirms it -> link by time.
        event = self._bf_event("Kalmar FF", "Blaavitt", "2026-07-05T12:00:00Z", 1.02, 32.0, 11.5)
        prov = _provider([event], self._clock(), [])
        odds = prov.get_1x2_odds(
            league_slug="fifa.world", home_team="Kalmar FF", away_team="Örgryte IS",
            kickoff_utc=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        )
        assert odds is not None and odds.home == 1.02  # linked via time + home name

    def test_falls_back_to_name_when_kickoff_time_disagrees(self) -> None:
        # ESPN kickoff is off by hours vs the feed; name matching still links it.
        event = self._bf_event("Kalmar FF", "Örgryte IS", "2026-07-05T12:00:00Z", 1.02, 32.0, 11.5)
        prov = _provider([event], self._clock(), [])
        odds = prov.get_1x2_odds(
            league_slug="fifa.world", home_team="Kalmar FF", away_team="Örgryte IS",
            kickoff_utc=datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),  # 6h off
        )
        assert odds is not None and odds.home == 1.02

    def test_caches_within_window_to_save_credits(self) -> None:
        calls: list[str] = []
        clock = self._clock()
        prov = _provider([_EVENT], clock, calls)
        prov.get_1x2_odds(
            league_slug="fifa.world", home_team="Canada", away_team="Morocco",
            kickoff_utc=None,
        )
        prov.get_1x2_odds(
            league_slug="fifa.world", home_team="Canada", away_team="Morocco",
            kickoff_utc=None,
        )
        assert calls == ["soccer_fifa_world_cup"]      # second call served from cache

    def test_cache_expires_after_window(self) -> None:
        calls: list[str] = []
        clock = self._clock()
        prov = _provider([_EVENT], clock, calls)
        prov.get_1x2_odds(
            league_slug="fifa.world", home_team="Canada", away_team="Morocco",
            kickoff_utc=None,
        )
        clock.now = clock.now.replace(minute=5)        # 5 min later > 3 min window
        prov.get_1x2_odds(
            league_slug="fifa.world", home_team="Canada", away_team="Morocco",
            kickoff_utc=None,
        )
        assert calls == ["soccer_fifa_world_cup", "soccer_fifa_world_cup"]
