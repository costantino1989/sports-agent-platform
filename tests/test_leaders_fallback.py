"""Tests for the season-leaders fallback that reads summary.leaders.

The dedicated core leaders endpoint 404s for some leagues (e.g. Chinese Super
League), but the event summary already carries a `leaders` block. When the core
payload is empty, we normalize summary.leaders into the shape the renderer
expects instead of showing "No data found".
"""

from __future__ import annotations

from src.dossier.leaders_fallback import (
    resolve_leaders_payload,
    summary_leaders_categories,
)
from src.models.dossier import EndpointPayload

_SUMMARY_LEADERS = {
    "leaders": [
        {
            "team": {"displayName": "Yunnan Yukun"},
            "leaders": [
                {
                    "name": "goalsLeaders",
                    "displayName": "Goals",
                    "leaders": [
                        {
                            "displayValue": "Matches: 16, Goals: 12",
                            "athlete": {"displayName": "Player A"},
                        }
                    ],
                }
            ],
        }
    ]
}


class TestSummaryLeadersCategories:
    def test_flattens_to_categories_with_athlete_and_team(self) -> None:
        categories = summary_leaders_categories(_SUMMARY_LEADERS)
        assert categories is not None
        assert len(categories) == 1
        category = categories[0]
        assert category["displayName"] == "Goals"
        leader = category["leaders"][0]
        assert leader["athlete"]["displayName"] == "Player A"
        # Team is propagated onto the leader so the renderer's Team column fills.
        assert leader["team"]["displayName"] == "Yunnan Yukun"

    def test_returns_none_when_no_leaders(self) -> None:
        assert summary_leaders_categories({}) is None
        assert summary_leaders_categories({"leaders": []}) is None
        assert summary_leaders_categories(None) is None
        assert summary_leaders_categories(["not", "a", "dict"]) is None


class TestResolveLeadersPayload:
    def test_keeps_core_payload_when_it_has_data(self) -> None:
        core = EndpointPayload(data={"items": [{"leaders": [{"athlete": {}}]}]})
        summary = EndpointPayload(data=_SUMMARY_LEADERS)
        assert resolve_leaders_payload(core, summary) is core

    def test_falls_back_to_summary_when_core_empty(self) -> None:
        core = EndpointPayload(data=None)
        summary = EndpointPayload(data=_SUMMARY_LEADERS)
        resolved = resolve_leaders_payload(core, summary)
        assert resolved is not core
        assert resolved.has_data()
        assert resolved.data[0]["displayName"] == "Goals"

    def test_returns_original_when_both_empty(self) -> None:
        core = EndpointPayload(data=None)
        summary = EndpointPayload(data={"boxscore": {}})
        assert resolve_leaders_payload(core, summary) is core
