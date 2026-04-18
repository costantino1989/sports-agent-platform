"""Action that builds prediction markdown files for live matches."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias

from src.dossier.client import DossierDataClient
from src.dossier.extractor import DossierDataExtractor
from src.dossier.render import MatchMarkdownRenderer
from src.espn import EspnApiError
from src.models.dossier import EndpointPayload, JsonData, MatchDossierData
from src.models.live_models import MatchRecordModel
from src.utils import get_logger

JsonDict: TypeAlias = dict[str, Any]
LOGGER = get_logger()


class MatchDossierAction:
    """Build one markdown dossier per live match from ESPN data sources.

    Attributes:
        _data_client: Endpoint client used for match-level datasets.
        _extractor: Team/player/head-to-head extractor.
        _renderer: Markdown renderer for final output.
    """

    def __init__(
        self,
        data_client: DossierDataClient,
        extractor: DossierDataExtractor,
        renderer: MatchMarkdownRenderer,
    ) -> None:
        """Initialize action dependencies.

        Args:
            data_client: Endpoint client for dossier data.
            extractor: Team and player extractor.
            renderer: Markdown renderer for one match dossier.
        """

        self._data_client = data_client
        self._extractor = extractor
        self._renderer = renderer

    def run(self, matches: list[MatchRecordModel], output_dir: Path) -> list[Path]:
        """Generate markdown dossiers for selected in-progress matches.

        Args:
            matches: In-progress match records selected for dossier generation.
            output_dir: Target directory for markdown files.

        Returns:
            List of generated markdown file paths.

        Raises:
            OSError: If writing markdown files fails.
        """

        output_dir.mkdir(parents=True, exist_ok=True)
        output_files: list[Path] = []
        LOGGER.info(
            f"Generating markdown dossiers for {len(matches)} in-progress matches."
        )
        if not matches:
            LOGGER.warn("No eligible matches were provided, markdown dossier output will be empty.")
        for match in matches:
            dossier_data = self._build_match_dossier_data(match=match, output_dir=output_dir)
            markdown = self._renderer.render(dossier_data)
            dossier_data.output_path.write_text(markdown, encoding="utf-8")
            output_files.append(dossier_data.output_path)
        LOGGER.info(f"Generated {len(output_files)} markdown dossier files.")
        return output_files

    def _build_match_dossier_data(
        self, match: MatchRecordModel, output_dir: Path
    ) -> MatchDossierData:
        """Build all section payloads for one match dossier.

        Args:
            match: Single live match record.
            output_dir: Target directory for markdown files.

        Returns:
            Aggregated dossier data for rendering.
        """

        league_slug = match.league.slug
        event_id = match.event.id or ""
        competition_id = match.competition.id or ""
        season_year = self._detect_season_year(match=match, league_slug=league_slug)

        summary = self._safe_fetch(
            lambda: self._data_client.fetch_summary(league_slug, event_id)
        )
        core_event = self._safe_fetch(
            lambda: self._data_client.fetch_core_event(league_slug, event_id)
        )
        core_competition = self._safe_fetch(
            lambda: self._data_client.fetch_core_competition(
                league_slug,
                event_id,
                competition_id,
            )
        )
        plays = self._safe_fetch(
            lambda: self._fetch_full_plays(
                league_slug=league_slug,
                event_id=event_id,
                competition_id=competition_id,
            )
        )
        situation = self._safe_fetch(
            lambda: self._data_client.fetch_core_situation(league_slug, event_id, competition_id)
        )
        probabilities = self._safe_fetch(
            lambda: self._data_client.fetch_core_probabilities(
                league_slug,
                event_id,
                competition_id,
            )
        )
        odds = self._fetch_odds_with_fallback(
            league_slug=league_slug,
            event_id=event_id,
            competition_id=competition_id,
            summary=summary,
        )
        standings = self._safe_fetch(lambda: self._data_client.fetch_standings(league_slug))
        leaders = self._safe_fetch(lambda: self._data_client.fetch_leaders(league_slug, season_year))
        rankings = self._safe_fetch(lambda: self._data_client.fetch_rankings(league_slug))
        news = self._safe_fetch(lambda: self._data_client.fetch_news(league_slug))
        teams = self._extractor.build_teams_data(
            match=match,
            league_slug=league_slug,
            summary_payload=summary.data,
            safe_fetcher=self._safe_fetch,
        )
        head_to_head = self._extractor.build_head_to_head(teams=teams)
        output_path = output_dir / self._build_file_name(match=match)

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

    def _safe_fetch(self, fetcher: Callable[[], JsonData]) -> EndpointPayload:
        """Fetch endpoint data and wrap failures into EndpointPayload.

        Args:
            fetcher: Zero-argument callable that fetches one endpoint.

        Returns:
            Endpoint payload with data or error.
        """

        try:
            payload = fetcher()
        except EspnApiError as exc:
            return EndpointPayload(data=None, error=str(exc))
        if isinstance(payload, dict) and not payload:
            return EndpointPayload(data=None)
        if isinstance(payload, list) and not payload:
            return EndpointPayload(data=None)
        return EndpointPayload(data=payload)

    def _fetch_odds_with_fallback(
        self,
        league_slug: str,
        event_id: str,
        competition_id: str,
        summary: EndpointPayload,
    ) -> EndpointPayload:
        """Fetch odds from core endpoint, then fallback to site summary.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.
            competition_id: ESPN competition identifier.
            summary: Already-fetched summary payload.

        Returns:
            Endpoint payload containing odds data or no-data marker.
        """

        core_odds = self._safe_fetch(
            lambda: self._data_client.fetch_core_odds(
                league_slug,
                event_id,
                competition_id,
            )
        )
        if core_odds.has_data():
            return core_odds
        if isinstance(summary.data, dict) and "odds" in summary.data:
            return EndpointPayload(data={"source": "site-summary", "odds": summary.data["odds"]})
        return core_odds

    def _fetch_full_plays(
        self,
        league_slug: str,
        event_id: str,
        competition_id: str,
    ) -> JsonData:
        """Fetch full play-by-play data, aggregating all available pages.

        Args:
            league_slug: ESPN league slug.
            event_id: ESPN event identifier.
            competition_id: ESPN competition identifier.

        Returns:
            Full play-by-play payload with merged ``items`` collection.
        """

        first_page = self._data_client.fetch_core_plays(
            league_slug=league_slug,
            event_id=event_id,
            competition_id=competition_id,
            page=1,
        )
        if not isinstance(first_page, dict):
            return first_page
        page_count = first_page.get("pageCount")
        if not isinstance(page_count, int) or page_count <= 1:
            return first_page
        first_items = first_page.get("items")
        if not isinstance(first_items, list):
            return first_page
        merged_items = list(first_items)
        for page in range(2, page_count + 1):
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
        return merged_payload

    def _detect_season_year(self, match: MatchRecordModel, league_slug: str) -> int:
        """Detect target season year for leaders endpoint.

        Args:
            match: Match record that may include season info.
            league_slug: ESPN league slug.

        Returns:
            Season year, defaulting to the current UTC year when unavailable.
        """

        season = match.event.season or {}
        if isinstance(season, dict):
            year_value = season.get("year")
            if isinstance(year_value, int):
                return year_value
        season_payload = self._safe_fetch(lambda: self._data_client.fetch_current_season(league_slug))
        if isinstance(season_payload.data, dict):
            year_value = season_payload.data.get("year")
            if isinstance(year_value, int):
                return year_value
        return datetime.now(timezone.utc).year

    def _build_file_name(self, match: MatchRecordModel) -> str:
        """Build safe markdown filename for one match.

        Args:
            match: Match record.

        Returns:
            Stable markdown filename.
        """

        league = match.league.slug.replace(".", "_")
        event_id = (match.event.id or "unknown").replace("/", "_")
        return f"{league}_{event_id}.md"
