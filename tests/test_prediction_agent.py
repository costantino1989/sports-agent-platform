"""Tests for the Agno-backed 1X2 prediction agent branch and merge logic.

The deep branch is two-phase: a tool-enabled research agent (no output schema)
gathers external evidence, then a structured prediction agent turns the dossier
plus those findings into a validated draft. The fast branch skips research.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.prediction.agents.predictor import MatchPredictionAgent
from src.prediction.models import (
    PredictionDraft,
    PredictionResult,
    PredictionUnavailableError,
    RuleSignal,
)


def _signal(**overrides: Any) -> RuleSignal:
    defaults: dict[str, Any] = {
        "name": "explicit_no_data",
        "triggered": True,
        "details": "Section missing.",
        "search_query": "team injuries",
        "priority": 4,
    }
    defaults.update(overrides)
    return RuleSignal(**defaults)


def _draft(**overrides: Any) -> PredictionDraft:
    defaults: dict[str, Any] = {
        "match": "Milan vs Inter",
        "predicted_result": "1",
        "success_probability": 63,
        "rationale": "Home side in strong form.",
        "evidence_refs": ["sec:4"],
    }
    defaults.update(overrides)
    return PredictionDraft(**defaults)


class _FakeRunResponse:
    """Minimal stand-in for an Agno run response."""

    def __init__(self, content: Any) -> None:
        self.content = content


class _FakeAgent:
    """Records prompts/invocations and returns a response or raises."""

    def __init__(self, content: Any = None, error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.calls = 0
        self.prompts: list[str] = []

    def run(self, prompt: str) -> _FakeRunResponse:
        self.calls += 1
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error
        return _FakeRunResponse(content=self._content)


def _make_agent() -> MatchPredictionAgent:
    """Build a prediction agent with dummy credentials (no network at init)."""

    return MatchPredictionAgent(
        model_id="glm-5.2",
        base_url="https://example.test/v1",
        api_key="dummy-key",
    )


def _dossier(tmp_path: Path, name: str, extra: str = "") -> Path:
    path = tmp_path / name
    path.write_text(f"# D\n- Match: Real vs Barca\n{extra}", encoding="utf-8")
    return path


class TestNeedsDeepResearch:
    """Tests for the deterministic deep-research branch selector."""

    def test_no_signals_is_fast_path(self) -> None:
        assert MatchPredictionAgent._needs_deep_research([]) is False

    def test_triggered_high_priority_signal_needs_deep_research(self) -> None:
        assert MatchPredictionAgent._needs_deep_research([_signal(priority=4)]) is True

    def test_low_priority_signal_stays_fast(self) -> None:
        assert MatchPredictionAgent._needs_deep_research([_signal(priority=3)]) is False

    def test_untriggered_high_priority_signal_stays_fast(self) -> None:
        assert (
            MatchPredictionAgent._needs_deep_research(
                [_signal(priority=5, triggered=False)]
            )
            is False
        )


class TestBuildResultFromDraft:
    """Tests for merging a model draft into a full prediction result."""

    def test_merges_source_file_and_outcome(self) -> None:
        result = MatchPredictionAgent._build_result_from_draft(
            draft=_draft(),
            default_match="Fallback vs Label",
            source_file="ita_1_1.md",
        )
        assert isinstance(result, PredictionResult)
        assert result.source_file == "ita_1_1.md"
        assert result.outcome == ""
        assert result.match == "Milan vs Inter"
        assert result.predicted_result == "1"
        assert result.success_probability == 63

    def test_over_under_fields_pass_through(self) -> None:
        result = MatchPredictionAgent._build_result_from_draft(
            draft=_draft(over_under_result="Over", over_under_line=2.5,
                         over_under_probability=68),
            default_match="X vs Y", source_file="s.md",
        )
        assert result.over_under_result == "Over"
        assert result.over_under_line == 2.5
        assert result.over_under_probability == 68

    def test_over_under_absent_defaults_to_none(self) -> None:
        result = MatchPredictionAgent._build_result_from_draft(
            draft=_draft(), default_match="X vs Y", source_file="s.md",
        )
        assert result.over_under_result is None
        assert result.over_under_probability is None

    def test_blank_draft_match_falls_back_to_default(self) -> None:
        result = MatchPredictionAgent._build_result_from_draft(
            draft=_draft(match="   "),
            default_match="Home vs Away",
            source_file="eng_1_2.md",
        )
        assert result.match == "Home vs Away"


class TestPredictFromMarkdown:
    """Tests for end-to-end per-file prediction wiring and fallback."""

    def test_fast_path_skips_research(self, tmp_path: Path) -> None:
        agent = _make_agent()
        prediction = _FakeAgent(content=_draft(match="Fast Home vs Fast Away"))
        research = _FakeAgent(content="findings text")
        agent._prediction_agent = prediction  # type: ignore[assignment]
        agent._research_agent = research  # type: ignore[assignment]

        result = agent.predict_from_markdown(markdown_path=_dossier(tmp_path, "a.md"))

        assert research.calls == 0
        assert prediction.calls == 1
        assert result.match == "Fast Home vs Fast Away"
        assert result.source_file == "a.md"

    def test_deep_path_researches_then_structures(self, tmp_path: Path) -> None:
        agent = _make_agent()
        prediction = _FakeAgent(content=_draft(match="Structured"))
        research = _FakeAgent(content="Kvaratskhelia fit; Roma missing 2 defenders")
        agent._prediction_agent = prediction  # type: ignore[assignment]
        agent._research_agent = research  # type: ignore[assignment]
        dossier = _dossier(
            tmp_path,
            "b.md",
            extra="No data found (source: ESPN API, section: Injuries).\n",
        )

        result = agent.predict_from_markdown(markdown_path=dossier)

        assert research.calls == 1
        assert prediction.calls == 1
        assert result.match == "Structured"
        # The research findings must be threaded into the structuring prompt.
        assert "Roma missing 2 defenders" in prediction.prompts[0]

    def test_research_failure_still_produces_structured_prediction(
        self, tmp_path: Path
    ) -> None:
        agent = _make_agent()
        prediction = _FakeAgent(content=_draft(match="Structured Anyway"))
        research = _FakeAgent(error=RuntimeError("search down"))
        agent._prediction_agent = prediction  # type: ignore[assignment]
        agent._research_agent = research  # type: ignore[assignment]
        dossier = _dossier(
            tmp_path,
            "c.md",
            extra="No data found (source: ESPN API, section: News).\n",
        )

        result = agent.predict_from_markdown(markdown_path=dossier)

        assert research.calls == 1
        assert prediction.calls == 1
        assert result.match == "Structured Anyway"

    def test_prediction_error_raises_unavailable(self, tmp_path: Path) -> None:
        # A model failure must NOT fabricate an "X at 50%" placeholder: it raises
        # so the caller skips the match and persists nothing.
        agent = _make_agent()
        agent._prediction_agent = _FakeAgent(error=RuntimeError("boom"))  # type: ignore[assignment]
        agent._research_agent = _FakeAgent(content="")  # type: ignore[assignment]

        with pytest.raises(PredictionUnavailableError):
            agent.predict_from_markdown(markdown_path=_dossier(tmp_path, "d.md"))

    def test_non_draft_content_raises_unavailable(self, tmp_path: Path) -> None:
        agent = _make_agent()
        agent._prediction_agent = _FakeAgent(content="not a draft")  # type: ignore[assignment]
        agent._research_agent = _FakeAgent(content="")  # type: ignore[assignment]

        with pytest.raises(PredictionUnavailableError):
            agent.predict_from_markdown(markdown_path=_dossier(tmp_path, "e.md"))


class TestAgentComposition:
    """Tests that tools and the research directive sit on the right agents."""

    def test_research_agent_carries_directive(self) -> None:
        from src.prediction.agents.predictor import DEEP_RESEARCH_DIRECTIVE

        agent = _make_agent()
        assert DEEP_RESEARCH_DIRECTIVE in str(agent._research_agent.instructions)

    def test_prediction_agent_has_no_directive(self) -> None:
        from src.prediction.agents.predictor import DEEP_RESEARCH_DIRECTIVE

        agent = _make_agent()
        assert DEEP_RESEARCH_DIRECTIVE not in str(agent._prediction_agent.instructions)

    def test_research_agent_has_web_search_and_scrape_tools(self) -> None:
        agent = _make_agent()
        tool_types = {type(tool).__name__ for tool in agent._research_agent.tools}
        assert "WebSearchTools" in tool_types
        assert "WebsiteTools" in tool_types

    def test_prediction_agent_has_no_tools(self) -> None:
        agent = _make_agent()
        assert not agent._prediction_agent.tools

    def test_research_agent_bounds_tool_calls(self) -> None:
        from src.prediction.agents.predictor import RESEARCH_TOOL_CALL_LIMIT

        agent = _make_agent()
        # Research is best-effort: cap tool calls so failed scrapes cannot spiral.
        assert agent._research_agent.tool_call_limit == RESEARCH_TOOL_CALL_LIMIT
        assert RESEARCH_TOOL_CALL_LIMIT <= 6


@pytest.mark.parametrize("predicted", ["1", "X", "2"])
def test_prediction_draft_accepts_valid_results(predicted: str) -> None:
    draft = _draft(predicted_result=predicted)
    assert draft.predicted_result == predicted
