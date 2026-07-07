"""Tests that the dossier's section-1 snapshot reflects the live summary.

Regression: the snapshot used to render score/status from the match record
persisted at sync time (pre-match: 0-0 / Scheduled), contradicting the live
play-by-play in section 6 and depressing the model's confidence.
"""

from __future__ import annotations

from pathlib import Path

from src.dossier.render import MatchMarkdownRenderer, extract_live_snapshot
from src.dossier.render_tools import prematch_odds_note
from src.models.dossier import EndpointPayload, MatchDossierData
from src.models.live_models import (
    ApiReferencesModel,
    CompetitionModel,
    EventModel,
    LeagueModel,
    MatchRecordModel,
    TeamIdentifiersModel,
    TeamModel,
)

# A live summary header: away leads 0-2 at minute 20, match in progress.
_LIVE_SUMMARY = {
    "header": {
        "competitions": [
            {
                "status": {
                    "type": {
                        "state": "in",
                        "description": "1st Half",
                        "detail": "20'",
                        "completed": False,
                    }
                },
                "competitors": [
                    {"homeAway": "home", "score": "0",
                     "team": {"id": "17361", "displayName": "Tampa Bay Rowdies"}},
                    {"homeAway": "away", "score": "2",
                     "team": {"id": "21822", "displayName": "Lexington"}},
                ],
            }
        ]
    }
}


class TestExtractLiveSnapshot:
    def test_reads_competitors_and_status_from_header(self) -> None:
        competitors, status_type = extract_live_snapshot(_LIVE_SUMMARY)
        by_name = {c["team_name"]: c for c in competitors}
        assert by_name["Lexington"]["score"] == "2"
        assert by_name["Lexington"]["side"] == "away"
        assert by_name["Tampa Bay Rowdies"]["team_id"] == "17361"
        assert status_type["detail"] == "20'"

    def test_missing_header_returns_empty(self) -> None:
        assert extract_live_snapshot({}) == ([], None)
        assert extract_live_snapshot(None) == ([], None)

    def test_prematch_without_scores_yields_no_competitors(self) -> None:
        payload = {"header": {"competitions": [{"competitors": [{"homeAway": "home"}]}]}}
        competitors, _ = extract_live_snapshot(payload)
        assert competitors == []


def _match_record() -> MatchRecordModel:
    # Stale sync-time record: Scheduled, 0-0, and side is None (as stored by the
    # weekly sync), so live scores must be matched by team id/name, not side.
    return MatchRecordModel(
        league=LeagueModel(slug="usa.usl.1", name="USL Championship"),
        event=EventModel(
            id="e1",
            name="Lexington at Tampa Bay Rowdies",
            status={"type": {"description": "Scheduled", "detail": "Scheduled"}},
        ),
        competition=CompetitionModel(id="c1"),
        teams=[
            TeamIdentifiersModel(
                team=TeamModel(id="17361", displayName="Tampa Bay Rowdies"), score="0"
            ),
            TeamIdentifiersModel(
                team=TeamModel(id="21822", displayName="Lexington"), score="0"
            ),
        ],
        api_refs=ApiReferencesModel(summary="s", core_competition="c"),
    )


def _dossier_data(summary_data) -> MatchDossierData:
    empty = EndpointPayload(data=None)
    return MatchDossierData(
        match=_match_record(),
        output_path=Path("x.md"),
        summary=EndpointPayload(data=summary_data),
        core_event=empty,
        core_competition=empty,
        plays=empty,
        situation=empty,
        probabilities=empty,
        odds=empty,
        standings=empty,
        leaders=empty,
        rankings=empty,
        news=empty,
        teams=[],
        head_to_head=[],
    )


class TestSnapshotUsesLiveSummary:
    def test_live_score_overrides_stale_record(self) -> None:
        snapshot = MatchMarkdownRenderer._render_match_snapshot(_dossier_data(_LIVE_SUMMARY))
        assert "Tampa Bay Rowdies 0 - Lexington 2" in snapshot
        assert "0 - Lexington 0" not in snapshot  # no longer the stale 0-0
        assert "Scheduled" not in snapshot         # live status shown instead
        assert "Away" in snapshot                  # side recovered from live feed

    def test_falls_back_to_record_when_no_live_summary(self) -> None:
        snapshot = MatchMarkdownRenderer._render_match_snapshot(_dossier_data(None))
        assert "Tampa Bay Rowdies 0 - Lexington 0" in snapshot
        assert "Scheduled" in snapshot


class TestPrematchOddsNote:
    def test_warns_when_match_is_live(self) -> None:
        note = prematch_odds_note(_LIVE_SUMMARY)
        assert "PRE-MATCH" in note
        assert "0 - Lexington 2" in note  # live score echoed so the model sees it
        assert "20'" in note

    def test_no_note_before_kickoff(self) -> None:
        prematch = {
            "header": {"competitions": [{"status": {"type": {"state": "pre"}},
                                         "competitors": []}]}
        }
        assert prematch_odds_note(prematch) == ""

    def test_no_note_when_no_summary(self) -> None:
        assert prematch_odds_note(None) == ""
