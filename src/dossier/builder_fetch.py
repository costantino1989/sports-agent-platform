"""Fetch utilities used by the async dossier builder."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from functools import partial
from threading import BoundedSemaphore

from src.dossier.client import DossierDataClient
from src.dossier.comp_context import CompetitionContextResolver
from src.espn import EspnApiError
from src.models.dossier import EndpointPayload, JsonData
from src.models.live_models import MatchRecordModel


class DossierFetchFacade:
    """Provide thread-safe endpoint fetch helpers for dossier building."""

    def __init__(self, data_client: DossierDataClient) -> None:
        """Initialize fetch facade dependencies.

        Args:
            data_client: Endpoint client for dossier data.
        """

        self._data_client = data_client
        self._context_resolver = CompetitionContextResolver(data_client=data_client)

    async def safe_fetch_async(
        self,
        fetcher: Callable[[], JsonData],
        fetch_semaphore: BoundedSemaphore,
    ) -> EndpointPayload:
        """Run a safe endpoint fetch in a worker thread.

        Args:
            fetcher: Zero-argument callable returning raw JSON data.
            fetch_semaphore: Thread-safe limiter for concurrent requests.

        Returns:
            Normalized endpoint payload with error handling.
        """

        return await asyncio.to_thread(self.safe_fetch, fetcher, fetch_semaphore)

    def safe_fetch(
        self,
        fetcher: Callable[[], JsonData],
        fetch_semaphore: BoundedSemaphore,
    ) -> EndpointPayload:
        """Run one safe endpoint fetch with bounded concurrency.

        Args:
            fetcher: Zero-argument callable returning raw JSON data.
            fetch_semaphore: Thread-safe limiter for concurrent requests.

        Returns:
            Normalized endpoint payload with error handling.
        """

        try:
            with fetch_semaphore:
                payload = fetcher()
        except EspnApiError as exc:
            return EndpointPayload(data=None, error=str(exc))
        return self.endpoint_payload(payload=payload)

    async def fetch_full_plays_async(
        self,
        league_slug: str,
        event_id: str,
        competition_id: str,
        fetch_semaphore: BoundedSemaphore,
    ) -> EndpointPayload:
        """Fetch and merge all play-by-play pages in a worker thread.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.
            competition_id: ESPN competition identifier.
            fetch_semaphore: Thread-safe limiter for concurrent requests.

        Returns:
            Endpoint payload containing merged play-by-play entries.
        """

        return await asyncio.to_thread(
            self.fetch_full_plays,
            league_slug,
            event_id,
            competition_id,
            fetch_semaphore,
        )

    def fetch_full_plays(
        self,
        league_slug: str,
        event_id: str,
        competition_id: str,
        fetch_semaphore: BoundedSemaphore,
    ) -> EndpointPayload:
        """Fetch and merge all available play-by-play pages.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.
            competition_id: ESPN competition identifier.
            fetch_semaphore: Thread-safe limiter for concurrent requests.

        Returns:
            Endpoint payload containing merged play-by-play entries.
        """

        try:
            with fetch_semaphore:
                first_page = self._data_client.fetch_core_plays(
                    league_slug=league_slug,
                    event_id=event_id,
                    competition_id=competition_id,
                    page=1,
                )
            if not isinstance(first_page, dict):
                return self.endpoint_payload(payload=first_page)
            page_count = first_page.get("pageCount")
            if not isinstance(page_count, int) or page_count <= 1:
                return self.endpoint_payload(payload=first_page)
            first_items = first_page.get("items")
            if not isinstance(first_items, list):
                return self.endpoint_payload(payload=first_page)
            merged_items = list(first_items)
            for page in range(2, page_count + 1):
                with fetch_semaphore:
                    next_page = self._data_client.fetch_core_plays(
                        league_slug=league_slug,
                        event_id=event_id,
                        competition_id=competition_id,
                        page=page,
                    )
                if not isinstance(next_page, dict):
                    continue
                next_items = next_page.get("items")
                if isinstance(next_items, list):
                    merged_items.extend(next_items)
            merged_payload = dict(first_page)
            merged_payload["items"] = merged_items
            merged_payload["count"] = len(merged_items)
            merged_payload["pageIndex"] = 1
            merged_payload["pageCount"] = 1
            return self.endpoint_payload(payload=merged_payload)
        except EspnApiError as exc:
            return EndpointPayload(data=None, error=str(exc))

    def fetch_odds_with_fallback(
        self,
        league_slug: str,
        event_id: str,
        competition_id: str,
        summary: EndpointPayload,
        fetch_semaphore: BoundedSemaphore,
    ) -> EndpointPayload:
        """Fetch odds from core endpoint and fallback to summary odds.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.
            competition_id: ESPN competition identifier.
            summary: Summary endpoint payload.
            fetch_semaphore: Thread-safe limiter for concurrent requests.

        Returns:
            Endpoint payload containing odds data.
        """

        core_odds = self.safe_fetch(
            fetcher=partial(
                self._data_client.fetch_core_odds,
                league_slug,
                event_id,
                competition_id,
            ),
            fetch_semaphore=fetch_semaphore,
        )
        if core_odds.has_data():
            return core_odds
        if isinstance(summary.data, dict) and "odds" in summary.data:
            return EndpointPayload(data={"source": "site-summary", "odds": summary.data["odds"]})
        return core_odds

    def detect_season_year(
        self,
        match: MatchRecordModel,
        league_slug: str,
        fetch_semaphore: BoundedSemaphore,
    ) -> int:
        """Detect target season year for leaders endpoint.

        Args:
            match: Match record that may include season info.
            league_slug: ESPN league slug.
            fetch_semaphore: Thread-safe limiter for concurrent requests.

        Returns:
            Season year, defaulting to current UTC year.
        """

        season = match.event.season or {}
        if isinstance(season, dict):
            year_value = season.get("year")
            if isinstance(year_value, int):
                return year_value
        season_payload = self.safe_fetch(
            fetcher=partial(self._data_client.fetch_current_season, league_slug),
            fetch_semaphore=fetch_semaphore,
        )
        if isinstance(season_payload.data, dict):
            year_value = season_payload.data.get("year")
            if isinstance(year_value, int):
                return year_value
        return datetime.now(timezone.utc).year

    def endpoint_payload(self, payload: JsonData) -> EndpointPayload:
        """Convert raw payload to EndpointPayload with empty-data handling.

        Args:
            payload: Raw JSON payload.

        Returns:
            Normalized endpoint payload.
        """

        if isinstance(payload, dict) and not payload:
            return EndpointPayload(data=None)
        if isinstance(payload, list) and not payload:
            return EndpointPayload(data=None)
        return EndpointPayload(data=payload)

    def enrich_core_competition_context(
        self,
        competition_payload: EndpointPayload,
        fetch_semaphore: BoundedSemaphore,
    ) -> EndpointPayload:
        """Enrich core competition payload with resolved context fields."""

        return self._context_resolver.enrich(
            competition_payload=competition_payload,
            fetch_semaphore=fetch_semaphore,
        )
