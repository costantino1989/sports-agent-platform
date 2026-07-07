"""Tests for composing odds providers from runtime settings."""

from __future__ import annotations

from src.odds.apifootball import ApiFootballProvider
from src.odds.composite import CompositeOddsProvider
from src.odds.factory import build_api_football_provider, build_odds_provider
from src.odds.theoddsapi import TheOddsApiProvider


class TestBuildApiFootballProvider:
    def test_none_without_key(self) -> None:
        assert build_api_football_provider("") is None

    def test_builds_with_key(self) -> None:
        assert isinstance(build_api_football_provider("F"), ApiFootballProvider)


class TestBuildOddsProvider:
    def test_none_when_no_sources(self) -> None:
        assert build_odds_provider("", "eu", "betfair_ex_eu", 3) is None

    def test_theoddsapi_only(self) -> None:
        provider = build_odds_provider("K", "eu", "betfair_ex_eu", 3)
        assert isinstance(provider, CompositeOddsProvider)
        assert [type(p) for p in provider._providers] == [TheOddsApiProvider]

    def test_apifootball_only(self) -> None:
        apifb = build_api_football_provider("F")
        provider = build_odds_provider("", "eu", "betfair_ex_eu", 3, api_football_provider=apifb)
        assert [type(p) for p in provider._providers] == [ApiFootballProvider]

    def test_both_betfair_first(self) -> None:
        apifb = build_api_football_provider("F")
        provider = build_odds_provider("K", "eu", "betfair_ex_eu", 3, api_football_provider=apifb)
        assert [type(p) for p in provider._providers] == [
            TheOddsApiProvider,
            ApiFootballProvider,
        ]
