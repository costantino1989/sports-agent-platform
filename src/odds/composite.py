"""Compose several odds providers, trying each in priority order.

Lets the dossier layer stay unaware of how many odds sources exist: it holds a
single :class:`OddsProvider`, while this composite queries Betfair (The Odds
API) first, then API-Football, then any further source, returning the first that
prices the match.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.odds.models import MatchOdds
    from src.odds.provider import OddsProvider


class CompositeOddsProvider:
    """Try each wrapped provider in order and return the first odds found."""

    def __init__(self, providers: list["OddsProvider"]) -> None:
        """Initialize with providers in priority order (first is preferred)."""

        self._providers = providers

    def get_1x2_odds(
        self,
        *,
        league_slug: str,
        home_team: str,
        away_team: str,
        kickoff_utc: datetime | None,
    ) -> "MatchOdds | None":
        """Return the first provider's odds for the match, or None if none price it."""

        for provider in self._providers:
            odds = provider.get_1x2_odds(
                league_slug=league_slug,
                home_team=home_team,
                away_team=away_team,
                kickoff_utc=kickoff_utc,
            )
            if odds is not None:
                return odds
        return None
