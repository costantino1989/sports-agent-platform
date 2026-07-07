"""Tests for enriching a dossier's section 6 from API-Football events."""

from __future__ import annotations

from src.dossier.events_fallback import enrich_play_by_play
from src.prediction.prompt_compact import has_play_by_play

_EVENTS = [
    {"minute": 12, "team": "Emelec", "type": "Goal", "detail": "Normal Goal", "player": "J. Perez"},
    {"minute": 55, "team": "Delfín", "type": "Card", "detail": "Yellow Card", "player": "R. Diaz"},
]

_DOSSIER_EMPTY_S6 = (
    "## 5. Head-to-head\nx\n\n"
    "## 6. Current live statistics\n"
    "Full play-by-play:\n\n"
    "| Minute | Team | Event | Impact |\n"
    "| --- | --- | --- | --- |\n\n"
    "## 7. News\ny\n"
)


class TestEnrichPlayByPlay:
    def test_no_events_leaves_markdown_unchanged(self) -> None:
        assert enrich_play_by_play(_DOSSIER_EMPTY_S6, []) == _DOSSIER_EMPTY_S6

    def test_injects_events_and_passes_coverage_check(self) -> None:
        before = has_play_by_play(_DOSSIER_EMPTY_S6)
        merged = enrich_play_by_play(_DOSSIER_EMPTY_S6, _EVENTS)
        assert before is False           # ESPN section 6 was empty
        assert has_play_by_play(merged) is True   # now it has events
        assert "Emelec" in merged and "12'" in merged
        assert "Goal" in merged
        # Other sections preserved.
        assert "## 5. Head-to-head" in merged and "## 7. News" in merged

    def test_inserts_section6_when_absent(self) -> None:
        no_s6 = "## 5. H2H\nx\n\n## 7. News\ny\n"
        merged = enrich_play_by_play(no_s6, _EVENTS)
        assert has_play_by_play(merged) is True
        assert merged.index("## 6.") < merged.index("## 7.")  # placed before 7
