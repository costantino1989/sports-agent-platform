"""Tests for the composite odds provider (tries sources in order)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.odds.composite import CompositeOddsProvider
from src.odds.models import MatchOdds

KICKOFF = datetime(2026, 7, 5, 1, 0, tzinfo=timezone.utc)
_ODDS_A = MatchOdds(home=1.5, draw=4.0, away=6.0, bookmaker="Betfair Exchange", last_update="a")
_ODDS_B = MatchOdds(home=1.6, draw=3.9, away=5.0, bookmaker="Bet365", last_update="b")


class _Stub:
    def __init__(self, result): self._result = result; self.calls = 0
    def get_1x2_odds(self, **kwargs):
        self.calls += 1
        return self._result


def _q(provider):
    return provider.get_1x2_odds(
        league_slug="x", home_team="A", away_team="B", kickoff_utc=KICKOFF
    )


class TestCompositeOddsProvider:
    def test_returns_first_providers_odds(self) -> None:
        first, second = _Stub(_ODDS_A), _Stub(_ODDS_B)
        assert _q(CompositeOddsProvider([first, second])) is _ODDS_A
        assert second.calls == 0  # short-circuits on first hit

    def test_falls_through_to_next_when_first_is_none(self) -> None:
        first, second = _Stub(None), _Stub(_ODDS_B)
        assert _q(CompositeOddsProvider([first, second])) is _ODDS_B
        assert first.calls == 1 and second.calls == 1

    def test_none_when_all_providers_miss(self) -> None:
        assert _q(CompositeOddsProvider([_Stub(None), _Stub(None)])) is None

    def test_empty_provider_list_returns_none(self) -> None:
        assert _q(CompositeOddsProvider([])) is None
