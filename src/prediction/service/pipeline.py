"""Batch pipeline that runs 1X2 predictions and writes one markdown report."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from src.prediction.agents import MatchPredictionAgent
from src.prediction.models import PredictionResult
from src.utils import get_logger

LOGGER = get_logger()

DEFAULT_PREDICTION_CONCURRENCY = 4


class PredictionMarkdownPipeline:
    """Run predictions for many dossier markdown files and save one report."""

    def __init__(
        self,
        agent: MatchPredictionAgent,
        concurrency: int = DEFAULT_PREDICTION_CONCURRENCY,
    ) -> None:
        """Initialize pipeline dependencies.

        Args:
            agent: Prediction agent used for each dossier file.
            concurrency: Maximum number of matches predicted in parallel.
        """

        self._agent = agent
        self._concurrency = max(1, concurrency)

    def run_for_directory(self, markdown_dir: Path, output_path: Path) -> Path:
        """Run prediction pipeline for all markdown files in a directory."""

        markdown_files = sorted(markdown_dir.glob("*.md"))
        return self.run_for_files(
            markdown_files=markdown_files, output_path=output_path
        )

    def run_for_files(self, markdown_files: list[Path], output_path: Path) -> Path:
        """Run prediction pipeline for explicit markdown files."""

        return asyncio.run(
            self.arun_for_files(markdown_files=markdown_files, output_path=output_path)
        )

    async def arun_for_files(
        self, markdown_files: list[Path], output_path: Path
    ) -> Path:
        """Predict many dossier files concurrently and save one report.

        Predictions run in parallel bounded by ``concurrency`` (independent
        matches), preserving input order in the rendered report. Each match is
        isolated: a failure becomes a conservative fallback row instead of
        aborting the batch.

        Args:
            markdown_files: Dossier markdown files to predict.
            output_path: Destination markdown report file.

        Returns:
            The written report path.
        """

        LOGGER.info(
            f"Starting 1X2 predictions for {len(markdown_files)} dossier files "
            f"(concurrency={self._concurrency})."
        )
        semaphore = asyncio.Semaphore(self._concurrency)
        results = await asyncio.gather(
            *(
                self._predict_one(markdown_file=markdown_file, semaphore=semaphore)
                for markdown_file in markdown_files
            )
        )
        # Files whose model call failed yield None and are omitted from the
        # report: a fabricated "X at 50%" row would pollute the data. Order is
        # preserved for the rows that remain.
        predictions = [result for result in results if result is not None]
        markdown = self._render_markdown_report(predictions=predictions)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        LOGGER.info(
            f"Saved consolidated prediction report: {output_path} "
            f"({len(predictions)} rows)."
        )
        return output_path

    async def _predict_one(
        self, markdown_file: Path, semaphore: asyncio.Semaphore
    ) -> PredictionResult | None:
        """Predict a single dossier file off the event loop.

        Returns ``None`` when the model cannot produce a usable prediction, so
        the match is omitted from the report rather than filled with a fabricated
        placeholder (which would corrupt the data used for later analysis).
        """

        async with semaphore:
            try:
                return await asyncio.to_thread(
                    self._agent.predict_from_markdown, markdown_file
                )
            except (OSError, RuntimeError, ValueError) as error:
                LOGGER.error(
                    f"Prediction unavailable for {markdown_file.name}, omitting: {error}"
                )
                return None

    def _render_markdown_report(self, predictions: list[PredictionResult]) -> str:
        """Render consolidated markdown table report."""

        lines = [
            "# 1X2 Predictions",
            "",
            "| Match | Predicted result | Success probability | Detailed rationale | Outcome |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in predictions:
            rationale_cell = self._escape_cell(
                self._build_rationale_cell(prediction=item)
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        self._escape_cell(item.match),
                        self._escape_cell(item.predicted_result),
                        self._escape_cell(f"{item.success_probability}%"),
                        rationale_cell,
                        self._escape_cell(item.outcome),
                    ]
                )
                + " |"
            )
        if not predictions:
            lines.append(
                "| No matches available | N/A | N/A | No dossier files were generated. | |"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _extract_match_label(markdown_file: Path) -> str:
        """Extract match label from dossier markdown fallback path."""

        try:
            content = markdown_file.read_text(encoding="utf-8")
        except OSError:
            return markdown_file.stem
        match = re.search(r"^- Match:\s*(?P<value>.+)$", content, re.MULTILINE)
        if match is None:
            return markdown_file.stem
        return match.group("value").strip()

    @staticmethod
    def _build_rationale_cell(prediction: PredictionResult) -> str:
        """Build rationale cell text with embedded evidence references."""

        evidence_text = ""
        if prediction.evidence_refs:
            references = "; ".join(prediction.evidence_refs)
            evidence_text = f" Evidence refs: {references}."
        return f"{prediction.rationale}{evidence_text}"

    @staticmethod
    def _escape_cell(value: str) -> str:
        """Escape markdown table cell content."""

        escaped = value.replace("|", "\\|").replace("\n", "<br>")
        return escaped.strip()
