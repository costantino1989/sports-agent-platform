"""Batch pipeline that runs 1X2 predictions and writes one markdown report."""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from src.prediction.agents import MatchPredictionAgent
from src.prediction.models import PredictionResult
from src.utils import get_logger

LOGGER = get_logger()


class PredictionMarkdownPipeline:
    """Run predictions for many dossier markdown files and save one report."""

    def __init__(self, agent: MatchPredictionAgent) -> None:
        """Initialize pipeline dependencies.

        Args:
            agent: Prediction agent used for each dossier file.
        """

        self._agent = agent

    def run_for_directory(self, markdown_dir: Path, output_path: Path) -> Path:
        """Run prediction pipeline for all markdown files in a directory."""

        markdown_files = sorted(markdown_dir.glob("*.md"))
        return self.run_for_files(markdown_files=markdown_files, output_path=output_path)

    def run_for_files(self, markdown_files: list[Path], output_path: Path) -> Path:
        """Run prediction pipeline for explicit markdown files."""

        predictions: list[PredictionResult] = []
        LOGGER.info(f"Starting 1X2 predictions for {len(markdown_files)} dossier files.")
        for markdown_file in markdown_files:
            try:
                prediction = self._agent.predict_from_markdown(markdown_path=markdown_file)
            except (
                    OSError,
                    RuntimeError,
                    ValueError,
                    httpx.HTTPError,
            ) as error:
                LOGGER.error(
                    f"Prediction failed for {markdown_file.name}: {error}"
                )
                prediction = PredictionResult(
                    match=self._extract_match_label(markdown_file=markdown_file),
                    predicted_result="X",
                    success_probability=50,
                    rationale=(
                        "Prediction execution failed. "
                        f"Error details: {error}"
                    ),
                    evidence_refs=["fallback:prediction_error"],
                    source_file=markdown_file.name,
                    outcome="",
                )
            predictions.append(prediction)
        markdown = self._render_markdown_report(predictions=predictions)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        LOGGER.info(
            f"Saved consolidated prediction report: {output_path} "
            f"({len(predictions)} rows)."
        )
        return output_path

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
            lines.append("| No matches available | N/A | N/A | No dossier files were generated. | |")
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
