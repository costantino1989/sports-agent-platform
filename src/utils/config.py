"""Runtime configuration utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.utils.color_logger import get_logger

DEFAULT_MATCH_CONCURRENCY = 5
DEFAULT_FETCH_CONCURRENCY = 12
ENV_FILE_NAME = ".env"
LOGGER = get_logger()


@dataclass(slots=True, frozen=True)
class RuntimeConfig:
    """Typed runtime settings loaded from environment variables.

    Attributes:
        match_concurrency_default: Maximum parallel dossier builds.
        fetch_concurrency_default: Maximum concurrent ESPN fetch calls.
    """

    match_concurrency_default: int
    fetch_concurrency_default: int


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
    )
    LOGGER.info(
        "Runtime config loaded: "
        f"match_concurrency={config.match_concurrency_default}, "
        f"fetch_concurrency={config.fetch_concurrency_default}, "
        f"env_loaded={env_loaded}, env_entries={env_entries}"
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
