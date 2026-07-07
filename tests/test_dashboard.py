"""Tests for building dashboard data (cards + P/L) from persisted bets."""

from __future__ import annotations

from src.prediction.dashboard import build_dashboard_data
from src.schedule.repositories.bet_repo import Bet


def _bet(**kw) -> Bet:
    defaults = dict(
        event_id="e", predicted_result="1", model_prob=90, odds=1.8,
        locked_minute=20, final_home=None, final_away=None, outcome=None, settled=False,
    )
    defaults.update(kw)
    return Bet(**defaults)


META = {
    "won1": {"league_slug": "eng.1", "league_name": "PL", "home": "City", "away": "Luton", "kickoff_utc": "2026-07-03T14:30:00Z"},
    "lost1": {"league_slug": "ita.1", "league_name": "Serie A", "home": "Napoli", "away": "Roma", "kickoff_utc": "2026-07-03T18:00:00Z"},
    "void1": {"league_slug": "irl.1", "league_name": "LOI", "home": "A", "away": "B", "kickoff_utc": "2026-07-03T19:45:00Z"},
}


class TestBuildDashboardData:
    def test_settled_bets_get_won_lost_status(self) -> None:
        bets = [
            _bet(event_id="won1", predicted_result="1", odds=1.8, model_prob=90, settled=True, outcome="won", final_home=2, final_away=0),
            _bet(event_id="lost1", predicted_result="2", odds=2.3, model_prob=82, settled=True, outcome="lost", final_home=2, final_away=1),
        ]
        data = build_dashboard_data(bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2)
        by_id = {m["leagueSlug"]: m for m in data["matches"]}
        assert by_id["eng.1"]["status"] == "won"
        assert by_id["eng.1"]["finalHome"] == 2
        assert by_id["ita.1"]["status"] == "lost"

    def test_pending_locked_bet_is_pending(self) -> None:
        bets = [_bet(event_id="won1", settled=False)]
        data = build_dashboard_data(bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2)
        assert data["matches"][0]["status"] == "pending"

    def test_card_exposes_locked_minute(self) -> None:
        bets = [_bet(event_id="won1", locked_minute=77)]
        data = build_dashboard_data(bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2)
        assert data["matches"][0]["lockedMinute"] == 77

    def test_card_exposes_bookmaker(self) -> None:
        bets = [_bet(event_id="won1", bookmaker="Betfair Exchange")]
        data = build_dashboard_data(bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2)
        assert data["matches"][0]["bookmaker"] == "Betfair Exchange"

    def test_card_exposes_stake_pct_for_bettable(self) -> None:
        # odds 2.0, prob 60% -> full Kelly 0.2, half-Kelly -> 10% of bankroll.
        bets = [_bet(event_id="won1", odds=2.0, model_prob=60)]
        data = build_dashboard_data(bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2)
        assert data["matches"][0]["stakePct"] == 10.0

    def test_no_stake_bet_excluded_from_dashboard(self) -> None:
        # Locked-but-no-stake (odds below floor) must not appear on the betting
        # dashboard — only real staked bets do.
        bets = [_bet(event_id="void1", odds=1.14, model_prob=70)]
        data = build_dashboard_data(bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2)
        assert data["matches"] == []

    def test_only_staked_bets_shown(self) -> None:
        bets = [
            _bet(event_id="won1", odds=2.0, model_prob=60),        # staked
            _bet(event_id="void1", odds=1.05, model_prob=95),      # no stake (odds < floor)
        ]
        data = build_dashboard_data(bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2)
        assert [m["leagueSlug"] for m in data["matches"]] == ["eng.1"]  # only the staked one

    def test_pl_uses_only_settled_bettable_bets(self) -> None:
        bets = [
            _bet(event_id="won1", odds=2.0, model_prob=60, settled=True, outcome="won", final_home=1, final_away=0),
            _bet(event_id="void1", odds=1.14, model_prob=70, settled=True, outcome="lost", final_home=0, final_away=1),
        ]
        data = build_dashboard_data(bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2)
        # Only the bettable won bet counts: 100 -> 110.
        assert data["pl"]["100"][0] == 110.0

    def test_matches_sorted_by_kickoff(self) -> None:
        bets = [
            _bet(event_id="lost1", settled=True, outcome="lost", final_home=0, final_away=1),
            _bet(event_id="won1", settled=True, outcome="won", final_home=1, final_away=0),
        ]
        data = build_dashboard_data(bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2)
        # won1 kickoff 14:30 before lost1 18:00.
        assert [m["leagueSlug"] for m in data["matches"]] == ["eng.1", "ita.1"]


class TestSyntheticSeparation:
    def test_synthetic_bet_excluded_from_real(self) -> None:
        bets = [_bet(event_id="won1", odds=1.2, model_prob=88, synthetic=True,
                     settled=True, outcome="won", final_home=0, final_away=2)]
        data = build_dashboard_data(
            bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2,
            synthetic_stake_fraction=0.02,
        )
        assert data["matches"] == []            # not on the real board
        assert data["pl"]["100"][0] == 100.0    # real bankroll untouched
        assert len(data["synthetic"]["matches"]) == 1
        assert data["synthetic"]["matches"][0]["leagueSlug"] == "eng.1"

    def test_synthetic_pl_uses_flat_stake(self) -> None:
        bets = [_bet(event_id="won1", odds=1.2, model_prob=88, synthetic=True,
                     settled=True, outcome="won", final_home=0, final_away=2)]
        data = build_dashboard_data(
            bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2,
            synthetic_stake_fraction=0.02,
        )
        # flat stake 2 at 1.2 win -> +0.4
        assert data["synthetic"]["pl"]["100"][0] == 100.4
        assert data["synthetic"]["matches"][0]["stakePct"] == 2.0

    def test_real_bet_not_in_synthetic(self) -> None:
        bets = [_bet(event_id="won1", odds=2.0, model_prob=60, settled=True,
                     outcome="won", final_home=1, final_away=0)]
        data = build_dashboard_data(
            bets, META, budgets=[100], kelly_fraction=0.5, min_odds=1.2,
            synthetic_stake_fraction=0.02,
        )
        assert [m["leagueSlug"] for m in data["matches"]] == ["eng.1"]
        assert data["synthetic"]["matches"] == []
