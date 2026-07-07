"""Tests for dispatching Telegram notifications from cycle outcomes."""

from __future__ import annotations

from types import SimpleNamespace

from src.notify.dispatch import notify_outcomes
from src.prediction.service.live import CycleOutcome
from src.schedule.repositories.bet_repo import Bet


class _Notifier:
    def __init__(self): self.sent: list[str] = []
    def send(self, text: str) -> bool: self.sent.append(text); return True


class _BetRepo:
    def __init__(self, bets): self._bets = bets
    def get(self, event_id): return self._bets.get(event_id)


class _MatchRepo:
    # Mirror the real MatchRepository method name so the fake can't hide a bug.
    def get_match(self, event_id):
        return SimpleNamespace(home_team="Lexington", away_team="Tampa Bay",
                               league_name="USL")


def _bet(**kw) -> Bet:
    d = dict(event_id="e", predicted_result="2", model_prob=88, odds=1.29,
             locked_minute=45, final_home=None, final_away=None, outcome=None,
             settled=False, bookmaker="Betfair Exchange")
    d.update(kw)
    return Bet(**d)


class TestNotifyOutcomes:
    def test_sends_on_locked_bet(self) -> None:
        notifier = _Notifier()
        notify_outcomes(
            [CycleOutcome("e", "predict", "locked_bet")],
            notifier, _BetRepo({"e": _bet()}), _MatchRepo(),
            kelly_multiplier=0.25, min_odds=1.2,
        )
        assert len(notifier.sent) == 1
        assert "Scommessa bloccata" in notifier.sent[0]

    def test_sends_on_settled_bet(self) -> None:
        notifier = _Notifier()
        bet = _bet(settled=True, outcome="won", final_home=0, final_away=3)
        notify_outcomes(
            [CycleOutcome("e", "done", "bet_settled")],
            notifier, _BetRepo({"e": bet}), _MatchRepo(),
            kelly_multiplier=0.25, min_odds=1.2,
        )
        assert len(notifier.sent) == 1
        assert "vinta" in notifier.sent[0].lower()

    def test_ignores_routine_outcomes(self) -> None:
        notifier = _Notifier()
        notify_outcomes(
            [CycleOutcome("e", "skip", "stable"),
             CycleOutcome("e", "predict", "no_usable_odds")],
            notifier, _BetRepo({}), _MatchRepo(),
            kelly_multiplier=0.25, min_odds=1.2,
        )
        assert notifier.sent == []

    def test_no_notifier_is_noop(self) -> None:
        # Must not raise when notifications are disabled.
        notify_outcomes(
            [CycleOutcome("e", "predict", "locked_bet")],
            None, _BetRepo({"e": _bet()}), _MatchRepo(),
            kelly_multiplier=0.25, min_odds=1.2,
        )
