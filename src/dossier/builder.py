"""Async orchestrator that builds match dossier data with bounded concurrency."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from pathlib import Path
from threading import BoundedSemaphore
from time import perf_counter

from src.dossier.builder_fetch import DossierFetchFacade
from src.dossier.client import DossierDataClient
from src.dossier.extractor import DossierDataExtractor
from src.dossier.fetch_cache import LeaguePayloadTaskCache
from src.models.dossier import EndpointPayload, JsonData, MatchDossierData, TeamDossierData
from src.models.live_models import MatchRecordModel
from src.utils.color_logger import get_logger
from src.utils.config import get_runtime_config
from src.utils.timing import log_execution_time

RUNTIME_CONFIG = get_runtime_config()
MATCH_CONCURRENCY_DEFAULT = RUNTIME_CONFIG.match_concurrency_default
FETCH_CONCURRENCY_DEFAULT = RUNTIME_CONFIG.fetch_concurrency_default
LOGGER = get_logger()


class MatchDossierBuilder:
    """Build match dossier payloads using async gather and semaphores."""

    def __init__(
        self,
        data_client: DossierDataClient,
        extractor: DossierDataExtractor,
        match_concurrency: int = MATCH_CONCURRENCY_DEFAULT,
        fetch_concurrency: int = FETCH_CONCURRENCY_DEFAULT,
    ) -> None:
        """Initialize dependencies and concurrency limits."""

        self._data_client = data_client
        self._extractor = extractor
        self._fetch = DossierFetchFacade(data_client=data_client)
        self._match_concurrency = max(1, match_concurrency)
        self._fetch_concurrency = max(1, fetch_concurrency)
        self._league_cache = LeaguePayloadTaskCache()
        LOGGER.info(
            f"Dossier builder configured: match_concurrency={self._match_concurrency}, "
            f"fetch_concurrency={self._fetch_concurrency}"
        )

    async def build_many(
        self,
        matches: list[MatchRecordModel],
        output_dir: Path,
    ) -> list[MatchDossierData]:
        """Build dossier payloads for all matches."""

        self._league_cache = LeaguePayloadTaskCache()
        LOGGER.info(
            f"Scheduling {len(matches)} match builds (output_dir={output_dir}, "
            f"max_parallel_matches={self._match_concurrency}, "
            f"max_parallel_fetches={self._fetch_concurrency})."
        )
        match_semaphore = asyncio.Semaphore(self._match_concurrency)
        fetch_semaphore = BoundedSemaphore(self._fetch_concurrency)
        tasks = [
            self._build_with_match_limit(
                match=match,
                output_dir=output_dir,
                match_semaphore=match_semaphore,
                fetch_semaphore=fetch_semaphore,
                match_reference=self._build_match_reference(match=match),
            )
            for match in matches
        ]
        return await asyncio.gather(*tasks)

    @log_execution_time(
        label="Match markdown build",
        reference_arg="match_reference",
        log_level="info",
    )
    async def _build_with_match_limit(
        self,
        match: MatchRecordModel,
        output_dir: Path,
        match_semaphore: asyncio.Semaphore,
        fetch_semaphore: BoundedSemaphore,
        match_reference: str,
    ) -> MatchDossierData:
        """Build one dossier payload while respecting match concurrency."""

        async with match_semaphore:
            LOGGER.info(f"Starting match build pipeline [{match_reference}].")
            return await self._build_match_data(
                match=match,
                output_dir=output_dir,
                fetch_semaphore=fetch_semaphore,
            )

    async def _build_match_data(
        self,
        match: MatchRecordModel,
        output_dir: Path,
        fetch_semaphore: BoundedSemaphore,
    ) -> MatchDossierData:
        """Build all endpoint payloads for a single match."""

        league_slug = match.league.slug
        event_id = match.event.id or ""
        competition_id = match.competition.id or ""
        output_path = output_dir / self._build_file_name(match=match)
        match_reference = self._build_match_reference(match=match)
        base_phase_start = perf_counter()

        summary_task = asyncio.create_task(self._fetch.safe_fetch_async(fetcher=partial(self._data_client.fetch_summary, league_slug, event_id), fetch_semaphore=fetch_semaphore))
        core_event_task = asyncio.create_task(self._fetch.safe_fetch_async(fetcher=partial(self._data_client.fetch_core_event, league_slug, event_id), fetch_semaphore=fetch_semaphore))
        core_competition_task = asyncio.create_task(self._fetch.safe_fetch_async(fetcher=partial(self._data_client.fetch_core_competition, league_slug, event_id, competition_id), fetch_semaphore=fetch_semaphore))
        plays_task = asyncio.create_task(self._fetch.fetch_full_plays_async(league_slug=league_slug, event_id=event_id, competition_id=competition_id, fetch_semaphore=fetch_semaphore))
        situation_task = asyncio.create_task(self._fetch.safe_fetch_async(fetcher=partial(self._data_client.fetch_core_situation, league_slug, event_id, competition_id), fetch_semaphore=fetch_semaphore))
        standings_task = await self._cached_league_fetch_task(
            key=f"standings:{league_slug}",
            fetcher=partial(self._data_client.fetch_standings, league_slug),
            fetch_semaphore=fetch_semaphore,
        )
        rankings_task = await self._cached_league_fetch_task(
            key=f"rankings:{league_slug}",
            fetcher=partial(self._data_client.fetch_rankings, league_slug),
            fetch_semaphore=fetch_semaphore,
        )
        news_task = await self._cached_league_fetch_task(
            key=f"news:{league_slug}",
            fetcher=partial(self._data_client.fetch_news, league_slug),
            fetch_semaphore=fetch_semaphore,
        )
        season_year_task = asyncio.create_task(asyncio.to_thread(self._fetch.detect_season_year, match, league_slug, fetch_semaphore))
        (summary, core_event, core_competition, plays, situation, standings, rankings, news, season_year) = await asyncio.gather(
            summary_task, core_event_task, core_competition_task, plays_task, situation_task, standings_task, rankings_task, news_task, season_year_task
        )
        LOGGER.info(f"Base fetch completed [{match_reference}] summary={self._payload_state(summary)}, core_event={self._payload_state(core_event)}, core_competition={self._payload_state(core_competition)}, plays={self._payload_state(plays)}, situation={self._payload_state(situation)}, standings={self._payload_state(standings)}, rankings={self._payload_state(rankings)}, news={self._payload_state(news)} in {self._elapsed_seconds(base_phase_start):.3f}s.")

        aggregation_phase_start = perf_counter()
        enriched_competition_task = asyncio.create_task(asyncio.to_thread(self._fetch.enrich_core_competition_context, core_competition, fetch_semaphore))
        probabilities_task = asyncio.create_task(self._fetch.safe_fetch_async(fetcher=partial(self._data_client.fetch_core_probabilities, league_slug, event_id, competition_id), fetch_semaphore=fetch_semaphore))
        odds_task = asyncio.create_task(asyncio.to_thread(self._fetch.fetch_odds_with_fallback, league_slug, event_id, competition_id, summary, fetch_semaphore))
        leaders_task = await self._cached_league_fetch_task(
            key=f"leaders:{league_slug}:{season_year}",
            fetcher=partial(self._data_client.fetch_leaders, league_slug, season_year),
            fetch_semaphore=fetch_semaphore,
        )
        teams_task = asyncio.create_task(self._build_teams_data_async(match=match, league_slug=league_slug, summary_payload=summary.data, fetch_semaphore=fetch_semaphore))
        (core_competition, probabilities, odds, leaders, teams) = await asyncio.gather(
            enriched_competition_task, probabilities_task, odds_task, leaders_task, teams_task
        )
        head_to_head = await asyncio.to_thread(self._extractor.build_head_to_head, teams)
        LOGGER.info(f"Match aggregation completed [{match_reference}] probabilities={self._payload_state(probabilities)}, odds={self._payload_state(odds)}, leaders={self._payload_state(leaders)}, teams={len(teams)}, head_to_head={len(head_to_head)} in {self._elapsed_seconds(aggregation_phase_start):.3f}s.")

        return MatchDossierData(
            match=match,
            output_path=output_path,
            summary=summary,
            core_event=core_event,
            core_competition=core_competition,
            plays=plays,
            situation=situation,
            probabilities=probabilities,
            odds=odds,
            standings=standings,
            leaders=leaders,
            rankings=rankings,
            news=news,
            teams=teams,
            head_to_head=head_to_head,
        )

    async def _build_teams_data_async(
        self,
        match: MatchRecordModel,
        league_slug: str,
        summary_payload: JsonData | None,
        fetch_semaphore: BoundedSemaphore,
    ) -> list[TeamDossierData]:
        """Build team data in a worker thread with shared fetch limiter."""

        return await asyncio.to_thread(
            self._extractor.build_teams_data,
            match,
            league_slug,
            summary_payload,
            partial(self._fetch.safe_fetch, fetch_semaphore=fetch_semaphore),
        )

    async def _cached_league_fetch_task(
        self,
        key: str,
        fetcher: Callable[[], JsonData],
        fetch_semaphore: BoundedSemaphore,
    ) -> asyncio.Task[EndpointPayload]:
        """Return a cached league-scoped fetch task."""

        return await self._league_cache.get_or_create(
            key=key,
            factory=partial(
                self._fetch.safe_fetch_async,
                fetcher=fetcher,
                fetch_semaphore=fetch_semaphore,
            ),
        )

    def _build_file_name(self, match: MatchRecordModel) -> str:
        """Build stable markdown filename from league/event identifiers."""

        league = match.league.slug.replace(".", "_")
        event_id = (match.event.id or "unknown").replace("/", "_")
        return f"{league}_{event_id}.md"

    def _build_match_reference(self, match: MatchRecordModel) -> str:
        """Build concise timing-log reference from league slug and event ID."""

        event_id = match.event.id or "unknown"
        return f"{match.league.slug}:{event_id}"

    def _payload_state(self, payload: EndpointPayload) -> str:
        """Describe payload availability in compact log-friendly format."""

        return "ok" if payload.has_data() else "empty"

    def _elapsed_seconds(self, start: float) -> float:
        """Compute elapsed wall-clock seconds from a perf-counter start."""

        return perf_counter() - start
