"""Competition-context enrichment helpers for core competition payloads."""

from __future__ import annotations

from threading import BoundedSemaphore

from src.dossier.client import DossierDataClient
from src.espn import EspnApiError
from src.models.dossier import EndpointPayload, JsonData


class CompetitionContextResolver:
    """Resolve selected core-competition references into display-ready fields."""

    def __init__(self, data_client: DossierDataClient) -> None:
        """Initialize resolver dependencies.

        Args:
            data_client: Endpoint client for dossier data.
        """

        self._data_client = data_client

    def enrich(
        self,
        competition_payload: EndpointPayload,
        fetch_semaphore: BoundedSemaphore,
    ) -> EndpointPayload:
        """Enrich competition payload with officials and group context.

        Args:
            competition_payload: Core competition endpoint payload.
            fetch_semaphore: Thread-safe limiter for concurrent requests.

        Returns:
            Updated payload with optional ``officialsResolved`` and
            ``groupResolved`` fields.
        """

        data = competition_payload.data
        if not isinstance(data, dict):
            return competition_payload
        enriched = dict(data)
        officials = self._resolve_officials(
            competition_data=data,
            fetch_semaphore=fetch_semaphore,
        )
        if officials:
            enriched["officialsResolved"] = officials
        group_name = self._resolve_group_name(
            competition_data=data,
            fetch_semaphore=fetch_semaphore,
        )
        if group_name:
            enriched["groupResolved"] = group_name
        return EndpointPayload(data=enriched, error=competition_payload.error)

    def _resolve_officials(
        self,
        competition_data: dict[str, JsonData],
        fetch_semaphore: BoundedSemaphore,
    ) -> list[str]:
        """Resolve official names from competition officials reference.

        Args:
            competition_data: Raw core competition dictionary.
            fetch_semaphore: Thread-safe limiter for concurrent requests.

        Returns:
            Official display names.
        """

        officials_block = competition_data.get("officials")
        if not isinstance(officials_block, dict):
            return []
        reference_url = officials_block.get("$ref")
        if not isinstance(reference_url, str) or not reference_url:
            return []
        try:
            with fetch_semaphore:
                officials_payload = self._data_client.fetch_by_url(reference_url)
        except EspnApiError:
            return []
        items = officials_payload.get("items") if isinstance(officials_payload, dict) else None
        if not isinstance(items, list):
            return []
        names: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            candidate = item.get("displayName") or item.get("fullName") or item.get("name")
            if isinstance(candidate, str) and candidate.strip():
                names.append(candidate.strip())
        return names

    def _resolve_group_name(
        self,
        competition_data: dict[str, JsonData],
        fetch_semaphore: BoundedSemaphore,
    ) -> str | None:
        """Resolve competition group name from inline block or referenced endpoint.

        Args:
            competition_data: Raw core competition dictionary.
            fetch_semaphore: Thread-safe limiter for concurrent requests.

        Returns:
            Group name when available.
        """

        group_block = competition_data.get("groups")
        if not isinstance(group_block, dict):
            return None
        inline_name = group_block.get("name") or group_block.get("abbreviation")
        if isinstance(inline_name, str) and inline_name.strip():
            return inline_name.strip()
        reference_url = group_block.get("$ref")
        if not isinstance(reference_url, str) or not reference_url:
            return None
        try:
            with fetch_semaphore:
                group_payload = self._data_client.fetch_by_url(reference_url)
        except EspnApiError:
            return None
        if not isinstance(group_payload, dict):
            return None
        candidate = group_payload.get("name") or group_payload.get("abbreviation")
        if not isinstance(candidate, str) or not candidate.strip():
            return None
        return candidate.strip()
