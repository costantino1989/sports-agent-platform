"""Safe terminal execution skill for the prediction agent tools."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass


BLOCKED_SNIPPETS = (
    "rm ",
    "rmdir ",
    "del ",
    "remove-item",
    "format-",
    "shutdown",
    "restart-computer",
    "stop-computer",
    "git reset --hard",
    "git clean -fd",
)

ALLOWED_ROOT_COMMANDS = frozenset(
    {
        "python",
        "py",
        "curl",
        "wget",
        "playwright-cli",
        "npx",
        "Get-Content",
        "Select-String",
        "where",
        "where.exe",
        "Invoke-WebRequest",
    }
)


@dataclass(slots=True, frozen=True)
class TerminalCommandResult:
    """Result payload for one safe terminal command execution."""

    command: str
    exit_code: int
    stdout: str
    stderr: str

    def render(self) -> str:
        """Render terminal result as concise plain text."""

        chunks = [
            f"command: {self.command}",
            f"exit_code: {self.exit_code}",
            f"stdout:\n{self.stdout.strip() or '(empty)'}",
        ]
        if self.stderr.strip():
            chunks.append(f"stderr:\n{self.stderr.strip()}")
        return "\n\n".join(chunks)


class SafeTerminalSkill:
    """Execute terminal commands through a constrained allowlist policy."""

    def __init__(self, default_timeout_seconds: int = 45) -> None:
        """Initialize terminal skill settings.

        Args:
            default_timeout_seconds: Default timeout for each command.
        """

        self._default_timeout_seconds = max(10, default_timeout_seconds)

    def execute(
        self,
        command: str,
        timeout_seconds: int | None = None,
    ) -> TerminalCommandResult:
        """Execute one safe terminal command.

        Args:
            command: Raw command string.
            timeout_seconds: Optional timeout override.

        Returns:
            Execution result with stdout and stderr.

        Raises:
            ValueError: When command is blocked by policy.
        """

        self._validate_command(command=command)
        effective_timeout = timeout_seconds or self._default_timeout_seconds
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=max(10, effective_timeout),
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            return TerminalCommandResult(
                command=command,
                exit_code=124,
                stdout=error.stdout or "",
                stderr=f"Command timed out after {max(10, effective_timeout)} seconds.",
            )
        return TerminalCommandResult(
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    @staticmethod
    def _validate_command(command: str) -> None:
        """Validate that command respects safe execution policy."""

        normalized = command.strip()
        if not normalized:
            raise ValueError("Terminal command cannot be empty.")
        lowered = normalized.lower()
        for snippet in BLOCKED_SNIPPETS:
            if snippet in lowered:
                raise ValueError(f"Blocked terminal command pattern detected: {snippet}")
        tokens = shlex.split(normalized, posix=False)
        if not tokens:
            raise ValueError("Terminal command cannot be empty.")
        root_command = tokens[0]
        if root_command == "npx":
            if len(tokens) < 2 or tokens[1] != "playwright-cli":
                raise ValueError("Safe mode allows npx only for playwright-cli.")
            return
        if root_command not in ALLOWED_ROOT_COMMANDS:
            raise ValueError(
                f"Command '{root_command}' is not allowed in safe mode."
            )

