"""The Odds API provider: real 1X2 odds from a chosen bookmaker (Betfair).

Odds are fetched per league (one HTTP call returns every match of that league
with all bookmakers) and cached briefly to conserve the monthly credit budget.
Outcomes are attached to the *ESPN* home/away teams by name, never by the
bookmaker's own home/away designation, so 1 and 2 can never get swapped.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from src.odds.league_map import DEFAULT_LEAGUE_MAP
from src.odds.models import MatchOdds
from src.odds.name_match import match_score, normalize, teams_match
from src.utils import get_logger

LOGGER = get_logger()

_API_BASE = "https://api.the-odds-api.com/v4"
# Two matches of the same league within this window are treated as simultaneous
# and disambiguated by name; a lone event this close to the kickoff is the match.
_KICKOFF_TOLERANCE_SECONDS = 15 * 60

HttpGet = Callable[[str, str, str], list[dict]]
Clock = Callable[[], datetime]


class TheOddsApiProvider:
    """Fetch real 1X2 odds for a match from a preferred bookmaker."""

    def __init__(
        self,
        api_key: str,
        region: str,
        bookmaker: str,
        cache_minutes: int,
        http_get: HttpGet | None = None,
        clock: Clock | None = None,
        league_map: dict[str, str] | None = None,
    ) -> None:
        """Initialize the provider.

        Args:
            api_key: The Odds API key.
            region: Region code (e.g. ``eu``).
            bookmaker: Preferred bookmaker key (e.g. ``betfair_ex_eu``).
            cache_minutes: Minutes to reuse a league's odds before refetching.
            http_get: Injectable fetch ``(sport_key, region, market) -> events``.
            clock: Injectable UTC clock for cache expiry (testable).
            league_map: ESPN slug -> sport key map (defaults to the built-in).
        """

        self._api_key = api_key
        self._region = region
        self._bookmaker = bookmaker
        self._cache_minutes = cache_minutes
        self._http_get = http_get or self._default_http_get
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._league_map = league_map if league_map is not None else DEFAULT_LEAGUE_MAP
        self._cache: dict[str, tuple[datetime, list[dict]]] = {}

    def get_1x2_odds(
        self,
        *,
        league_slug: str,
        home_team: str,
        away_team: str,
        kickoff_utc: datetime | None,
    ) -> MatchOdds | None:
        """Return decimal 1X2 odds for the match, or None when unavailable."""

        sport_key = self._league_map.get(league_slug)
        if sport_key is None:
            return None  # league not covered: caller falls back to ESPN
        events = self._fetch_cached(sport_key)
        event = self._match_event(events, home_team, away_team, kickoff_utc)
        if event is None:
            return None
        return self._extract_odds(event, home_team, away_team)

    def _fetch_cached(self, sport_key: str) -> list[dict]:
        """Return league events, using a short-lived cache to save credits."""

        now = self._clock()
        cached = self._cache.get(sport_key)
        if cached is not None:
            stamped_at, events = cached
            if now - stamped_at < timedelta(minutes=self._cache_minutes):
                return events
        try:
            events = self._http_get(sport_key, self._region, "h2h")
        except Exception as error:  # network/parse failure: degrade gracefully
            LOGGER.warn(f"Odds fetch failed [{sport_key}]: {error}")
            return cached[1] if cached is not None else []
        self._cache[sport_key] = (now, events)
        return events

    def _match_event(
        self,
        events: list[dict],
        home_team: str,
        away_team: str,
        kickoff_utc: datetime | None,
    ) -> dict | None:
        """Find the Odds API event for a match.

        League is already deterministic (the feed is per-league). Within it,
        kickoff time is the primary key: a single event at the same time is the
        match, and simultaneous matches are disambiguated by team name. Falls
        back to name matching across the league when the times disagree.
        """

        if kickoff_utc is not None:
            by_kickoff = self._match_by_kickoff(
                events, home_team, away_team, kickoff_utc
            )
            if by_kickoff is not None:
                return by_kickoff
        return self._match_by_name(events, home_team, away_team, kickoff_utc)

    def _match_by_kickoff(
        self,
        events: list[dict],
        home_team: str,
        away_team: str,
        kickoff_utc: datetime,
    ) -> dict | None:
        """Match using kickoff proximity, with names only to break ties."""

        near = [
            event
            for event in events
            if self._kickoff_distance(event, kickoff_utc) <= _KICKOFF_TOLERANCE_SECONDS
        ]
        if not near:
            return None
        named = [e for e in near if self._event_has_pair(e, home_team, away_team)]
        if named:
            return min(named, key=lambda e: self._kickoff_distance(e, kickoff_utc))
        # No name-pair among same-time events. Link a lone same-time event only
        # when at least one team confirms it, so we never bind to a coincidental
        # neighbour that kicks off at the same time.
        if len(near) == 1 and self._one_side_confirmed(near[0], home_team, away_team):
            return near[0]
        return None  # ambiguous or coincidental: defer to name matching / skip

    def _match_by_name(
        self,
        events: list[dict],
        home_team: str,
        away_team: str,
        kickoff_utc: datetime | None,
    ) -> dict | None:
        """Match by team-name pair across the league (kickoff time as tiebreak)."""

        candidates = [
            event
            for event in events
            if self._event_has_pair(event, home_team, away_team)
        ]
        if not candidates:
            return None
        if kickoff_utc is None or len(candidates) == 1:
            return candidates[0]
        return min(
            candidates,
            key=lambda event: self._kickoff_distance(event, kickoff_utc),
        )

    def _one_side_confirmed(
        self, event: dict, home_team: str, away_team: str
    ) -> bool:
        """Whether at least one team name matches strongly (exact/substring)."""

        sides = [str(event.get("home_team", "")), str(event.get("away_team", ""))]
        best = 0
        for team in (home_team, away_team):
            for side in sides:
                best = max(best, match_score(team, side))
        return best >= 2

    @staticmethod
    def _event_has_pair(event: dict, home_team: str, away_team: str) -> bool:
        """Whether both requested teams appear in the event (any orientation)."""

        sides = [str(event.get("home_team", "")), str(event.get("away_team", ""))]
        home_ok = any(teams_match(home_team, side) for side in sides)
        away_ok = any(teams_match(away_team, side) for side in sides)
        return home_ok and away_ok

    def _extract_odds(
        self, event: dict, home_team: str, away_team: str
    ) -> MatchOdds | None:
        """Read the preferred bookmaker's 1X2 prices, mapped to ESPN sides."""

        bookmaker = next(
            (
                book
                for book in event.get("bookmakers", [])
                if book.get("key") == self._bookmaker
            ),
            None,
        )
        if bookmaker is None:
            return None
        market = next(
            (m for m in bookmaker.get("markets", []) if m.get("key") == "h2h"),
            None,
        )
        if market is None:
            return None
        draw, team_prices = self._split_outcomes(market)
        if draw is None or len(team_prices) != 2:
            return None
        home, away = self._assign_sides(team_prices, home_team, away_team)
        if home is None or away is None:
            return None
        return MatchOdds(
            home=home,
            draw=draw,
            away=away,
            bookmaker=self._bookmaker,
            last_update=str(bookmaker.get("last_update", "")),
        )

    @staticmethod
    def _split_outcomes(
        market: dict,
    ) -> tuple[float | None, list[tuple[str, float]]]:
        """Separate the draw price from the two team (name, price) outcomes."""

        draw: float | None = None
        team_prices: list[tuple[str, float]] = []
        for outcome in market.get("outcomes", []):
            name = str(outcome.get("name", ""))
            price = outcome.get("price")
            if not isinstance(price, (int, float)):
                continue
            if normalize(name) == "draw":
                draw = float(price)
            else:
                team_prices.append((name, float(price)))
        return draw, team_prices

    @staticmethod
    def _assign_sides(
        team_prices: list[tuple[str, float]],
        home_team: str,
        away_team: str,
    ) -> tuple[float | None, float | None]:
        """Assign the two team outcomes to home/away by best overall fit.

        Chooses between the two possible orientations the one with the higher
        combined match score, so two clubs sharing a generic token (e.g. "IF")
        are never swapped or dropped.
        """

        (first_name, first_price), (second_name, second_price) = team_prices
        direct = match_score(home_team, first_name) + match_score(
            away_team, second_name
        )
        swapped = match_score(home_team, second_name) + match_score(
            away_team, first_name
        )
        if direct == 0 and swapped == 0:
            return None, None
        if direct >= swapped:
            return first_price, second_price
        return second_price, first_price

    @staticmethod
    def _kickoff_distance(event: dict, kickoff_utc: datetime) -> float:
        """Absolute seconds between an event's start and the target kickoff."""

        try:
            commence = datetime.fromisoformat(
                str(event.get("commence_time", "")).replace("Z", "+00:00")
            )
        except ValueError:
            return float("inf")
        return abs((commence - kickoff_utc).total_seconds())

    def _default_http_get(
        self, sport_key: str, region: str, market: str
    ) -> list[dict]:
        """Fetch odds for one league from The Odds API over HTTPS."""

        query = urllib.parse.urlencode(
            {
                "apiKey": self._api_key,
                "regions": region,
                "markets": market,
                "oddsFormat": "decimal",
            }
        )
        url = f"{_API_BASE}/sports/{sport_key}/odds/?{query}"
        with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310
            remaining = response.headers.get("x-requests-remaining")
            payload = json.loads(response.read().decode("utf-8"))
        if remaining is not None:
            LOGGER.info(f"Odds API credits remaining: {remaining} (after {sport_key}).")
        return payload if isinstance(payload, list) else []
