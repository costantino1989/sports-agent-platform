"""HTTP client for ESPN soccer resources."""

from __future__ import annotations

import json
from typing import Any, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

JsonDict: TypeAlias = dict[str, Any]
JsonData: TypeAlias = JsonDict | list[Any]

DEFAULT_TIMEOUT_SECONDS = 15
SCOREBOARD_URL_TEMPLATE = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/scoreboard"
)


class EspnApiError(RuntimeError):
    """Raised when an ESPN endpoint cannot be consumed."""


class EspnSoccerClient:
    """Fetch raw soccer resources from ESPN APIs.

    Attributes:
        _timeout_seconds: Request timeout used for every API call.
    """

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        """Initialize the ESPN client.

        Args:
            timeout_seconds: HTTP timeout in seconds.
        """

        self._timeout_seconds = timeout_seconds

    def fetch_json(self, url: str) -> JsonData:
        """Fetch and parse a JSON payload from a URL.

        Args:
            url: Fully-qualified ESPN endpoint URL.

        Returns:
            Parsed JSON payload.

        Raises:
            EspnApiError: If the HTTP request fails or JSON is invalid.
        """

        request = Request(url=url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                charset = response.headers.get_content_charset("utf-8")
                payload = response.read().decode(charset)
        except HTTPError as exc:
            raise EspnApiError(
                f"HTTP error while reading ESPN resource '{url}': {exc.code}"
            ) from exc
        except TimeoutError as exc:
            raise EspnApiError(
                f"Timeout while reading ESPN resource '{url}'."
            ) from exc
        except URLError as exc:
            raise EspnApiError(
                f"Network error while reading ESPN resource '{url}': {exc.reason}"
            ) from exc

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise EspnApiError(
                f"Invalid JSON returned by ESPN resource '{url}'."
            ) from exc

    def fetch_scoreboard(self, league_slug: str) -> JsonDict:
        """Fetch the scoreboard payload for a league slug.

        Args:
            league_slug: ESPN league slug, for example ``ita.1``.

        Returns:
            Parsed JSON payload from the scoreboard endpoint.

        Raises:
            EspnApiError: If the HTTP request fails or JSON is invalid.
        """

        url = SCOREBOARD_URL_TEMPLATE.format(league_slug=league_slug)
        payload = self.fetch_json(url=url)
        if not isinstance(payload, dict):
            raise EspnApiError(
                f"Unexpected payload type for scoreboard '{league_slug}'."
            )
        return payload
