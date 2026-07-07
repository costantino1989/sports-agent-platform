"""Characterization tests for runtime configuration parsing helpers."""

from __future__ import annotations

import pytest

from src.utils import config as config_module
from src.utils.config import (
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    _parse_env_line,
    _read_non_empty_string,
    _read_positive_int,
    get_runtime_config,
)


class TestParseEnvLine:
    """Tests for the .env line parser."""

    def test_simple_pair(self) -> None:
        assert _parse_env_line("KEY=value") == ("KEY", "value")

    def test_strips_whitespace_and_quotes(self) -> None:
        assert _parse_env_line('  KEY = "value"  ') == ("KEY", "value")

    def test_single_quotes_stripped(self) -> None:
        assert _parse_env_line("KEY='value'") == ("KEY", "value")

    def test_value_may_contain_equals(self) -> None:
        assert _parse_env_line("URL=http://x?a=b") == ("URL", "http://x?a=b")

    @pytest.mark.parametrize("line", ["", "   ", "# comment", "no-equals-sign", "=orphan"])
    def test_invalid_lines_return_none(self, line: str) -> None:
        assert _parse_env_line(line) is None


class TestReadPositiveInt:
    """Tests for positive-integer environment reading."""

    def test_missing_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SOME_INT", raising=False)
        assert _read_positive_int("SOME_INT", default=7) == 7

    def test_valid_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOME_INT", "12")
        assert _read_positive_int("SOME_INT", default=7) == 12

    @pytest.mark.parametrize("raw", ["0", "-3", "abc"])
    def test_invalid_or_non_positive_returns_default(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        monkeypatch.setenv("SOME_INT", raw)
        assert _read_positive_int("SOME_INT", default=7) == 7


class TestReadNonEmptyString:
    """Tests for non-empty-string environment reading."""

    def test_missing_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SOME_STR", raising=False)
        assert _read_non_empty_string("SOME_STR", default="fallback") == "fallback"

    def test_blank_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOME_STR", "   ")
        assert _read_non_empty_string("SOME_STR", default="fallback") == "fallback"

    def test_value_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOME_STR", "custom")
        assert _read_non_empty_string("SOME_STR", default="fallback") == "custom"


class TestRuntimeModelConfig:
    """Tests for the model/prediction settings of the runtime config."""

    def test_model_timeout_default_allows_large_dossiers(self) -> None:
        # A full live dossier (~28KB) needs ~110s for the structured prediction,
        # so the default timeout must comfortably exceed that (and never collapse
        # to the scheduler max-attempts value of 2s as it did pre-migration).
        assert DEFAULT_MODEL_TIMEOUT_SECONDS >= 180

    def test_reads_model_settings_from_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ZEN_MODEL_ID", "glm-5.2")
        monkeypatch.setenv("ZEN_BASE_URL", "https://opencode.ai/zen/go/v1")
        monkeypatch.setenv("ZEN_API_KEY", "secret-token")
        monkeypatch.setenv("PREDICTION_CONCURRENCY", "3")
        get_runtime_config.cache_clear()
        try:
            config = get_runtime_config()
        finally:
            get_runtime_config.cache_clear()
        assert config.model_id == "glm-5.2"
        assert config.model_base_url == "https://opencode.ai/zen/go/v1"
        assert config.model_api_key == "secret-token"
        assert config.prediction_concurrency == 3

    def test_module_exposes_model_defaults(self) -> None:
        assert hasattr(config_module, "DEFAULT_MODEL_ID")
        assert hasattr(config_module, "DEFAULT_MODEL_BASE_URL")
