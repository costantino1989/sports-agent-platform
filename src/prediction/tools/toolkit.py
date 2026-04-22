"""LangChain toolset used by the 1X2 LangGraph agent."""

from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from langchain_core.tools import BaseTool, StructuredTool

from src.prediction.skills import PlaywrightCliSkill, SafeTerminalSkill


class PredictionToolset:
    """Factory for browser, terminal, and HTTP tools."""

    def __init__(
        self,
        playwright_skill: PlaywrightCliSkill,
        terminal_skill: SafeTerminalSkill,
    ) -> None:
        """Initialize the toolset with injected skill instances.

        Args:
            playwright_skill: Playwright CLI wrapper skill.
            terminal_skill: Safe terminal execution skill.
        """

        self._playwright_skill = playwright_skill
        self._terminal_skill = terminal_skill

    def build(self) -> list[BaseTool]:
        """Build and return the list of LangChain tools."""

        return [
            StructuredTool.from_function(
                func=self.playwright_command,
                name="playwright_command",
                description=(
                    "Execute one playwright-cli command with full command parity. "
                    "Input should be command content after executable, for example "
                    "'open https://example.com' or '--raw snapshot'."
                ),
            ),
            StructuredTool.from_function(
                func=self.safe_terminal_command,
                name="safe_terminal_command",
                description=(
                    "Execute one terminal command in safe mode with allowlist and "
                    "blocked dangerous patterns."
                ),
            ),
            StructuredTool.from_function(
                func=self.fetch_url_text,
                name="fetch_url_text",
                description=(
                    "Fetch plain text from one URL for evidence extraction. "
                    "Prefer this when you already know the target URL."
                ),
            ),
            StructuredTool.from_function(
                func=self.list_playwright_commands,
                name="list_playwright_commands",
                description="List all supported playwright-cli commands.",
            ),
        ]

    def playwright_command(self, instruction: str) -> str:
        """Run one Playwright CLI instruction and return formatted output."""

        result = self._playwright_skill.execute(instruction=instruction)
        return result.render()

    def safe_terminal_command(self, command: str) -> str:
        """Run one safe terminal command and return formatted output."""

        result = self._terminal_skill.execute(command=command)
        return result.render()

    @staticmethod
    def fetch_url_text(url: str, max_chars: int = 6000) -> str:
        """Fetch webpage content and return a compact text payload.

        Args:
            url: Target URL to fetch.
            max_chars: Maximum returned content length.

        Returns:
            JSON string with URL, status, and content snippet.
        """

        request = Request(
            url=url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BettingBot/1.0)"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except URLError as error:
            return json.dumps(
                {"url": url, "status": "error", "error": str(error)},
                ensure_ascii=False,
            )
        limited_content = raw[: max(500, max_chars)]
        return json.dumps(
            {"url": url, "status": "ok", "content": limited_content},
            ensure_ascii=False,
        )

    def list_playwright_commands(self) -> str:
        """Return supported playwright-cli command list as JSON text."""

        return json.dumps(
            {"commands": self._playwright_skill.supported_commands()},
            ensure_ascii=False,
        )

