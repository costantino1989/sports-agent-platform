"""Project-local Playwright CLI skill wrapper with 1:1 command parity."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

SUPPORTED_PLAYWRIGHT_COMMANDS = frozenset(
    {
        "open",
        "attach",
        "goto",
        "type",
        "click",
        "dblclick",
        "fill",
        "drag",
        "hover",
        "select",
        "upload",
        "check",
        "uncheck",
        "snapshot",
        "eval",
        "dialog-accept",
        "dialog-dismiss",
        "resize",
        "close",
        "go-back",
        "go-forward",
        "reload",
        "press",
        "keydown",
        "keyup",
        "mousemove",
        "mousedown",
        "mouseup",
        "mousewheel",
        "screenshot",
        "pdf",
        "tab-list",
        "tab-new",
        "tab-close",
        "tab-select",
        "state-save",
        "state-load",
        "cookie-list",
        "cookie-get",
        "cookie-set",
        "cookie-delete",
        "cookie-clear",
        "localstorage-list",
        "localstorage-get",
        "localstorage-set",
        "localstorage-delete",
        "localstorage-clear",
        "sessionstorage-list",
        "sessionstorage-get",
        "sessionstorage-set",
        "sessionstorage-delete",
        "sessionstorage-clear",
        "route",
        "route-list",
        "unroute",
        "console",
        "network",
        "run-code",
        "tracing-start",
        "tracing-stop",
        "video-start",
        "video-chapter",
        "video-stop",
        "list",
        "close-all",
        "kill-all",
        "delete-data",
    }
)


@dataclass(slots=True, frozen=True)
class PlaywrightCommandResult:
    """Execution result for one Playwright CLI command."""

    command_line: str
    exit_code: int
    stdout: str
    stderr: str

    def render(self) -> str:
        """Render command execution result as compact plain text."""

        sections = [
            f"command: {self.command_line}",
            f"exit_code: {self.exit_code}",
            f"stdout:\n{self.stdout.strip() or '(empty)'}",
        ]
        if self.stderr.strip():
            sections.append(f"stderr:\n{self.stderr.strip()}")
        return "\n\n".join(sections)


class PlaywrightCliSkill:
    """Execute Playwright CLI commands with strict command validation."""

    def __init__(
            self,
            binary: str = "playwright-cli",
            default_timeout_seconds: int = 90,
    ) -> None:
        """Initialize CLI wrapper.

        Args:
            binary: Playwright CLI executable name.
            default_timeout_seconds: Default subprocess timeout.
        """

        self._binary = binary
        self._default_timeout_seconds = max(10, default_timeout_seconds)

    def execute(
            self,
            instruction: str,
            timeout_seconds: int | None = None,
    ) -> PlaywrightCommandResult:
        """Execute one validated Playwright command instruction.

        Args:
            instruction: Command string with optional global options and arguments.
            timeout_seconds: Optional timeout override.

        Returns:
            Structured execution result.

        Raises:
            ValueError: When command is empty or unsupported.
        """

        argv = self._build_argv(instruction=instruction)
        command_name = self._extract_command_name(argv[1:])
        if command_name not in SUPPORTED_PLAYWRIGHT_COMMANDS:
            raise ValueError(
                f"Unsupported playwright-cli command '{command_name}'. "
                "The project requires 1:1 parity with the known command surface."
            )
        effective_timeout = timeout_seconds or self._default_timeout_seconds
        command_line = " ".join(argv)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=max(10, effective_timeout),
                check=False,
            )
        except FileNotFoundError:
            return PlaywrightCommandResult(
                command_line=command_line,
                exit_code=127,
                stdout="",
                stderr=(
                    "playwright-cli executable not found. "
                    "Install it globally or ensure it is available in PATH."
                ),
            )
        except subprocess.TimeoutExpired as error:
            return PlaywrightCommandResult(
                command_line=command_line,
                exit_code=124,
                stdout=error.stdout or "",
                stderr=f"Command timed out after {max(10, effective_timeout)} seconds.",
            )
        return PlaywrightCommandResult(
            command_line=command_line,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _build_argv(self, instruction: str) -> list[str]:
        """Build subprocess argv from user instruction."""

        if not instruction.strip():
            raise ValueError("Playwright instruction cannot be empty.")
        tokens = shlex.split(instruction, posix=False)
        if not tokens:
            raise ValueError("Playwright instruction cannot be empty.")
        if tokens[0] == "playwright-cli":
            return tokens
        if len(tokens) >= 2 and tokens[0] == "npx" and tokens[1] == "playwright-cli":
            return tokens
        return [self._binary, *tokens]

    @staticmethod
    def _extract_command_name(tokens: list[str]) -> str:
        """Extract the playwright command name after global options."""

        if not tokens:
            raise ValueError("Missing playwright command.")
        if tokens[0] == "playwright-cli":
            tokens = tokens[1:]
        if tokens and tokens[0] == "npx":
            if len(tokens) < 3 or tokens[1] != "playwright-cli":
                raise ValueError("Invalid npx usage for playwright-cli command.")
            tokens = tokens[2:]
        for token in tokens:
            if token.startswith("-"):
                continue
            return token
        raise ValueError("Missing playwright command after global options.")

    @staticmethod
    def supported_commands() -> list[str]:
        """Return sorted list of supported Playwright CLI commands."""

        return sorted(SUPPORTED_PLAYWRIGHT_COMMANDS)
