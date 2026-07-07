"""Build odds providers from runtime settings."""

from __future__ import annotations

from src.odds.apifootball import ApiFootballProvider
from src.odds.composite import CompositeOddsProvider
from src.odds.provider import OddsProvider
from src.odds.theoddsapi import TheOddsApiProvider

# API-Football's day-odds call is paginated and its free plan is small (100/day),
# so its data is cached far longer than The Odds API's (pre-match odds are stable).
_API_FOOTBALL_CACHE_MINUTES = 12 * 60


def build_api_football_provider(
    api_football_key: str,
    preferred_bookmakers: tuple[str, ...] = ("Bet365", "Betfair"),
) -> ApiFootballProvider | None:
    """Build the API-Football provider (odds + events), or None when no key.

    A single instance is shared for both odds and the events dossier fallback so
    the paginated day-odds call is cached once, conserving the free-plan quota.
    """

    if not api_football_key:
        return None
    return ApiFootballProvider(
        api_key=api_football_key,
        cache_minutes=_API_FOOTBALL_CACHE_MINUTES,
        preferred_bookmakers=preferred_bookmakers,
    )


def build_odds_provider(
    odds_api_key: str,
    region: str,
    bookmaker: str,
    cache_minutes: int,
    api_football_provider: ApiFootballProvider | None = None,
) -> OddsProvider | None:
    """Compose the configured odds sources, in priority order.

    Betfair (The Odds API) is tried first, then API-Football for the leagues The
    Odds API does not cover. Returns None when no source is configured, so
    callers fall back to the ESPN snapshot.

    Args:
        odds_api_key: The Odds API key (empty disables Betfair source).
        region: The Odds API region (e.g. ``eu``).
        bookmaker: The Odds API bookmaker key (e.g. ``betfair_ex_eu``).
        cache_minutes: Minutes The Odds API reuses a league's odds.
        api_football_provider: Pre-built API-Football provider (shared with the
            events fallback), appended after The Odds API when present.

    Returns:
        A composite provider, or None when no source is configured.
    """

    providers: list[OddsProvider] = []
    if odds_api_key:
        providers.append(
            TheOddsApiProvider(
                api_key=odds_api_key,
                region=region,
                bookmaker=bookmaker,
                cache_minutes=cache_minutes,
            )
        )
    if api_football_provider is not None:
        providers.append(api_football_provider)
    if not providers:
        return None
    return CompositeOddsProvider(providers)
