"""Action that builds prediction markdown files for live matches."""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.dossier.builder import MatchDossierBuilder
from src.dossier.client import DossierDataClient
from src.dossier.extractor import DossierDataExtractor
from src.dossier.render import MatchMarkdownRenderer
from src.models.live_models import MatchRecordModel
from src.utils import get_logger

LOGGER = get_logger()


class MatchDossierAction:
    """Build one markdown dossier per live match from ESPN data sources.

    Attributes:
        _builder: Async builder that fetches and aggregates dossier data.
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

        self._builder = MatchDossierBuilder(
            data_client=data_client,
            extractor=extractor,
        )
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
        LOGGER.info(
            f"Generating markdown dossiers for {len(matches)} in-progress matches."
        )
        if not matches:
            LOGGER.warn("No eligible matches were provided, markdown dossier output will be empty.")
            return []
        dossiers = asyncio.run(
            self._builder.build_many(
                matches=matches,
                output_dir=output_dir,
            )
        )
        LOGGER.info("Rendering and writing markdown outputs.")
        output_files: list[Path] = []
        for dossier in dossiers:
            markdown = self._renderer.render(dossier)
            dossier.output_path.write_text(markdown, encoding="utf-8")
            output_files.append(dossier.output_path)
            LOGGER.info(f"Saved markdown file: {dossier.output_path}")
        LOGGER.info(f"Generated {len(output_files)} markdown dossier files.")
        return output_files
