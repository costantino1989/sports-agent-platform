"""Tests for the live-prediction skip/re-evaluate decision.

A confident prediction (>= threshold) is not recomputed every cycle. It is
re-evaluated only when the scoreline moves against the pick, a red card appears,
or a bounded number of skip cycles have elapsed (safety net).
"""

from __future__ import annotations

from src.prediction.live_decision import (
    LastPrediction,
    MatchState,
    PredictionAction,
    decide_action,
    should_lock,
)

FORCE_EVERY = 6


def _last(**kw) -> LastPrediction:
    defaults = dict(
        predicted_result="1",
        success_probability=85,
        home_score=1,
        away_score=0,
        red_cards=0,
        cycles_since_full=0,
    )
    defaults.update(kw)
    return LastPrediction(**defaults)


def _state(**kw) -> MatchState:
    defaults = dict(home_score=1, away_score=0, red_cards=0, minute=30, finished=False)
    defaults.update(kw)
    return MatchState(**defaults)


def _decide(last, state):
    return decide_action(last=last, current=state, force_refresh_every=FORCE_EVERY)


class TestDecideAction:
    def test_no_prior_prediction_predicts(self) -> None:
        action, _ = decide_action(
            last=None, current=_state(), force_refresh_every=FORCE_EVERY
        )
        assert action is PredictionAction.PREDICT

    def test_low_confidence_but_stable_skips(self) -> None:
        # Below-threshold matches are NOT re-predicted every cycle; only on
        # material change or the periodic force-refresh.
        action, reason = _decide(_last(success_probability=64), _state())
        assert action is PredictionAction.SKIP
        assert reason == "stable"

    def test_stable_match_skips(self) -> None:
        action, reason = _decide(_last(), _state())
        assert action is PredictionAction.SKIP
        assert reason == "stable"

    def test_goal_for_the_pick_still_skips(self) -> None:
        # Pick is home ("1"); home scores again -> reinforces, no re-eval.
        action, _ = _decide(_last(predicted_result="1"), _state(home_score=2))
        assert action is PredictionAction.SKIP

    def test_goal_against_home_pick_reevaluates(self) -> None:
        action, reason = _decide(_last(predicted_result="1"), _state(away_score=1))
        assert action is PredictionAction.PREDICT
        assert reason == "material_change"

    def test_goal_against_away_pick_reevaluates(self) -> None:
        action, reason = _decide(
            _last(predicted_result="2", home_score=0, away_score=1),
            _state(home_score=1, away_score=1),
        )
        assert action is PredictionAction.PREDICT
        assert reason == "material_change"

    def test_any_goal_breaks_a_draw_pick(self) -> None:
        action, reason = _decide(
            _last(predicted_result="X", home_score=0, away_score=0),
            _state(home_score=1, away_score=0),
        )
        assert action is PredictionAction.PREDICT
        assert reason == "material_change"

    def test_new_red_card_reevaluates(self) -> None:
        action, reason = _decide(_last(red_cards=0), _state(red_cards=1))
        assert action is PredictionAction.PREDICT
        assert reason == "material_change"

    def test_forced_refresh_after_enough_cycles(self) -> None:
        # 5 prior skip cycles + this one reaches the limit of 6 -> force.
        action, reason = _decide(_last(cycles_since_full=5), _state())
        assert action is PredictionAction.PREDICT
        assert reason == "forced_refresh"

    def test_finished_match_is_not_predicted(self) -> None:
        action, reason = _decide(_last(), _state(finished=True))
        assert action is PredictionAction.DONE
        assert reason == "match_finished"


class TestShouldLock:
    def test_locks_at_or_above_confidence(self) -> None:
        assert should_lock(80, 80) is True
        assert should_lock(92, 80) is True

    def test_does_not_lock_below_confidence(self) -> None:
        assert should_lock(79, 80) is False


class TestShouldLockBet:
    def test_locks_on_high_confidence(self) -> None:
        from src.prediction.live_decision import should_lock_bet

        assert should_lock_bet(model_prob=85, odds=2.5, lock_confidence=80, lock_odds=1.25) is True

    def test_locks_when_odds_near_floor(self) -> None:
        from src.prediction.live_decision import should_lock_bet

        # Low confidence, but odds collapsed near 1.2 -> outcome nearly decided.
        assert should_lock_bet(model_prob=60, odds=1.2, lock_confidence=80, lock_odds=1.25) is True

    def test_does_not_lock_when_neither(self) -> None:
        from src.prediction.live_decision import should_lock_bet

        assert should_lock_bet(model_prob=60, odds=2.5, lock_confidence=80, lock_odds=1.25) is False

    def test_missing_odds_falls_back_to_confidence(self) -> None:
        from src.prediction.live_decision import should_lock_bet

        assert should_lock_bet(model_prob=60, odds=None, lock_confidence=80, lock_odds=1.25) is False
        assert should_lock_bet(model_prob=90, odds=None, lock_confidence=80, lock_odds=1.25) is True


class TestRequiredConfidence:
    def _rc(self, minute):
        from src.prediction.live_decision import required_confidence
        return required_confidence(minute, base_confidence=80)

    def test_full_confidence_before_60(self) -> None:
        assert self._rc(0) == 80 and self._rc(45) == 80 and self._rc(59) == 80

    def test_minus_10_between_60_and_75(self) -> None:
        assert self._rc(60) == 70 and self._rc(70) == 70 and self._rc(74) == 70

    def test_minus_20_from_75(self) -> None:
        assert self._rc(75) == 60 and self._rc(88) == 60

    def test_scales_with_base(self) -> None:
        from src.prediction.live_decision import required_confidence
        assert required_confidence(80, base_confidence=90) == 70  # 90 - 20
