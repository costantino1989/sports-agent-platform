"""Project-specific toolset used by the 1X2 Agno prediction agent.

Web search and scraping are provided by Agno's own toolkits
(``WebSearchTools`` + ``WebsiteTools``), wired directly in the deep-research
agent; this class only exposes the project's browser/terminal skills.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from src.prediction.skills import PlaywrightCliSkill, SafeTerminalSkill


class PredictionToolset:
    """Factory for the project's browser and terminal tools.

    Agno treats plain Python callables (with docstrings and type hints) as tools,
    so :meth:`build` returns the bound methods directly instead of wrapping them.
    """

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

    def build(self) -> list[Callable[..., str]]:
        """Build and return the list of callable tools for the agent."""

        return [
            self.playwright_command,
            self.safe_terminal_command,
            self.list_playwright_commands,
        ]

    def playwright_command(self, instruction: str) -> str:
        """Execute one playwright-cli command with full command parity.

        Args:
            instruction: Command content after the executable, for example
                ``open https://example.com`` or ``--raw snapshot``.

        Returns:
            Formatted command output.
        """

        result = self._playwright_skill.execute(instruction=instruction)
        return result.render()

    def safe_terminal_command(self, command: str) -> str:
        """Execute one terminal command in safe mode.

        The command runs against an allowlist with blocked dangerous patterns.

        Args:
            command: Terminal command to execute.

        Returns:
            Formatted command output.
        """

        result = self._terminal_skill.execute(command=command)
        return result.render()

    def list_playwright_commands(self) -> str:
        """Return supported playwright-cli command list as JSON text."""

        return json.dumps(
            {"commands": self._playwright_skill.supported_commands()},
            ensure_ascii=False,
        )
