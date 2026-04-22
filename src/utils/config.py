"""Runtime configuration utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.utils.color_logger import get_logger

DEFAULT_MATCH_CONCURRENCY = 5
DEFAULT_FETCH_CONCURRENCY = 12
DEFAULT_OLLAMA_MODEL = "gemma4:latest"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_TERMINAL_TIMEOUT_SECONDS = 45
DEFAULT_SCHEDULE_DB_PATH = "output\\schedule_state.db"
DEFAULT_SCHEDULE_STALE_MINUTES = 30
DEFAULT_SCHEDULE_MAX_ATTEMPTS = 2
ENV_FILE_NAME = ".env"
LOGGER = get_logger()


@dataclass(slots=True, frozen=True)
class RuntimeConfig:
    """Typed runtime settings loaded from environment variables.

    Attributes:
        match_concurrency_default: Maximum parallel dossier builds.
        fetch_concurrency_default: Maximum concurrent ESPN fetch calls.
        ollama_model: Default Ollama model used for LangGraph predictions.
        ollama_base_url: Base URL for local Ollama server.
        terminal_timeout_seconds: Timeout for safe terminal tool execution.
        schedule_db_path: Default SQLite path for scheduler persistence.
        schedule_stale_minutes: Threshold to recover stale running jobs.
        schedule_max_attempts: Maximum attempts per scheduled run.
    """

    match_concurrency_default: int
    fetch_concurrency_default: int
    ollama_model: str
    ollama_base_url: str
    terminal_timeout_seconds: int
    schedule_db_path: str
    schedule_stale_minutes: int
    schedule_max_attempts: int
    model_timeout_seconds: int


@lru_cache(maxsize=1)
def get_runtime_config() -> RuntimeConfig:
    """Load runtime configuration from ``.env`` and process environment.

    Returns:
        Parsed runtime configuration with validated positive integers.
    """

    env_loaded, env_entries = _load_project_env()
    config = RuntimeConfig(
        match_concurrency_default=_read_positive_int(
            name="MATCH_CONCURRENCY_DEFAULT",
            default=DEFAULT_MATCH_CONCURRENCY,
        ),
        fetch_concurrency_default=_read_positive_int(
            name="FETCH_CONCURRENCY_DEFAULT",
            default=DEFAULT_FETCH_CONCURRENCY,
        ),
        ollama_model=_read_non_empty_string(
            name="OLLAMA_MODEL",
            default=DEFAULT_OLLAMA_MODEL,
        ),
        ollama_base_url=_read_non_empty_string(
            name="OLLAMA_BASE_URL",
            default=DEFAULT_OLLAMA_BASE_URL,
        ),
        terminal_timeout_seconds=_read_positive_int(
            name="TERMINAL_TIMEOUT_SECONDS",
            default=DEFAULT_TERMINAL_TIMEOUT_SECONDS,
        ),
        schedule_db_path=_read_non_empty_string(
            name="SCHEDULE_DB_PATH",
            default=DEFAULT_SCHEDULE_DB_PATH,
        ),
        schedule_stale_minutes=_read_positive_int(
            name="SCHEDULE_STALE_MINUTES",
            default=DEFAULT_SCHEDULE_STALE_MINUTES,
        ),
        schedule_max_attempts=_read_positive_int(
            name="SCHEDULE_MAX_ATTEMPTS",
            default=DEFAULT_SCHEDULE_MAX_ATTEMPTS,
        ),
        model_timeout_seconds=_read_positive_int(
            name="MODEL_TIMEOUT_SECONDS",
            default=DEFAULT_SCHEDULE_MAX_ATTEMPTS,
        ),
    )
    LOGGER.info(
        "Runtime config loaded: "
        f"match_concurrency={config.match_concurrency_default}, "
        f"fetch_concurrency={config.fetch_concurrency_default}, "
        f"ollama_model={config.ollama_model}, "
        f"ollama_base_url={config.ollama_base_url}, "
        f"terminal_timeout={config.terminal_timeout_seconds}, "
        f"schedule_db_path={config.schedule_db_path}, "
        f"schedule_stale_minutes={config.schedule_stale_minutes}, "
        f"schedule_max_attempts={config.schedule_max_attempts}, "
        f"env_loaded={env_loaded}, env_entries={env_entries}, "
        f"model_timeout_seconds={config.model_timeout_seconds}"

    )
    return config


def _load_project_env() -> tuple[bool, int]:
    """Load environment variables from project ``.env`` if present.

    Returns:
        Pair containing ``env_exists`` and number of loaded entries.
    """

    env_path = _project_root() / ENV_FILE_NAME
    if not env_path.exists():
        return False, 0
    loaded_entries = 0
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if key in os.environ:
            continue
        os.environ[key] = value
        loaded_entries += 1
    return True, loaded_entries


def _project_root() -> Path:
    """Return repository root path based on this module location."""

    return Path(__file__).resolve().parents[2]


def _parse_env_line(line: str) -> tuple[str, str] | None:
    """Parse one ``KEY=VALUE`` line from an env file.

    Args:
        line: Raw env line.

    Returns:
        Parsed key/value pair when valid, otherwise ``None``.
    """

    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    clean_key = key.strip()
    if not clean_key:
        return None
    clean_value = value.strip().strip('"').strip("'")
    return clean_key, clean_value


def _read_positive_int(name: str, default: int) -> int:
    """Read one positive integer setting from environment.

    Args:
        name: Environment variable name.
        default: Fallback value when missing or invalid.

    Returns:
        Positive integer configuration value.
    """

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return default
    return parsed_value if parsed_value > 0 else default


def _read_non_empty_string(name: str, default: str) -> str:
    """Read one non-empty string setting from environment.

    Args:
        name: Environment variable name.
        default: Fallback value when missing or empty.

    Returns:
        Configuration string value.
    """

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    cleaned = raw_value.strip()
    return cleaned if cleaned else default
