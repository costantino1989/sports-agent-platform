"""Endpoint client for building match prediction dossiers."""

from __future__ import annotations

from typing import Any, TypeAlias

from src.espn import EspnSoccerClient, JsonData

JsonDict: TypeAlias = dict[str, Any]

SITE_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"
SITE_STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/soccer"
CORE_BASE_URL = "https://sports.core.api.espn.com/v2/sports/soccer/leagues"


class DossierDataClient:
    """Fetch all endpoint payloads required by the prediction markdown dossier.

    Attributes:
        _client: Shared ESPN HTTP client.
    """

    def __init__(self, client: EspnSoccerClient) -> None:
        """Initialize the dossier data client.

        Args:
            client: Shared HTTP client used for ESPN requests.
        """

        self._client = client

    def fetch_by_url(self, url: str) -> JsonData:
        """Fetch JSON payload from a fully-qualified URL.

        Args:
            url: Absolute ESPN endpoint URL.

        Returns:
            Endpoint JSON payload.
        """

        return self._client.fetch_json(url=url)

    def fetch_summary(self, league_slug: str, event_id: str) -> JsonData:
        """Fetch the match summary payload.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.

        Returns:
            Summary JSON payload.
        """

        url = f"{SITE_BASE_URL}/{league_slug}/summary?event={event_id}"
        return self._client.fetch_json(url=url)

    def fetch_news(self, league_slug: str) -> JsonData:
        """Fetch league news payload.

        Args:
            league_slug: ESPN league slug.

        Returns:
            News JSON payload.
        """

        url = f"{SITE_BASE_URL}/{league_slug}/news"
        return self._client.fetch_json(url=url)

    def fetch_team_roster(self, league_slug: str, team_id: str) -> JsonData:
        """Fetch team roster payload.

        Args:
            league_slug: ESPN league slug.
            team_id: ESPN team identifier.

        Returns:
            Team roster JSON payload.
        """

        url = f"{SITE_BASE_URL}/{league_slug}/teams/{team_id}/roster"
        return self._client.fetch_json(url=url)

    def fetch_team_injuries(self, league_slug: str, team_id: str) -> JsonData:
        """Fetch team injury report payload.

        Args:
            league_slug: ESPN league slug.
            team_id: ESPN team identifier.

        Returns:
            Team injuries JSON payload.
        """

        url = f"{SITE_BASE_URL}/{league_slug}/teams/{team_id}/injuries"
        return self._client.fetch_json(url=url)

    def fetch_team_schedule(self, league_slug: str, team_id: str) -> JsonData:
        """Fetch team schedule payload.

        Args:
            league_slug: ESPN league slug.
            team_id: ESPN team identifier.

        Returns:
            Team schedule JSON payload.
        """

        url = f"{SITE_BASE_URL}/{league_slug}/teams/{team_id}/schedule"
        return self._client.fetch_json(url=url)

    def fetch_standings(self, league_slug: str) -> JsonData:
        """Fetch league standings payload.

        Args:
            league_slug: ESPN league slug.

        Returns:
            Standings JSON payload.
        """

        url = f"{SITE_STANDINGS_URL}/{league_slug}/standings"
        return self._client.fetch_json(url=url)

    def fetch_core_event(self, league_slug: str, event_id: str) -> JsonData:
        """Fetch core event payload.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.

        Returns:
            Core event JSON payload.
        """

        url = f"{CORE_BASE_URL}/{league_slug}/events/{event_id}"
        return self._client.fetch_json(url=url)

    def fetch_core_competition(
        self, league_slug: str, event_id: str, competition_id: str
    ) -> JsonData:
        """Fetch core competition payload.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.
            competition_id: ESPN competition identifier.

        Returns:
            Core competition JSON payload.
        """

        url = (
            f"{CORE_BASE_URL}/{league_slug}/events/{event_id}/competitions/{competition_id}"
        )
        return self._client.fetch_json(url=url)

    def fetch_core_plays(
        self,
        league_slug: str,
        event_id: str,
        competition_id: str,
        page: int | None = None,
    ) -> JsonData:
        """Fetch play-by-play payload.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.
            competition_id: ESPN competition identifier.
            page: Optional page number for paginated play-by-play payloads.

        Returns:
            Play-by-play JSON payload.
        """

        base_url = (
            f"{CORE_BASE_URL}/{league_slug}/events/{event_id}/competitions/"
            f"{competition_id}/plays?limit=300"
        )
        url = f"{base_url}&page={page}" if page is not None else base_url
        return self._client.fetch_json(url=url)

    def fetch_core_situation(
        self, league_slug: str, event_id: str, competition_id: str
    ) -> JsonData:
        """Fetch live match situation payload.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.
            competition_id: ESPN competition identifier.

        Returns:
            Situation JSON payload.
        """

        url = (
            f"{CORE_BASE_URL}/{league_slug}/events/{event_id}/competitions/"
            f"{competition_id}/situation"
        )
        return self._client.fetch_json(url=url)

    def fetch_core_probabilities(
        self, league_slug: str, event_id: str, competition_id: str
    ) -> JsonData:
        """Fetch win probability payload.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.
            competition_id: ESPN competition identifier.

        Returns:
            Probabilities JSON payload.
        """

        url = (
            f"{CORE_BASE_URL}/{league_slug}/events/{event_id}/competitions/"
            f"{competition_id}/probabilities"
        )
        return self._client.fetch_json(url=url)

    def fetch_core_odds(
        self, league_slug: str, event_id: str, competition_id: str
    ) -> JsonData:
        """Fetch competition odds payload.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.
            competition_id: ESPN competition identifier.

        Returns:
            Odds JSON payload.
        """

        url = (
            f"{CORE_BASE_URL}/{league_slug}/events/{event_id}/competitions/"
            f"{competition_id}/odds"
        )
        return self._client.fetch_json(url=url)

    def fetch_rankings(self, league_slug: str) -> JsonData:
        """Fetch league rankings payload.

        Args:
            league_slug: ESPN league slug.

        Returns:
            Rankings JSON payload.
        """

        url = f"{CORE_BASE_URL}/{league_slug}/rankings"
        return self._client.fetch_json(url=url)

    def fetch_current_season(self, league_slug: str) -> JsonData:
        """Fetch current season payload.

        Args:
            league_slug: ESPN league slug.

        Returns:
            Current season JSON payload.
        """

        url = f"{CORE_BASE_URL}/{league_slug}/season"
        return self._client.fetch_json(url=url)

    def fetch_leaders(self, league_slug: str, season_year: int) -> JsonData:
        """Fetch season leaders payload.

        Args:
            league_slug: ESPN league slug.
            season_year: Target season year.

        Returns:
            Season leaders JSON payload.
        """

        url = f"{CORE_BASE_URL}/{league_slug}/seasons/{season_year}/leaders"
        return self._client.fetch_json(url=url)

    def fetch_athlete(self, league_slug: str, athlete_id: str) -> JsonData:
        """Fetch athlete detail payload.

        Args:
            league_slug: ESPN league slug.
            athlete_id: ESPN athlete identifier.

        Returns:
            Athlete detail JSON payload.
        """

        url = f"{CORE_BASE_URL}/{league_slug}/athletes/{athlete_id}"
        return self._client.fetch_json(url=url)
