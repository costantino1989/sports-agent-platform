"""Odds provider protocol: fetch real 1X2 odds for a match."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from src.odds.models import MatchOdds


@runtime_checkable
class OddsProvider(Protocol):
    """A source of real 1X2 market odds for a single match.

    Implementations map a match (identified the way ESPN describes it) to a
    bookmaker's decimal odds. They return ``None`` — never raise — when the
    league is unsupported, the match cannot be found, or odds are unavailable,
    so the caller can fall back to another source.
    """

    def get_1x2_odds(
        self,
        *,
        league_slug: str,
        home_team: str,
        away_team: str,
        kickoff_utc: datetime | None,
    ) -> MatchOdds | None:
        """Return decimal 1X2 odds for the match, or None when unavailable."""
        ...
