"""API-Football provider (api-sports.io): odds and play-by-play events.

Complements ESPN + The Odds API for leagues they don't cover (Ecuador, USL,
Uruguay, ...). On the free plan the ``league``/``season`` filters return empty,
but ``/fixtures?date=`` (all fixtures of a day, one page — no pagination) and the
per-``fixture`` odds/events endpoints work. So the day's fixtures are fetched
once and cached, filtered to the wanted league, matched by kickoff (names break
ties), then odds/events are fetched by fixture id. Odds are oriented to the ESPN
home/away sides by name, so 1 and 2 can never be swapped.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from src.odds.models import MatchOdds
from src.odds.name_match import match_score, teams_match
from src.utils import get_logger

LOGGER = get_logger()

_API_BASE = "https://v3.football.api-sports.io"
_KICKOFF_TOLERANCE_SECONDS = 15 * 60
_MATCH_WINNER_BETS = frozenset({"Match Winner", "1X2"})
_LIVE_RESULT_BET = "Fulltime Result"  # the in-play 1X2 market on /odds/live
_LIVE_CACHE_MINUTES = 3  # live odds move fast; the whole feed is one call
_LIVE_BOOKMAKER = "API-Football Live"  # aggregated in-play price (no single book)

# ESPN league slug -> API-Football numeric league id. Extend as needed; leagues
# absent here simply fall through (the caller tries the next source).
DEFAULT_API_FOOTBALL_LEAGUES: dict[str, int] = {
    "usa.usl.1": 255,     # USL Championship
    "usa.usl.l1": 489,    # USL League One
    "swe.1": 113,         # Allsvenskan (Sweden)
    "ecu.1": 242,         # Liga Pro (Ecuador)
    "uru.1": 268,         # Primera División (Uruguay)
}

ApiFootballGet = Callable[[str, dict], list[dict]]
Clock = Callable[[], datetime]


class ApiFootballProvider:
    """Fetch 1X2 odds and events for a match from API-Football."""

    def __init__(
        self,
        api_key: str,
        cache_minutes: int,
        preferred_bookmakers: tuple[str, ...] = ("Bet365", "Betfair"),
        http_get: ApiFootballGet | None = None,
        clock: Clock | None = None,
        league_map: dict[str, int] | None = None,
    ) -> None:
        """Initialize the provider.

        Args:
            api_key: API-Football (api-sports.io) key.
            cache_minutes: Minutes to reuse a day's fixtures / a fixture's data.
            preferred_bookmakers: Bookmaker names to use, in priority order.
            http_get: Injectable ``(endpoint, params) -> response`` fetcher.
            clock: Injectable UTC clock for cache expiry (testable).
            league_map: ESPN slug -> API-Football league id (defaults to built-in).
        """

        self._api_key = api_key
        self._cache_minutes = cache_minutes
        self._preferred = preferred_bookmakers
        self._http_get = http_get or self._default_http_get
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._league_map = (
            league_map if league_map is not None else DEFAULT_API_FOOTBALL_LEAGUES
        )
        self._fixtures_cache: dict[str, tuple[datetime, list[dict]]] = {}
        self._odds_cache: dict[int, tuple[datetime, list[dict]]] = {}
        self._events_cache: dict[int, tuple[datetime, list[dict]]] = {}
        self._live_cache: tuple[datetime, list[dict]] | None = None

    def get_1x2_odds(
        self,
        *,
        league_slug: str,
        home_team: str,
        away_team: str,
        kickoff_utc: datetime | None,
    ) -> MatchOdds | None:
        """Return decimal 1X2 odds for the match, or None when unavailable."""

        fixture = self._locate(league_slug, home_team, away_team, kickoff_utc)
        if fixture is None:
            return None
        # Prefer genuinely-live in-play odds; fall back to the pre-match book
        # snapshot only when the match is not currently in the live feed.
        live = self._live_odds(fixture, home_team)
        if live is not None:
            return live
        bookmakers = self._cached_fixture_odds(fixture["id"])
        if not bookmakers:
            return None
        return self._extract_odds(bookmakers, fixture, home_team)

    def _live_odds(self, fixture: dict, home_team: str) -> MatchOdds | None:
        """Return in-play 1X2 from /odds/live for this fixture, or None."""

        entry = next(
            (
                e
                for e in self._cached_live_feed()
                if (e.get("fixture") or {}).get("id") == fixture["id"]
            ),
            None,
        )
        if entry is None:
            return None
        prices = self._fulltime_result_prices(entry.get("odds", []))
        if prices is None:
            return None
        return self._orient(
            *prices, fixture, home_team, _LIVE_BOOKMAKER, "API-Football live"
        )

    def _cached_live_feed(self) -> list[dict]:
        """Return all currently-live matches' odds (one call), briefly cached."""

        now = self._clock()
        if self._live_cache is not None and (
            now - self._live_cache[0] < timedelta(minutes=_LIVE_CACHE_MINUTES)
        ):
            return self._live_cache[1]
        feed = self._safe_get("odds/live", {})
        self._live_cache = (now, feed)
        return feed

    @staticmethod
    def _fulltime_result_prices(markets: list[dict]) -> tuple[float, float, float] | None:
        """Extract (home, draw, away) from the live 'Fulltime Result' market."""

        market = next(
            (m for m in markets if str(m.get("name", "")) == _LIVE_RESULT_BET), None
        )
        if market is None:
            return None
        values = {str(v.get("value")): v.get("odd") for v in market.get("values", [])}
        try:
            return float(values["Home"]), float(values["Draw"]), float(values["Away"])
        except (KeyError, TypeError, ValueError):
            return None

    def fetch_events(
        self,
        *,
        league_slug: str,
        home_team: str,
        away_team: str,
        kickoff_utc: datetime | None,
    ) -> list[dict]:
        """Return the match's play-by-play events, or [] when unavailable.

        Used as a dossier fallback for leagues ESPN does not cover with
        play-by-play. Each event is ``{minute, team, type, detail, player}``.
        """

        fixture = self._locate(league_slug, home_team, away_team, kickoff_utc)
        if fixture is None:
            return []
        return self._cached_events(fixture["id"])

    def _locate(
        self, league_slug: str, home_team: str, away_team: str, kickoff_utc: datetime | None
    ) -> dict | None:
        """Find the API-Football fixture for a match: kickoff-first, names to tie."""

        league_id = self._league_map.get(league_slug)
        if league_id is None or kickoff_utc is None:
            return None
        date = kickoff_utc.astimezone(timezone.utc).date().isoformat()
        fixtures = [
            f for f in self._cached_day_fixtures(date) if f["league_id"] == league_id
        ]
        near = [
            f
            for f in fixtures
            if self._kickoff_distance(f, kickoff_utc) <= _KICKOFF_TOLERANCE_SECONDS
        ]
        named = [f for f in near if self._has_pair(f, home_team, away_team)]
        if named:
            return min(named, key=lambda f: self._kickoff_distance(f, kickoff_utc))
        # A lone same-time fixture links only when a team confirms it, so we never
        # bind to a coincidental neighbour kicking off at the same time.
        if len(near) == 1 and self._one_side_confirmed(near[0], home_team, away_team):
            return near[0]
        return None

    def _cached_day_fixtures(self, date: str) -> list[dict]:
        """Return every fixture of a day (one un-paginated call), cached by date."""

        cached = self._fixtures_cache.get(date)
        if cached is not None and self._fresh(cached[0]):
            return cached[1]
        fixtures = self._parse_fixtures(self._safe_get("fixtures", {"date": date}))
        self._fixtures_cache[date] = (self._clock(), fixtures)
        return fixtures

    def _cached_fixture_odds(self, fixture_id: int) -> list[dict]:
        """Return a fixture's bookmaker odds, cached by fixture id."""

        cached = self._odds_cache.get(fixture_id)
        if cached is not None and self._fresh(cached[0]):
            return cached[1]
        response = self._safe_get("odds", {"fixture": fixture_id})
        bookmakers = (response[0].get("bookmakers") or []) if response else []
        self._odds_cache[fixture_id] = (self._clock(), bookmakers)
        return bookmakers

    def _cached_events(self, fixture_id: int) -> list[dict]:
        """Return a fixture's parsed events, cached by fixture id."""

        cached = self._events_cache.get(fixture_id)
        if cached is not None and self._fresh(cached[0]):
            return cached[1]
        events = self._parse_events(
            self._safe_get("fixtures/events", {"fixture": fixture_id})
        )
        self._events_cache[fixture_id] = (self._clock(), events)
        return events

    def _fresh(self, stamped_at: datetime) -> bool:
        """Whether a cache timestamp is still within the reuse window."""

        return self._clock() - stamped_at < timedelta(minutes=self._cache_minutes)

    def _safe_get(self, endpoint: str, params: dict) -> list[dict]:
        """Call the injected fetcher, degrading to an empty list on failure."""

        try:
            return self._http_get(endpoint, params)
        except Exception as error:  # network/parse failure: degrade gracefully
            LOGGER.warn(f"API-Football {endpoint} fetch failed: {error}")
            return []

    @staticmethod
    def _parse_fixtures(response: list[dict]) -> list[dict]:
        """Flatten fixtures into ``{id, league_id, home, away, commence_time}``."""

        fixtures: list[dict] = []
        for item in response:
            fixture = item.get("fixture") or {}
            fixture_id = fixture.get("id")
            if fixture_id is None:
                continue
            teams = item.get("teams") or {}
            fixtures.append(
                {
                    "id": fixture_id,
                    "league_id": (item.get("league") or {}).get("id"),
                    "home": str((teams.get("home") or {}).get("name", "")),
                    "away": str((teams.get("away") or {}).get("name", "")),
                    "commence_time": str(fixture.get("date", "")),
                }
            )
        return fixtures

    @staticmethod
    def _parse_events(response: list[dict]) -> list[dict]:
        """Flatten API-Football events into ``{minute, team, type, detail, player}``."""

        events: list[dict] = []
        for item in response:
            time = item.get("time") or {}
            minute = time.get("elapsed")
            if minute is None:
                continue
            events.append(
                {
                    "minute": minute + (time.get("extra") or 0),
                    "team": str((item.get("team") or {}).get("name", "")),
                    "type": str(item.get("type", "")),
                    "detail": str(item.get("detail", "")),
                    "player": str((item.get("player") or {}).get("name", "")),
                }
            )
        events.sort(key=lambda event: event["minute"])
        return events

    @staticmethod
    def _has_pair(fixture: dict, home_team: str, away_team: str) -> bool:
        """Whether both requested teams appear in the fixture (any orientation)."""

        sides = [fixture["home"], fixture["away"]]
        return any(teams_match(home_team, s) for s in sides) and any(
            teams_match(away_team, s) for s in sides
        )

    @staticmethod
    def _one_side_confirmed(fixture: dict, home_team: str, away_team: str) -> bool:
        """Whether at least one team name matches strongly (exact/substring)."""

        best = 0
        for team in (home_team, away_team):
            for side in (fixture["home"], fixture["away"]):
                best = max(best, match_score(team, side))
        return best >= 2

    @staticmethod
    def _kickoff_distance(fixture: dict, kickoff_utc: datetime) -> float:
        """Absolute seconds between a fixture's kickoff and the target kickoff."""

        try:
            commence = datetime.fromisoformat(
                fixture["commence_time"].replace("Z", "+00:00")
            )
        except ValueError:
            return float("inf")
        return abs((commence - kickoff_utc).total_seconds())

    def _extract_odds(
        self, bookmakers: list[dict], fixture: dict, home_team: str
    ) -> MatchOdds | None:
        """Read the preferred bookmaker's 1X2, oriented to the ESPN home side."""

        book = self._pick_bookmaker(bookmakers)
        if book is None:
            return None
        prices = self._match_winner_prices(book)
        if prices is None:
            return None
        return self._orient(
            *prices, fixture, home_team, str(book.get("name", "")), "API-Football"
        )

    @staticmethod
    def _orient(
        api_home: float,
        draw: float,
        api_away: float,
        fixture: dict,
        home_team: str,
        bookmaker: str,
        last_update: str,
    ) -> MatchOdds:
        """Map the source's home/away prices to the ESPN home/away sides by name.

        The source labels "Home" as the fixture's home team; if ESPN's home team
        is actually the fixture's away side, the two prices are swapped, so 1 and
        2 can never get flipped.
        """

        home_is_fixture_home = match_score(home_team, fixture["home"]) >= match_score(
            home_team, fixture["away"]
        )
        home, away = (api_home, api_away) if home_is_fixture_home else (api_away, api_home)
        return MatchOdds(
            home=home, draw=draw, away=away, bookmaker=bookmaker, last_update=last_update
        )

    def _pick_bookmaker(self, bookmakers: list[dict]) -> dict | None:
        """Return the first bookmaker matching the preference order, or None."""

        by_name = {str(b.get("name", "")).lower(): b for b in bookmakers}
        for preferred in self._preferred:
            book = by_name.get(preferred.lower())
            if book is not None:
                return book
        return None

    @staticmethod
    def _match_winner_prices(book: dict) -> tuple[float, float, float] | None:
        """Extract (home, draw, away) decimal prices from a bookmaker's 1X2 bet."""

        bet = next(
            (b for b in book.get("bets", []) if b.get("name") in _MATCH_WINNER_BETS),
            None,
        )
        if bet is None:
            return None
        values = {str(v.get("value")): v.get("odd") for v in bet.get("values", [])}
        try:
            return (
                float(values["Home"]),
                float(values["Draw"]),
                float(values["Away"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _default_http_get(self, endpoint: str, params: dict) -> list[dict]:
        """Fetch one endpoint from API-Football and return its ``response`` list."""

        url = f"{_API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"x-apisports-key": self._api_key})
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        result = payload.get("response") if isinstance(payload, dict) else None
        return result if isinstance(result, list) else []
