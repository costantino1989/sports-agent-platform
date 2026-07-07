"""Real-odds retrieval from external providers (The Odds API -> Betfair)."""

from src.odds.models import MatchOdds
from src.odds.provider import OddsProvider

__all__ = ["MatchOdds", "OddsProvider"]
