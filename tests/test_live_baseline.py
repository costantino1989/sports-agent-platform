"""Tests for the deterministic in-play 1X2 baseline (score + time, Poisson)."""

from __future__ import annotations

import pytest

from src.prediction.live_baseline import (
    expected_goals,
    live_1x2_probabilities,
    over_under_probabilities,
    shrunk_rate,
)


def _sum(probs: tuple[float, float, float]) -> float:
    return probs[0] + probs[1] + probs[2]


class TestLive1x2Probabilities:
    def test_probabilities_sum_to_one(self) -> None:
        probs = live_1x2_probabilities(1, 0, 30, mu_home=1.4, mu_away=1.2)
        assert _sum(probs) == pytest.approx(1.0, abs=1e-6)

    def test_no_time_left_is_deterministic_on_current_score(self) -> None:
        # 1-0 with no minutes remaining -> home has certainly won.
        p1, px, p2 = live_1x2_probabilities(1, 0, 0, mu_home=1.4, mu_away=1.2)
        assert p1 == pytest.approx(1.0, abs=1e-9)
        assert px == pytest.approx(0.0, abs=1e-9) and p2 == pytest.approx(0.0, abs=1e-9)

    def test_level_late_game_is_mostly_draw(self) -> None:
        # 0-0 with ~2 minutes left: a draw is by far the likeliest final result.
        p1, px, p2 = live_1x2_probabilities(0, 0, 2, mu_home=1.4, mu_away=1.2)
        assert px > 0.85

    def test_big_lead_late_is_almost_certain(self) -> None:
        p1, px, p2 = live_1x2_probabilities(3, 0, 3, mu_home=1.4, mu_away=1.2)
        assert p1 > 0.98

    def test_symmetry_when_level_and_equal_rates(self) -> None:
        p1, px, p2 = live_1x2_probabilities(0, 0, 45, mu_home=1.3, mu_away=1.3)
        assert p1 == pytest.approx(p2, abs=1e-9)

    def test_more_time_helps_the_trailing_side(self) -> None:
        # Home trails 0-1. With more time left the comeback (p1) is likelier and
        # the lead holding (p2) is less certain than with little time left.
        p1_early, _, p2_early = live_1x2_probabilities(0, 1, 80, mu_home=1.4, mu_away=1.2)
        p1_late, _, p2_late = live_1x2_probabilities(0, 1, 5, mu_home=1.4, mu_away=1.2)
        assert p1_early > p1_late
        assert p2_late > p2_early

    def test_one_goal_lead_midway_is_favoured_not_certain(self) -> None:
        # 1-0 at ~65' (25 min left): home clearly favoured but far from certain.
        p1, px, p2 = live_1x2_probabilities(1, 0, 25, mu_home=1.4, mu_away=1.2)
        assert 0.6 < p1 < 0.85
        assert p2 < px  # trailing away win less likely than a draw


class TestOverUnderProbabilities:
    def test_probabilities_sum_to_one(self) -> None:
        p_over, p_under = over_under_probabilities(0, 0, 90, 1.4, 1.2, line=2.5)
        assert p_over + p_under == pytest.approx(1.0, abs=1e-9)

    def test_current_total_already_over_is_certain(self) -> None:
        # 3-0 already exceeds 2.5 regardless of remaining time.
        p_over, p_under = over_under_probabilities(3, 0, 40, 1.4, 1.2, line=2.5)
        assert p_over == pytest.approx(1.0, abs=1e-9)

    def test_level_late_is_under(self) -> None:
        # 0-0 with ~2 minutes left: almost no goals left -> Under 2.5.
        p_over, p_under = over_under_probabilities(0, 0, 2, 1.4, 1.2, line=2.5)
        assert p_under > 0.95

    def test_more_time_raises_over(self) -> None:
        early, _ = over_under_probabilities(1, 0, 80, 1.4, 1.2, line=2.5)
        late, _ = over_under_probabilities(1, 0, 10, 1.4, 1.2, line=2.5)
        assert early > late  # more time to reach 3+ goals

    def test_high_scoring_teams_raise_over(self) -> None:
        low, _ = over_under_probabilities(0, 0, 90, 0.8, 0.7, line=2.5)
        high, _ = over_under_probabilities(0, 0, 90, 2.2, 2.0, line=2.5)
        assert high > low


class TestShrunkRate:
    def test_no_games_returns_league_average(self) -> None:
        assert shrunk_rate(0, 0, league_avg=1.35, k=5) == pytest.approx(1.35)

    def test_pulls_extreme_rate_toward_league_average(self) -> None:
        # 34 goals in 13 games (2.6/game) with k=5 shrinks toward 1.35.
        rate = shrunk_rate(34, 13, league_avg=1.35, k=5)
        assert 1.35 < rate < 2.6
        assert rate == pytest.approx((34 + 1.35 * 5) / (13 + 5), abs=1e-9)

    def test_large_sample_barely_shrinks(self) -> None:
        rate = shrunk_rate(40, 40, league_avg=1.35, k=5)  # 1.0/game over 40
        assert abs(rate - 1.0) < 0.1  # close to raw rate with a big sample


class TestExpectedGoals:
    def test_average_teams_give_home_advantage_split(self) -> None:
        # Both teams league-average -> home slightly above, away at league avg.
        mu_home, mu_away = expected_goals(
            gf_home=27, ga_home=27, gp_home=20,
            gf_away=27, ga_away=27, gp_away=20,
            league_avg=1.35, home_adv=1.10, k=5,
        )
        assert mu_home == pytest.approx(1.35 * 1.10, abs=0.05)
        assert mu_away == pytest.approx(1.35, abs=0.05)

    def test_strong_attack_weak_defence_raises_expected_goals(self) -> None:
        # Strong home attack vs leaky away defence -> high home expectancy.
        mu_home, _ = expected_goals(
            gf_home=40, ga_home=10, gp_home=20,   # 2.0 scored
            gf_away=10, ga_away=40, gp_away=20,   # 2.0 conceded
            league_avg=1.35, home_adv=1.10, k=5,
        )
        assert mu_home > 2.0
