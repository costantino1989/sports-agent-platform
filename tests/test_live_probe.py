"""Tests for parsing a cheap live match state from an ESPN summary payload."""

from __future__ import annotations

from src.prediction.live_decision import MatchState
from src.prediction.live_probe import parse_match_state


def _summary(*, home, away, state, detail, reds=(0, 0)) -> dict:
    return {
        "header": {
            "competitions": [
                {
                    "status": {"type": {"state": state, "completed": state == "post", "detail": detail}},
                    "competitors": [
                        {"homeAway": "home", "score": home},
                        {"homeAway": "away", "score": away},
                    ],
                }
            ]
        },
        "boxscore": {
            "teams": [
                {"statistics": [{"name": "redCards", "displayValue": str(reds[0])}]},
                {"statistics": [{"name": "redCards", "displayValue": str(reds[1])}]},
            ]
        },
    }


class TestParseMatchState:
    def test_live_match(self) -> None:
        state = parse_match_state(_summary(home="1", away="0", state="in", detail="23'"))
        assert state == MatchState(home_score=1, away_score=0, red_cards=0, minute=23, finished=False)

    def test_finished_match(self) -> None:
        state = parse_match_state(_summary(home=2, away=1, state="post", detail="FT"))
        assert state.finished is True
        assert (state.home_score, state.away_score) == (2, 1)

    def test_red_cards_summed_across_teams(self) -> None:
        state = parse_match_state(_summary(home="0", away="0", state="in", detail="61'", reds=(1, 1)))
        assert state.red_cards == 2

    def test_minute_extracted_from_detail(self) -> None:
        state = parse_match_state(_summary(home="0", away="0", state="in", detail="45'+2"))
        assert state.minute == 45

    def test_returns_none_without_competitors(self) -> None:
        assert parse_match_state({"header": {"competitions": [{}]}}) is None

    def test_returns_none_on_garbage(self) -> None:
        assert parse_match_state({}) is None
        assert parse_match_state({"header": {}}) is None
