"""Tests for the betting engine: settlement, value filter, Kelly, bankroll P/L."""

from __future__ import annotations

import pytest

from src.prediction.betting import (
    BetRecord,
    capped_kelly_stake,
    is_bettable,
    kelly_fraction,
    parse_predicted_odds,
    result_from_score,
    settle_bet,
    simulate_bankroll,
)

MIN_ODDS = 1.2

_ODDS_SECTION = (
    "## 8. Odds\n"
    "1X2 odds (decimal):\n\n"
    "| Provider | Snapshot | 1 (Home) | X (Draw) | 2 (Away) |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| DraftKings | Current | 2.5 | 3.75 | 2.55 |\n"
    "| DraftKings | Open | 2.35 | 3.5 | 2.75 |\n\n"
    "## 9. Details\n"
)


class TestParsePredictedOdds:
    def test_reads_current_snapshot_for_home(self) -> None:
        assert parse_predicted_odds(_ODDS_SECTION, "1") == pytest.approx(2.5)

    def test_reads_current_snapshot_for_away(self) -> None:
        assert parse_predicted_odds(_ODDS_SECTION, "2") == pytest.approx(2.55)

    def test_reads_draw(self) -> None:
        assert parse_predicted_odds(_ODDS_SECTION, "X") == pytest.approx(3.75)

    def test_returns_none_when_no_odds(self) -> None:
        assert parse_predicted_odds("## 8. Odds\nNo data found.\n", "1") is None


class TestResultFromScore:
    @pytest.mark.parametrize(
        ("home", "away", "expected"),
        [(2, 1, "1"), (1, 1, "X"), (0, 2, "2"), (3, 0, "1")],
    )
    def test_maps_score_to_1x2(self, home: int, away: int, expected: str) -> None:
        assert result_from_score(home, away) == expected


class TestSettleBet:
    def test_won_when_pick_matches_final(self) -> None:
        assert settle_bet("1", final_home=2, final_away=1) == "won"

    def test_lost_when_pick_differs(self) -> None:
        assert settle_bet("2", final_home=2, final_away=1) == "lost"

    def test_draw_pick(self) -> None:
        assert settle_bet("X", final_home=1, final_away=1) == "won"


class TestIsBettable:
    def test_below_min_odds_not_bettable(self) -> None:
        assert is_bettable(odds=1.15, model_prob=95, min_odds=MIN_ODDS) is False

    def test_positive_edge_is_bettable(self) -> None:
        # odds 2.5 -> implied 0.40; model 0.50 -> edge > 0.
        assert is_bettable(odds=2.5, model_prob=50, min_odds=MIN_ODDS) is True

    def test_negative_edge_not_bettable(self) -> None:
        # odds 2.5 -> implied 0.40; model 0.30 -> no edge.
        assert is_bettable(odds=2.5, model_prob=30, min_odds=MIN_ODDS) is False


class TestKellyFraction:
    def test_positive_edge_fraction(self) -> None:
        # f* = (p*odds - 1)/(odds - 1) = (0.5*2.5 - 1)/1.5 = 0.1667
        assert kelly_fraction(model_prob=50, odds=2.5) == pytest.approx(0.1667, abs=1e-3)

    def test_non_positive_edge_is_zero(self) -> None:
        assert kelly_fraction(model_prob=30, odds=2.5) == 0.0

    def test_clamped_to_one(self) -> None:
        assert kelly_fraction(model_prob=99, odds=5.0) <= 1.0


class TestCappedKellyStake:
    def test_normal_stake_is_fractional_kelly(self) -> None:
        # odds 2.0, prob 60% -> full Kelly 0.2, half -> 0.10, under the 5% cap? no,
        # 0.10 > 0.05 so it caps. Use a smaller edge to stay under the cap.
        stake = capped_kelly_stake(55, 2.0, kelly_multiplier=0.5, max_fraction=0.05)
        assert stake == 0.05  # (0.55*2-1)/1=0.10 full, *0.5=0.05 -> at cap

    def test_low_odds_high_conf_is_capped(self) -> None:
        # odds 1.10, prob 95% -> big Kelly; must be clamped to the cap.
        stake = capped_kelly_stake(95, 1.10, kelly_multiplier=0.25, max_fraction=0.05)
        assert stake == 0.05

    def test_no_edge_is_zero(self) -> None:
        assert capped_kelly_stake(50, 1.10, kelly_multiplier=0.25, max_fraction=0.05) == 0.0

    def test_below_cap_passes_through(self) -> None:
        # odds 3.0, prob 40% -> full Kelly (0.4*3-1)/2=0.10, *0.25=0.025 < 0.05.
        stake = capped_kelly_stake(40, 3.0, kelly_multiplier=0.25, max_fraction=0.05)
        assert stake == pytest.approx(0.025, abs=1e-9)


class TestSimulateBankroll:
    def test_single_win_grows_balance(self) -> None:
        bets = [BetRecord(event_id="e", odds=2.0, model_prob=60, outcome="won")]
        # half-Kelly: f* = (0.6*2 -1)/1 = 0.2 -> stake 0.1*budget -> win +0.1*budget*(1)=+0.1*budget
        result = simulate_bankroll(bets, budget=100, kelly_fraction=0.5)
        assert result.start == 100
        assert result.end == pytest.approx(110.0, abs=1e-6)

    def test_single_loss_shrinks_balance(self) -> None:
        bets = [BetRecord(event_id="e", odds=2.0, model_prob=60, outcome="lost")]
        result = simulate_bankroll(bets, budget=100, kelly_fraction=0.5)
        assert result.end == pytest.approx(90.0, abs=1e-6)

    def test_sequence_compounds(self) -> None:
        bets = [
            BetRecord(event_id="a", odds=2.0, model_prob=60, outcome="won"),
            BetRecord(event_id="b", odds=2.0, model_prob=60, outcome="lost"),
        ]
        result = simulate_bankroll(bets, budget=100, kelly_fraction=0.5)
        # 100 -> 110 (win) -> stake 0.1*110=11 lost -> 99
        assert result.end == pytest.approx(99.0, abs=1e-6)

    def test_empty_bets_returns_budget(self) -> None:
        result = simulate_bankroll([], budget=50, kelly_fraction=0.5)
        assert result.end == 50 and result.roi == 0.0


class TestBankrollByBudget:
    def test_simulates_each_budget(self) -> None:
        from src.prediction.betting import bankroll_by_budget

        bets = [BetRecord(event_id="e", odds=2.0, model_prob=60, outcome="won")]
        results = bankroll_by_budget(bets, budgets=[10, 100], kelly_fraction=0.5)
        assert set(results) == {10, 100}
        assert results[10].end == pytest.approx(11.0, abs=1e-6)
        assert results[100].end == pytest.approx(110.0, abs=1e-6)


class TestFlatBankroll:
    """Flat-stake simulation for synthetic bets (Kelly rejects their low odds)."""

    def test_win_adds_flat_stake_times_net_odds(self) -> None:
        from src.prediction.betting import simulate_flat_bankroll

        bets = [BetRecord(event_id="e", odds=1.2, model_prob=70, outcome="won")]
        result = simulate_flat_bankroll(bets, budget=100, stake_fraction=0.02)
        # stake 2, win at 1.2 -> +2*0.2 = +0.4
        assert result.end == pytest.approx(100.4, abs=1e-6)

    def test_loss_subtracts_full_flat_stake(self) -> None:
        from src.prediction.betting import simulate_flat_bankroll

        bets = [BetRecord(event_id="e", odds=1.2, model_prob=70, outcome="lost")]
        result = simulate_flat_bankroll(bets, budget=100, stake_fraction=0.02)
        assert result.end == pytest.approx(98.0, abs=1e-6)

    def test_low_odds_high_loss_rate_bleeds(self) -> None:
        # Three 1.2 picks, 2 lost 1 won: asymmetric payoff bleeds the bankroll.
        from src.prediction.betting import simulate_flat_bankroll

        bets = [
            BetRecord(event_id="a", odds=1.2, model_prob=65, outcome="won"),
            BetRecord(event_id="b", odds=1.2, model_prob=65, outcome="lost"),
            BetRecord(event_id="c", odds=1.2, model_prob=65, outcome="lost"),
        ]
        result = simulate_flat_bankroll(bets, budget=100, stake_fraction=0.10)
        # 100 -> +10*0.2=102 -> -10.2=91.8 -> -9.18=82.62
        assert result.end == pytest.approx(82.62, abs=1e-6)
        assert result.roi < 0

    def test_flat_bankroll_by_budget(self) -> None:
        from src.prediction.betting import flat_bankroll_by_budget

        bets = [BetRecord(event_id="e", odds=1.2, model_prob=70, outcome="won")]
        results = flat_bankroll_by_budget(bets, budgets=[100, 1000], stake_fraction=0.02)
        assert set(results) == {100, 1000}
        assert results[100].end == pytest.approx(100.4, abs=1e-6)
        assert results[1000].end == pytest.approx(1004.0, abs=1e-6)
