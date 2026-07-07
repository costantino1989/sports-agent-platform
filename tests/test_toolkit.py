"""Tests that the prediction toolset exposes plain callables (no LangChain)."""

from __future__ import annotations

from src.prediction.skills import PlaywrightCliSkill, SafeTerminalSkill
from src.prediction.tools.toolkit import PredictionToolset


def _make_toolset() -> PredictionToolset:
    return PredictionToolset(
        playwright_skill=PlaywrightCliSkill(),
        terminal_skill=SafeTerminalSkill(default_timeout_seconds=45),
    )


class TestPredictionToolset:
    """Tests for the Agno-compatible toolset factory."""

    def test_build_returns_three_plain_callables(self) -> None:
        tools = _make_toolset().build()
        assert len(tools) == 3
        assert all(callable(tool) for tool in tools)

    def test_tool_names_are_stable(self) -> None:
        tools = _make_toolset().build()
        names = {getattr(tool, "__name__", "") for tool in tools}
        assert names == {
            "playwright_command",
            "safe_terminal_command",
            "list_playwright_commands",
        }
