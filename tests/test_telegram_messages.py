"""Tests for Telegram message formatting."""

from __future__ import annotations

from src.notify.messages import daily_summary_message, lock_message, settle_message
from src.schedule.repositories.bet_repo import Bet


def _bet(**kw) -> Bet:
    defaults = dict(
        event_id="e", predicted_result="2", model_prob=88, odds=1.29,
        locked_minute=45, final_home=None, final_away=None, outcome=None,
        settled=False, bookmaker="Betfair Exchange",
    )
    defaults.update(kw)
    return Bet(**defaults)


class TestLockMessage:
    def test_includes_teams_pick_odds_bookmaker(self) -> None:
        text = lock_message(_bet(), "Lexington", "Tampa Bay", "USL", stake_pct=11.7)
        assert "Lexington" in text and "Tampa Bay" in text
        assert "1.29" in text
        assert "Betfair Exchange" in text
        assert "88%" in text
        assert "11.7" in text  # stake

    def test_no_bet_when_stake_none(self) -> None:
        text = lock_message(_bet(), "A", "B", "L", stake_pct=None)
        assert "Nessuna puntata" in text


class TestSettleMessage:
    def test_won_message(self) -> None:
        bet = _bet(settled=True, outcome="won", final_home=0, final_away=3)
        text = settle_message(bet, "Lexington", "Tampa Bay", profit_units=0.29)
        assert "vinta" in text.lower()
        assert "0-3" in text
        assert "+0.29" in text

    def test_lost_message(self) -> None:
        bet = _bet(settled=True, outcome="lost", final_home=2, final_away=0)
        text = settle_message(bet, "A", "B", profit_units=-1.0)
        assert "persa" in text.lower()
        assert "-1.00" in text


class TestDailySummary:
    def test_counts_and_pl(self) -> None:
        bets = [
            _bet(event_id="w", settled=True, outcome="won", odds=2.0, model_prob=90),
            _bet(event_id="l", settled=True, outcome="lost", odds=2.0, model_prob=90),
            _bet(event_id="p", settled=False),
        ]
        text = daily_summary_message(bets, min_odds=1.2)
        assert "3" in text          # total bets
        assert "vinte" in text.lower() and "perse" in text.lower()
        # won +1.0 (2.0-1), lost -1.0 -> net 0.00 units
        assert "0.00" in text

    def test_empty(self) -> None:
        text = daily_summary_message([], min_odds=1.2)
        assert "essun" in text  # "Nessuna scommessa"
