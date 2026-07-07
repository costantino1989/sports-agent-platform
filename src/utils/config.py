"""Runtime configuration utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.utils.color_logger import get_logger

DEFAULT_MATCH_CONCURRENCY = 5
DEFAULT_FETCH_CONCURRENCY = 12
DEFAULT_MODEL_ID = "glm-5.2"
DEFAULT_MODEL_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL_API_KEY = ""
DEFAULT_PREDICTION_CONCURRENCY = 4
DEFAULT_PREDICTION_LOCK_CONFIDENCE = 80
DEFAULT_PREDICTION_FORCE_REFRESH_EVERY = 3
DEFAULT_PREDICTION_RECENT_EVENTS = 15
DEFAULT_PREDICTION_ACTIVE_WINDOW_HOURS = 3
DEFAULT_PREDICTION_MAX_BET_MINUTE = 80
DEFAULT_PREDICTION_MIN_ODDS = 1.2
DEFAULT_PREDICTION_LOCK_ODDS = 1.25
DEFAULT_PREDICTION_KELLY_FRACTION = 0.25
# Hard ceiling on the bankroll fraction staked per bet, so a low-odds pick cannot
# risk a big slice for a tiny payout even when Kelly would size it large.
DEFAULT_PREDICTION_MAX_STAKE_FRACTION = 0.05
# Synthetic betting: when no real bookmaker odds exist, still simulate a bet at a
# conservative placeholder price (a win pays little, a loss costs the full stake)
# using a flat fraction of the bankroll, reported separately from real bets.
DEFAULT_PREDICTION_SYNTHETIC_ODDS = 1.2
DEFAULT_PREDICTION_SYNTHETIC_STAKE_FRACTION = 0.02
DEFAULT_ODDS_API_KEY = ""
DEFAULT_ODDS_API_REGION = "eu"
DEFAULT_ODDS_API_BOOKMAKER = "betfair_ex_eu"
DEFAULT_ODDS_API_CACHE_MINUTES = 3
DEFAULT_ODDS_FALLBACK_PROVIDER = "Bet 365"
DEFAULT_API_FOOTBALL_KEY = ""
DEFAULT_TELEGRAM_BOT_TOKEN = ""
DEFAULT_TELEGRAM_CHAT_ID = ""
DEFAULT_TERMINAL_TIMEOUT_SECONDS = 45
DEFAULT_MODEL_TIMEOUT_SECONDS = 180
DEFAULT_SCHEDULE_DB_PATH = "output/schedule_state.db"
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
        model_id: Model identifier used by the Agno prediction agent.
        model_base_url: Base URL of the OpenAI-compatible model endpoint.
        model_api_key: API key for the model endpoint.
        prediction_concurrency: Maximum parallel per-match predictions.
        terminal_timeout_seconds: Timeout for safe terminal tool execution.
        schedule_db_path: Default SQLite path for scheduler persistence.
        schedule_stale_minutes: Threshold to recover stale running jobs.
        schedule_max_attempts: Maximum attempts per scheduled run.
        model_timeout_seconds: HTTP timeout for model requests.
    """

    match_concurrency_default: int
    fetch_concurrency_default: int
    model_id: str
    model_base_url: str
    model_api_key: str
    prediction_concurrency: int
    prediction_lock_confidence: int
    prediction_force_refresh_every: int
    prediction_recent_events: int
    prediction_active_window_hours: int
    prediction_max_bet_minute: int
    prediction_min_odds: float
    prediction_lock_odds: float
    prediction_kelly_fraction: float
    prediction_max_stake_fraction: float
    prediction_synthetic_odds: float
    prediction_synthetic_stake_fraction: float
    odds_api_key: str
    odds_api_region: str
    odds_api_bookmaker: str
    odds_api_cache_minutes: int
    odds_fallback_provider: str
    api_football_key: str
    telegram_bot_token: str
    telegram_chat_id: str
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
        model_id=_read_non_empty_string(
            name="ZEN_MODEL_ID",
            default=DEFAULT_MODEL_ID,
        ),
        model_base_url=_read_non_empty_string(
            name="ZEN_BASE_URL",
            default=DEFAULT_MODEL_BASE_URL,
        ),
        model_api_key=_read_non_empty_string(
            name="ZEN_API_KEY",
            default=DEFAULT_MODEL_API_KEY,
        ),
        prediction_concurrency=_read_positive_int(
            name="PREDICTION_CONCURRENCY",
            default=DEFAULT_PREDICTION_CONCURRENCY,
        ),
        prediction_lock_confidence=_read_positive_int(
            name="PREDICTION_LOCK_CONFIDENCE",
            default=DEFAULT_PREDICTION_LOCK_CONFIDENCE,
        ),
        prediction_force_refresh_every=_read_positive_int(
            name="PREDICTION_FORCE_REFRESH_EVERY",
            default=DEFAULT_PREDICTION_FORCE_REFRESH_EVERY,
        ),
        prediction_recent_events=_read_positive_int(
            name="PREDICTION_RECENT_EVENTS",
            default=DEFAULT_PREDICTION_RECENT_EVENTS,
        ),
        prediction_active_window_hours=_read_positive_int(
            name="PREDICTION_ACTIVE_WINDOW_HOURS",
            default=DEFAULT_PREDICTION_ACTIVE_WINDOW_HOURS,
        ),
        prediction_max_bet_minute=_read_positive_int(
            name="PREDICTION_MAX_BET_MINUTE",
            default=DEFAULT_PREDICTION_MAX_BET_MINUTE,
        ),
        prediction_min_odds=_read_positive_float(
            name="PREDICTION_MIN_ODDS",
            default=DEFAULT_PREDICTION_MIN_ODDS,
        ),
        prediction_lock_odds=_read_positive_float(
            name="PREDICTION_LOCK_ODDS",
            default=DEFAULT_PREDICTION_LOCK_ODDS,
        ),
        prediction_kelly_fraction=_read_positive_float(
            name="PREDICTION_KELLY_FRACTION",
            default=DEFAULT_PREDICTION_KELLY_FRACTION,
        ),
        prediction_max_stake_fraction=_read_positive_float(
            name="PREDICTION_MAX_STAKE_FRACTION",
            default=DEFAULT_PREDICTION_MAX_STAKE_FRACTION,
        ),
        prediction_synthetic_odds=_read_positive_float(
            name="PREDICTION_SYNTHETIC_ODDS",
            default=DEFAULT_PREDICTION_SYNTHETIC_ODDS,
        ),
        prediction_synthetic_stake_fraction=_read_positive_float(
            name="PREDICTION_SYNTHETIC_STAKE_FRACTION",
            default=DEFAULT_PREDICTION_SYNTHETIC_STAKE_FRACTION,
        ),
        odds_api_key=os.getenv("ODDS_API_KEY", DEFAULT_ODDS_API_KEY).strip(),
        odds_api_region=_read_non_empty_string(
            name="ODDS_API_REGION",
            default=DEFAULT_ODDS_API_REGION,
        ),
        odds_api_bookmaker=_read_non_empty_string(
            name="ODDS_API_BOOKMAKER",
            default=DEFAULT_ODDS_API_BOOKMAKER,
        ),
        odds_api_cache_minutes=_read_positive_int(
            name="ODDS_API_CACHE_MINUTES",
            default=DEFAULT_ODDS_API_CACHE_MINUTES,
        ),
        odds_fallback_provider=_read_non_empty_string(
            name="ODDS_FALLBACK_PROVIDER",
            default=DEFAULT_ODDS_FALLBACK_PROVIDER,
        ),
        api_football_key=os.getenv(
            "API_FOOTBALL_KEY", DEFAULT_API_FOOTBALL_KEY
        ).strip(),
        telegram_bot_token=os.getenv(
            "TELEGRAM_BOT_TOKEN", DEFAULT_TELEGRAM_BOT_TOKEN
        ).strip(),
        telegram_chat_id=os.getenv(
            "TELEGRAM_CHAT_ID", DEFAULT_TELEGRAM_CHAT_ID
        ).strip(),
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
            default=DEFAULT_MODEL_TIMEOUT_SECONDS,
        ),
    )
    LOGGER.info(
        "Runtime config loaded: "
        f"match_concurrency={config.match_concurrency_default}, "
        f"fetch_concurrency={config.fetch_concurrency_default}, "
        f"model_id={config.model_id}, "
        f"model_base_url={config.model_base_url}, "
        f"model_api_key_set={bool(config.model_api_key)}, "
        f"prediction_concurrency={config.prediction_concurrency}, "
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


def _read_positive_float(name: str, default: float) -> float:
    """Read one positive float setting from environment.

    Args:
        name: Environment variable name.
        default: Fallback value when missing or invalid.

    Returns:
        Positive float configuration value.
    """

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        parsed_value = float(raw_value)
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
