"""Characterization tests for dossier markdown rendering helpers."""

from __future__ import annotations

import pytest

from src.dossier.render_tools import (
    as_text,
    build_stat_map,
    find_dicts_with_keys,
    first_value,
    format_utc_datetime,
    render_table,
    sanitize_payload,
)


class TestAsText:
    """Tests for the compact display-string converter."""

    def test_none_returns_default(self) -> None:
        assert as_text(None) == "N/A"

    def test_none_returns_custom_default(self) -> None:
        assert as_text(None, default="-") == "-"

    def test_blank_string_returns_default(self) -> None:
        assert as_text("   ") == "N/A"

    def test_string_is_stripped(self) -> None:
        assert as_text("  Milan  ") == "Milan"

    def test_float_is_formatted_two_decimals(self) -> None:
        assert as_text(1.5) == "1.50"

    def test_integer_is_stringified(self) -> None:
        assert as_text(3) == "3"


class TestRenderTable:
    """Tests for markdown table rendering."""

    def test_headers_and_rows(self) -> None:
        table = render_table(["A", "B"], [["1", "2"], ["3", "4"]])
        assert table == (
            "| A | B |\n"
            "| --- | --- |\n"
            "| 1 | 2 |\n"
            "| 3 | 4 |"
        )

    def test_no_rows_emits_header_and_separator_only(self) -> None:
        table = render_table(["X"], [])
        assert table == "| X |\n| --- |"


class TestSanitizePayload:
    """Tests for recursive payload sanitization."""

    def test_removes_technical_keys(self) -> None:
        payload = {"id": "1", "$ref": "url", "href": "url", "uid": "u", "name": "keep"}
        assert sanitize_payload(payload) == {"name": "keep"}

    def test_removes_empty_values(self) -> None:
        payload = {"a": "", "b": [], "c": {}, "d": None, "e": "value"}
        assert sanitize_payload(payload) == {"e": "value"}

    def test_all_empty_dict_becomes_none(self) -> None:
        assert sanitize_payload({"id": "1", "empty": ""}) is None

    def test_nested_lists_filtered(self) -> None:
        payload = {"items": [{"id": "1", "name": "keep"}, {"id": "2"}]}
        assert sanitize_payload(payload) == {"items": [{"name": "keep"}]}

    def test_scalar_passthrough(self) -> None:
        assert sanitize_payload(42) == 42


class TestFindDictsWithKeys:
    """Tests for nested dictionary search by required keys."""

    def test_finds_nested_matches(self) -> None:
        payload = {"outer": {"a": 1, "b": 2}, "list": [{"a": 3, "b": 4}]}
        matches = find_dicts_with_keys(payload, {"a", "b"})
        assert {"a": 1, "b": 2} in matches
        assert {"a": 3, "b": 4} in matches

    def test_none_payload_returns_empty(self) -> None:
        assert find_dicts_with_keys(None, {"a"}) == []

    def test_limit_is_respected(self) -> None:
        payload = [{"a": index, "b": index} for index in range(10)]
        assert len(find_dicts_with_keys(payload, {"a", "b"}, limit=3)) == 3


class TestBuildStatMap:
    """Tests for ESPN statistic normalization."""

    def test_normalizes_names_and_prefers_display_value(self) -> None:
        stats = [{"name": "Total Shots", "displayValue": "12", "value": 12}]
        assert build_stat_map(stats) == {"totalshots": "12"}

    def test_falls_back_to_value(self) -> None:
        stats = [{"abbreviation": "SOG", "value": 5}]
        assert build_stat_map(stats) == {"sog": "5"}

    def test_non_list_returns_empty(self) -> None:
        assert build_stat_map("not-a-list") == {}


class TestFirstValue:
    """Tests for alias-based statistic lookup."""

    def test_returns_first_matching_alias(self) -> None:
        stat_map = {"totalshots": "12"}
        assert first_value(stat_map, ["Total_Shots", "shots"]) == "12"

    def test_returns_default_when_no_match(self) -> None:
        assert first_value({}, ["shots"], default="none") == "none"


class TestFormatUtcDatetime:
    """Tests for ISO kickoff formatting."""

    def test_parses_zulu_timestamp(self) -> None:
        assert format_utc_datetime("2026-04-22T08:30:00Z") == "2026-04-22 08:30 UTC"

    def test_invalid_string_returned_as_is(self) -> None:
        assert format_utc_datetime("not-a-date") == "not-a-date"

    @pytest.mark.parametrize("value", [None, "", "   ", 123])
    def test_missing_or_non_string_returns_na(self, value: object) -> None:
        assert format_utc_datetime(value) == "N/A"
