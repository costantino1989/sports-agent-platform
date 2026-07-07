"""Characterization tests for the 1X2 prediction markdown pipeline."""

from __future__ import annotations

from pathlib import Path

from src.prediction.models import PredictionResult
from src.prediction.service.pipeline import PredictionMarkdownPipeline


def _make_pipeline() -> PredictionMarkdownPipeline:
    # The report renderer never touches the agent, so a placeholder is fine.
    return PredictionMarkdownPipeline(agent=None)  # type: ignore[arg-type]


def _prediction(**overrides: object) -> PredictionResult:
    defaults = {
        "match": "Home vs Away",
        "predicted_result": "1",
        "success_probability": 62,
        "rationale": "Home team in strong form.",
        "evidence_refs": ["sec:4"],
        "source_file": "eng_1_123.md",
        "outcome": "",
    }
    defaults.update(overrides)
    return PredictionResult(**defaults)  # type: ignore[arg-type]


class TestEscapeCell:
    """Tests for markdown table cell escaping."""

    def test_escapes_pipes(self) -> None:
        assert PredictionMarkdownPipeline._escape_cell("a|b") == "a\\|b"

    def test_newlines_become_breaks(self) -> None:
        assert PredictionMarkdownPipeline._escape_cell("a\nb") == "a<br>b"


class TestBuildRationaleCell:
    """Tests for rationale cell composition."""

    def test_appends_evidence_refs(self) -> None:
        result = _prediction(rationale="Reason.", evidence_refs=["a", "b"])
        cell = PredictionMarkdownPipeline._build_rationale_cell(result)
        assert cell == "Reason. Evidence refs: a; b."

    def test_no_evidence_refs(self) -> None:
        result = _prediction(rationale="Reason.", evidence_refs=[])
        assert PredictionMarkdownPipeline._build_rationale_cell(result) == "Reason."


class TestRenderMarkdownReport:
    """Tests for the consolidated markdown report."""

    def test_header_and_row(self) -> None:
        report = _make_pipeline()._render_markdown_report([_prediction()])
        assert report.startswith("# 1X2 Predictions")
        assert "| Match | Predicted result |" in report
        assert "| Home vs Away | 1 | 62% |" in report

    def test_empty_predictions_emit_placeholder_row(self) -> None:
        report = _make_pipeline()._render_markdown_report([])
        assert "| No matches available | N/A | N/A |" in report


class _RecordingAgent:
    """Fake prediction agent returning one result per file, or failing."""

    def __init__(self, fail_for: set[str] | None = None) -> None:
        self._fail_for = fail_for or set()
        self.seen: list[str] = []

    def predict_from_markdown(self, markdown_path: Path) -> PredictionResult:
        self.seen.append(markdown_path.name)
        if markdown_path.name in self._fail_for:
            raise RuntimeError("model unavailable")
        return _prediction(match=markdown_path.stem, source_file=markdown_path.name)


class TestBatchPredictions:
    """Tests for concurrent batch execution over dossier files."""

    def _dossier(self, tmp_path: Path, name: str) -> Path:
        path = tmp_path / name
        path.write_text(f"# D\n- Match: {name}\n", encoding="utf-8")
        return path

    def test_one_prediction_row_per_file_in_order(self, tmp_path: Path) -> None:
        files = [self._dossier(tmp_path, f"eng_1_{index}.md") for index in range(4)]
        agent = _RecordingAgent()
        pipeline = PredictionMarkdownPipeline(agent=agent, concurrency=2)  # type: ignore[arg-type]

        output = pipeline.run_for_files(files, output_path=tmp_path / "out.md")

        report = output.read_text(encoding="utf-8")
        assert set(agent.seen) == {path.name for path in files}
        # Order of rendered rows matches the input order.
        positions = [report.index(path.stem) for path in files]
        assert positions == sorted(positions)

    def test_failed_file_is_omitted_from_report(self, tmp_path: Path) -> None:
        # A model failure must produce NO row (no "X at 50%" placeholder): the
        # match is simply absent, keeping the persisted data clean for analysis.
        good = self._dossier(tmp_path, "eng_1_1.md")
        bad = self._dossier(tmp_path, "eng_1_2.md")
        agent = _RecordingAgent(fail_for={"eng_1_2.md"})
        pipeline = PredictionMarkdownPipeline(agent=agent, concurrency=2)  # type: ignore[arg-type]

        report = pipeline.run_for_files(
            [good, bad], output_path=tmp_path / "out.md"
        ).read_text(encoding="utf-8")

        assert "eng_1_1" in report          # the good file is present
        assert "eng_1_2" not in report      # the failed file is omitted
        assert "50%" not in report          # no fabricated fallback row
        assert "fallback" not in report


class TestExtractMatchLabel:
    """Tests for fallback match-label extraction from a dossier file."""

    def test_reads_match_line(self, tmp_path: Path) -> None:
        dossier = tmp_path / "eng_1_123.md"
        dossier.write_text("# Title\n- Match: Milan vs Inter\n", encoding="utf-8")
        assert PredictionMarkdownPipeline._extract_match_label(dossier) == "Milan vs Inter"

    def test_missing_match_line_falls_back_to_stem(self, tmp_path: Path) -> None:
        dossier = tmp_path / "eng_1_123.md"
        dossier.write_text("# Title only\n", encoding="utf-8")
        assert PredictionMarkdownPipeline._extract_match_label(dossier) == "eng_1_123"

    def test_unreadable_file_falls_back_to_stem(self, tmp_path: Path) -> None:
        missing = tmp_path / "ita_1_999.md"
        assert PredictionMarkdownPipeline._extract_match_label(missing) == "ita_1_999"
