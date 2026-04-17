"""Colored console logger with caller metadata."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime
from types import FrameType


@dataclass(frozen=True, slots=True)
class LogCallerContext:
    """Caller metadata used to format one log line.

    Attributes:
        class_name: Class name inferred from the caller frame.
        line_number: Line number inferred from the caller frame.
    """

    class_name: str
    line_number: int


class ColorLogger:
    """Print colored logs with timestamp, class, and source line."""

    _LEVEL_DEBUG = "DEBUG"
    _LEVEL_INFO = "INFO"
    _LEVEL_WARN = "WARN"
    _LEVEL_ERROR = "ERROR"

    _COLOR_RESET = "\033[0m"
    _LEVEL_COLORS = {
        _LEVEL_DEBUG: "\033[34m",
        _LEVEL_INFO: "\033[32m",
        _LEVEL_WARN: "\033[33m",
        _LEVEL_ERROR: "\033[31m",
    }

    def debug(self, message: str) -> None:
        """Log a debug message in blue.

        Args:
            message: Message to log.
        """

        self._log(level=self._LEVEL_DEBUG, message=message)

    def info(self, message: str) -> None:
        """Log an info message in green.

        Args:
            message: Message to log.
        """

        self._log(level=self._LEVEL_INFO, message=message)

    def warn(self, message: str) -> None:
        """Log a warning message in yellow.

        Args:
            message: Message to log.
        """

        self._log(level=self._LEVEL_WARN, message=message)

    def error(self, message: str) -> None:
        """Log an error message in red.

        Args:
            message: Message to log.
        """

        self._log(level=self._LEVEL_ERROR, message=message)

    def _log(self, level: str, message: str) -> None:
        """Build and print one formatted log entry.

        Args:
            level: Log severity level.
            message: Message to log.
        """

        context = self._resolve_caller_context()
        entry = self._build_entry(level=level, message=message, context=context)
        color = self._LEVEL_COLORS[level]
        print(f"{color}{entry}{self._COLOR_RESET}")

    def _build_entry(self, level: str, message: str, context: LogCallerContext) -> str:
        """Build a normalized log entry string.

        Args:
            level: Log severity level.
            message: Message to log.
            context: Caller metadata for class and line.

        Returns:
            Formatted log entry.
        """

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"{timestamp} | {level:<5} | "
            f"{context.class_name}:{context.line_number} | {message}"
        )

    def _resolve_caller_context(self) -> LogCallerContext:
        """Extract caller class name and line number from the stack.

        Returns:
            Caller context used by the log formatter.
        """

        frame = inspect.currentframe()
        if frame is None:
            return LogCallerContext(class_name="Unknown", line_number=0)
        try:
            caller_frame = frame.f_back
            while caller_frame is not None and caller_frame.f_code.co_filename == __file__:
                caller_frame = caller_frame.f_back
            if caller_frame is None:
                return LogCallerContext(class_name="Unknown", line_number=0)
            return LogCallerContext(
                class_name=self._extract_class_name(caller_frame=caller_frame),
                line_number=caller_frame.f_lineno,
            )
        finally:
            del frame

    def _extract_class_name(self, caller_frame: FrameType) -> str:
        """Extract class name from a caller frame.

        Args:
            caller_frame: Stack frame where logging was triggered.

        Returns:
            Class name when available, otherwise module name.
        """

        local_self = caller_frame.f_locals.get("self")
        if local_self is not None:
            return local_self.__class__.__name__
        local_cls = caller_frame.f_locals.get("cls")
        if isinstance(local_cls, type):
            return local_cls.__name__
        return caller_frame.f_globals.get("__name__", "Module")


_SHARED_LOGGER = ColorLogger()


def get_logger() -> ColorLogger:
    """Return the shared logger instance for the process."""

    return _SHARED_LOGGER
