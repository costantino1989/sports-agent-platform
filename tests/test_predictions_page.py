"""Tests for the predictions-page data builder (cards)."""

from __future__ import annotations

from src.prediction.predictions_page import build_predictions_data
from src.schedule.repositories.prediction_repo import PredictionRow


def _pred(event_id, result="2", prob=73, hs=0, as_=1, minute=80, status="live",
          rationale="", evidence=None, ou_result=None, ou_line=None, ou_prob=None):
    return PredictionRow(
        event_id=event_id, predicted_result=result, success_probability=prob,
        home_score=hs, away_score=as_, minute=minute, status=status,
        updated_at="2026-07-05T22:00:00+00:00",
        rationale=rationale, evidence=evidence or [],
        over_under_result=ou_result, over_under_line=ou_line,
        over_under_probability=ou_prob,
    )


_META = {
    "e1": {"league_slug": "chn.1", "league_name": "Chinese Super League",
           "home": "Qingdao", "away": "Chengdu", "kickoff_utc": "2026-07-05T13:00:00+02:00"},
    "e2": {"league_slug": "fifa.world", "league_name": "World Cup",
           "home": "Brazil", "away": "Norway", "kickoff_utc": "2026-07-05T22:00:00+02:00"},
}


class TestBuildPredictionsData:
    def test_builds_card_with_fields(self) -> None:
        cards = build_predictions_data([_pred("e1")], _META, {})
        card = cards[0]
        assert card["home"] == "Qingdao" and card["away"] == "Chengdu"
        assert card["predicted"] == "2" and card["probability"] == 73
        assert (card["scoreHome"], card["scoreAway"], card["minute"]) == (0, 1, 80)
        assert card["leagueSlug"] == "chn.1"

    def test_excludes_predictions_without_match_meta(self) -> None:
        cards = build_predictions_data([_pred("unknown")], _META, {})
        assert cards == []

    def test_sorted_by_kickoff_most_recent_first(self) -> None:
        # Closest/most recent kickoff first (descending): e2 (22:00) before e1 (13:00).
        cards = build_predictions_data([_pred("e1"), _pred("e2")], _META, {})
        assert [c["eventId"] for c in cards] == ["e2", "e1"]

    def test_rationale_from_bet_when_present(self) -> None:
        bets = {"e1": {"rationale": "Chengdu dominating", "evidence": ["shots 12-3"]}}
        card = build_predictions_data([_pred("e1")], _META, bets)[0]
        assert card["rationale"] == "Chengdu dominating"
        assert card["evidence"] == ["shots 12-3"]

    def test_no_rationale_defaults_empty(self) -> None:
        card = build_predictions_data([_pred("e1")], _META, {})[0]
        assert card["rationale"] == "" and card["evidence"] == []

    def test_rationale_from_prediction_when_no_bet(self) -> None:
        # The reasoning is now shown even without a locked bet.
        pred = _pred("e1", rationale="Away side pressing hard.", evidence=["sec:6"])
        card = build_predictions_data([pred], _META, {})[0]
        assert card["rationale"] == "Away side pressing hard."
        assert card["evidence"] == ["sec:6"]

    def test_prediction_rationale_preferred_over_bet(self) -> None:
        # The prediction's own (most current) reasoning wins over an older bet's.
        pred = _pred("e1", rationale="Current reasoning.", evidence=["sec:9"])
        bets = {"e1": {"rationale": "Old bet reasoning.", "evidence": ["sec:1"]}}
        card = build_predictions_data([pred], _META, bets)[0]
        assert card["rationale"] == "Current reasoning."
        assert card["evidence"] == ["sec:9"]

    def test_excludes_model_failure_fallback_x_50(self) -> None:
        # X at exactly 50% is the model-failure fallback (no credits) — hide it.
        preds = [_pred("e1", result="X", prob=50), _pred("e2", result="2", prob=73)]
        cards = build_predictions_data(preds, _META, {})
        assert [c["eventId"] for c in cards] == ["e2"]

    def test_keeps_genuine_draw_prediction(self) -> None:
        # A real draw call (not exactly 50%) is kept.
        card = build_predictions_data([_pred("e1", result="X", prob=58)], _META, {})[0]
        assert card["predicted"] == "X" and card["probability"] == 58

    def test_outcome_pending_while_match_not_finished(self) -> None:
        card = build_predictions_data([_pred("e1", status="live")], _META, {})[0]
        assert card["outcome"] == "pending"

    def test_outcome_won_when_finished_score_matches_pick(self) -> None:
        # Picked away ("2"); finished 0-2 (away win) -> won.
        pred = _pred("e1", result="2", hs=0, as_=2, status="done")
        card = build_predictions_data([pred], _META, {})[0]
        assert card["outcome"] == "won"

    def test_outcome_lost_when_finished_score_contradicts_pick(self) -> None:
        # Picked away ("2"); finished 2-1 (home win) -> lost.
        pred = _pred("e1", result="2", hs=2, as_=1, status="done")
        card = build_predictions_data([pred], _META, {})[0]
        assert card["outcome"] == "lost"

    def test_outcome_won_for_correct_draw_pick(self) -> None:
        pred = _pred("e1", result="X", prob=58, hs=1, as_=1, status="done")
        card = build_predictions_data([pred], _META, {})[0]
        assert card["outcome"] == "won"

    def test_over_under_fields_exposed(self) -> None:
        pred = _pred("e1", ou_result="Over", ou_line=2.5, ou_prob=64)
        card = build_predictions_data([pred], _META, {})[0]
        assert card["overUnder"] == "Over"
        assert card["overUnderLine"] == 2.5
        assert card["overUnderProbability"] == 64

    def test_over_under_absent_is_none(self) -> None:
        card = build_predictions_data([_pred("e1")], _META, {})[0]
        assert card["overUnder"] is None

    def test_over_under_outcome_won_when_finished(self) -> None:
        # Finished 2-2 (total 4 > 2.5), pick Over -> won.
        pred = _pred("e1", hs=2, as_=2, status="done", ou_result="Over", ou_line=2.5, ou_prob=60)
        card = build_predictions_data([pred], _META, {})[0]
        assert card["overUnderOutcome"] == "won"

    def test_over_under_outcome_lost_when_finished(self) -> None:
        # Finished 1-0 (total 1 < 2.5), pick Over -> lost.
        pred = _pred("e1", hs=1, as_=0, status="done", ou_result="Over", ou_line=2.5, ou_prob=60)
        card = build_predictions_data([pred], _META, {})[0]
        assert card["overUnderOutcome"] == "lost"

    def test_over_under_outcome_pending_while_live(self) -> None:
        pred = _pred("e1", status="live", ou_result="Under", ou_line=2.5, ou_prob=60)
        card = build_predictions_data([pred], _META, {})[0]
        assert card["overUnderOutcome"] == "pending"

    def test_settled_bet_outcome_overrides_score_derivation(self) -> None:
        # A settled bet is authoritative even if the prediction row still reads
        # "live" (e.g. it was settled via the stale-bet path, status not flipped).
        pred = _pred("e1", result="2", hs=0, as_=1, status="live")
        bets = {"e1": {"rationale": "", "evidence": [], "outcome": "won"}}
        card = build_predictions_data([pred], _META, bets)[0]
        assert card["outcome"] == "won"
