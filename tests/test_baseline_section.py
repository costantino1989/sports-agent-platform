"""Tests for the dossier's statistical 1X2 baseline section."""

from __future__ import annotations

from pathlib import Path

from src.dossier.baseline_section import render_baseline_section
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


def _standings(home: str, away: str) -> dict:
    def entry(name: str, gf: int, ga: int, gp: int) -> dict:
        return {
            "team": {"displayName": name},
            "stats": [
                {"name": "pointsFor", "value": gf},
                {"name": "pointsAgainst", "value": ga},
                {"name": "gamesPlayed", "value": gp},
            ],
        }

    return {
        "entries": [
            entry(home, 30, 12, 15),
            entry(away, 14, 25, 15),
            entry("Filler FC", 20, 20, 15),
        ]
    }


def _summary(home: str, away: str, home_score: int, away_score: int, detail: str) -> dict:
    return {
        "header": {
            "competitions": [
                {
                    "status": {"type": {"state": "in", "detail": detail, "completed": False}},
                    "competitors": [
                        {"homeAway": "home", "score": str(home_score),
                         "team": {"id": "1", "displayName": home}},
                        {"homeAway": "away", "score": str(away_score),
                         "team": {"id": "2", "displayName": away}},
                    ],
                }
            ]
        }
    }


def _data(summary_data, standings_data, plays_data=None) -> MatchDossierData:
    empty = EndpointPayload(data=None)
    record = MatchRecordModel(
        league=LeagueModel(slug="usa.usl.1", name="USL Championship"),
        event=EventModel(id="e1", name="Away at Home"),
        competition=CompetitionModel(id="c1"),
        teams=[
            TeamIdentifiersModel(team=TeamModel(id="1", displayName="Home City"), score="0"),
            TeamIdentifiersModel(team=TeamModel(id="2", displayName="Away Town"), score="0"),
        ],
        api_refs=ApiReferencesModel(summary="s", core_competition="c"),
    )
    return MatchDossierData(
        match=record, output_path=Path("x.md"),
        summary=EndpointPayload(data=summary_data),
        core_event=empty, core_competition=empty,
        plays=EndpointPayload(data=plays_data), situation=empty,
        probabilities=empty, odds=empty,
        standings=EndpointPayload(data=standings_data),
        leaders=empty, rankings=empty, news=empty, teams=[], head_to_head=[],
    )


def _prob(section: str, code: str) -> int:
    # Row like "| 1 (Home City casa) | 83% |"
    for line in section.splitlines():
        if line.startswith(f"| {code} "):
            return int(line.rsplit("|", 2)[1].strip().rstrip("%"))
    raise AssertionError(f"no row for {code} in:\n{section}")


class TestRenderBaselineSection:
    def test_leading_home_late_is_favoured(self) -> None:
        data = _data(_summary("Home City", "Away Town", 1, 0, "80'"),
                     _standings("Home City", "Away Town"))
        section = render_baseline_section(data)
        p1, px, p2 = _prob(section, "1"), _prob(section, "X"), _prob(section, "2")
        assert p1 > px > p2                       # leader favoured, then draw
        assert 95 <= p1 + px + p2 <= 105          # ~100% (rounding)
        assert "μ casa" in section

    def test_includes_over_under_baseline(self) -> None:
        # 1-0 at 80': few minutes left -> Under 2.5 should dominate Over 2.5.
        data = _data(_summary("Home City", "Away Town", 1, 0, "80'"),
                     _standings("Home City", "Away Town"))
        section = render_baseline_section(data)
        assert "Under/Over" in section
        assert "2.5" in section
        # Parse the 2.5 row: "| 2.5 | <under>% | <over>% |"
        for row in section.splitlines():
            if row.startswith("| 2.5 "):
                cells = [c.strip().rstrip("%") for c in row.split("|") if c.strip()]
                under, over = int(cells[1]), int(cells[2])
                assert under > over  # late, level-ish -> Under likelier
                break
        else:
            raise AssertionError("no 2.5 O/U row")

    def test_team_specific_mu_when_standings_present(self) -> None:
        data = _data(_summary("Home City", "Away Town", 0, 0, "10'"),
                     _standings("Home City", "Away Town"))
        section = render_baseline_section(data)
        assert "default" not in section           # real standings -> team-specific

    def test_default_mu_without_standings(self) -> None:
        data = _data(_summary("Home City", "Away Town", 0, 0, "10'"), None)
        section = render_baseline_section(data)
        assert "default" in section               # falls back, still renders
        assert "| 1 " in section

    def test_prematch_uses_full_ninety_minutes(self) -> None:
        # No live header -> pre-match: 0-0 with 90 minutes remaining.
        data = _data(None, _standings("Home City", "Away Town"))
        section = render_baseline_section(data)
        assert "pre-partita" in section
        assert "punteggio 0-0" in section

    def test_play_by_play_score_overrides_lagging_header(self) -> None:
        # Header still says 0-0 at 4', but the play-by-play already has an away
        # goal (0-1) at 5'. The baseline must use the fresher play-by-play score.
        plays = {"items": [
            {"scoringPlay": True, "homeScore": 0, "awayScore": 1,
             "clock": {"displayValue": "5'"}},
        ]}
        stale = _data(_summary("Home City", "Away Town", 0, 0, "4'"),
                      _standings("Home City", "Away Town"), plays_data=plays)
        section = render_baseline_section(stale)
        assert "punteggio 0-1" in section
        # Away now leads, so its baseline must beat the 0-0 case.
        level = _data(_summary("Home City", "Away Town", 0, 0, "4'"),
                      _standings("Home City", "Away Town"))
        assert _prob(section, "2") > _prob(render_baseline_section(level), "2")
