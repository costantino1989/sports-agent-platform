"""Tests for compacting the dossier passed to the prediction model.

The full play-by-play in section 6 can be hundreds of rows and balloons the
prompt (slow / timeouts). We keep every section but trim section 6's table to
the most recent events. Everything else is left untouched.
"""

from __future__ import annotations

from src.prediction.prompt_compact import (
    compact_dossier_for_model,
    has_play_by_play,
    has_team_statistics,
)


def _dossier(play_rows: int) -> str:
    rows = "\n".join(
        f"| {i}' | TeamA | Pass at {i}' | General play update |" for i in range(1, play_rows + 1)
    )
    return (
        "## 1. Live match snapshot\n- Match: A vs B\n- Scoreline: A 0 - B 0\n\n"
        "## 6. Current live statistics\nFull play-by-play:\n\n"
        "| Minute | Team | Event | Impact |\n| --- | --- | --- | --- |\n"
        f"{rows}\n\n"
        "## 10. League standings\n| Team | Pts |\n| --- | --- |\n| A | 40 |\n"
    )


class TestCompactDossier:
    def test_trims_play_by_play_to_recent_events(self) -> None:
        out = compact_dossier_for_model(_dossier(play_rows=120), max_events=15)
        # Section 6 table data rows kept <= 15.
        section6 = out.split("## 6.")[1].split("## 10.")[0]
        data_rows = [ln for ln in section6.splitlines() if ln.startswith("| ") and "'" in ln]
        assert len(data_rows) <= 15
        # Most recent event (120') is kept; an early one (2') is dropped.
        assert "120'" in section6
        assert "| 2' |" not in section6

    def test_leaves_other_sections_untouched(self) -> None:
        out = compact_dossier_for_model(_dossier(play_rows=120), max_events=15)
        assert "## 1. Live match snapshot" in out
        assert "| A | 40 |" in out  # standings row intact
        assert "Scoreline: A 0 - B 0" in out

    def test_notes_how_many_events_were_hidden(self) -> None:
        out = compact_dossier_for_model(_dossier(play_rows=120), max_events=15)
        assert "120" in out  # total count surfaced in the truncation note

    def test_short_play_by_play_is_unchanged(self) -> None:
        original = _dossier(play_rows=5)
        assert compact_dossier_for_model(original, max_events=15) == original

    def test_has_play_by_play_true_with_events(self) -> None:
        assert has_play_by_play(_dossier(play_rows=5)) is True

    def test_has_play_by_play_false_when_no_data(self) -> None:
        text = (
            "## 6. Current live statistics\n"
            "No data found (source: ESPN API, section: Current live statistics).\n\n"
            "## 7. News\n"
        )
        assert has_play_by_play(text) is False

    def test_has_play_by_play_false_with_header_only(self) -> None:
        text = (
            "## 6. Current live statistics\n"
            "| Minute | Team | Event | Impact |\n| --- | --- | --- | --- |\n\n"
            "## 7. News\n"
        )
        assert has_play_by_play(text) is False

    def test_no_data_section_is_unchanged(self) -> None:
        text = (
            "## 6. Current live statistics\n"
            "No data found (source: ESPN API, section: Current live statistics).\n\n"
            "## 10. League standings\n| A | 40 |\n"
        )
        assert compact_dossier_for_model(text, max_events=15) == text


class TestHasTeamStatistics:
    _WITH_STATS = (
        "## 4. Team statistics\n"
        "| Metric | Home | Away |\n| --- | --- | --- |\n"
        "| Possession Pct | 62.0 | 38.0 |\n| Total Shots | 9 | 3 |\n\n"
        "## 5. Head-to-head\n"
    )

    def test_true_when_section_4_has_numeric_stats(self) -> None:
        assert has_team_statistics(self._WITH_STATS) is True

    def test_false_when_section_4_missing(self) -> None:
        assert has_team_statistics("## 6. Current live statistics\n| a |\n") is False

    def test_false_when_section_4_says_no_data(self) -> None:
        text = (
            "## 4. Team statistics\n"
            "No data found (source: ESPN API, section: Team statistics).\n\n"
            "## 5. Head-to-head\n"
        )
        assert has_team_statistics(text) is False


class TestOddsHiddenFromModel:
    _WITH_ODDS = (
        "## 1. Live match snapshot\n- Match: A vs B\n\n"
        "## 8. Odds\n"
        "| Provider | Snapshot | 1 (Home) | X (Draw) | 2 (Away) |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Betfair | Current | 1.80 | 3.50 | 4.20 |\n\n"
        "## 9. News\n- Nothing notable.\n"
    )

    def test_removes_odds_section_from_model_prompt(self) -> None:
        # The model must not see the odds (avoids anchoring to the market); it
        # predicts on stats + play-by-play. The file on disk keeps the odds.
        out = compact_dossier_for_model(self._WITH_ODDS, max_events=15)
        assert "## 8. Odds" not in out
        assert "Betfair" not in out
        assert "4.20" not in out

    def test_keeps_sections_around_the_odds(self) -> None:
        out = compact_dossier_for_model(self._WITH_ODDS, max_events=15)
        assert "## 1. Live match snapshot" in out
        assert "## 9. News" in out
        assert "Nothing notable." in out
