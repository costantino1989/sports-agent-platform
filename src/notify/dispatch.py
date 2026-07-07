"""Turn live-cycle outcomes into Telegram notifications (best-effort).

Kept out of ``LivePredictionService`` so the tested cycle logic stays free of
notification concerns: ``main.py`` calls this with the outcomes the cycle
returned, and only the noteworthy ones (a bet locked, a bet settled) produce a
message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.notify.messages import _bet_profit_units, lock_message, settle_message
from src.prediction.betting import capped_kelly_stake, is_bettable

if TYPE_CHECKING:
    from src.notify.telegram import TelegramNotifier
    from src.prediction.service.live import CycleOutcome


def _stake_pct(
    bet, kelly_multiplier: float, min_odds: float, max_stake_fraction: float
) -> float | None:
    """Capped Kelly stake as a percentage of bankroll, or None when no bet."""

    if bet.odds is None or not is_bettable(bet.odds, bet.model_prob, min_odds):
        return None
    return round(
        capped_kelly_stake(bet.model_prob, bet.odds, kelly_multiplier, max_stake_fraction) * 100,
        1,
    )


def notify_outcomes(
    outcomes: "list[CycleOutcome]",
    notifier: "TelegramNotifier | None",
    bet_repo,  # type: ignore[no-untyped-def]
    match_repo,  # type: ignore[no-untyped-def]
    kelly_multiplier: float,
    min_odds: float,
    max_stake_fraction: float = 1.0,
) -> None:
    """Send Telegram messages for locked/settled bets in this cycle's outcomes.

    Args:
        outcomes: Outcomes returned by ``LivePredictionService.run_cycle``.
        notifier: Telegram notifier, or None to disable (no-op).
        bet_repo: Repository exposing ``get(event_id) -> Bet | None``.
        match_repo: Repository exposing ``get(event_id)`` with team/league names.
        kelly_multiplier: Fractional-Kelly multiplier for the stake shown.
        min_odds: Minimum odds for a bet to count as a real stake.
    """

    if notifier is None:
        return
    for outcome in outcomes:
        if outcome.reason == "locked_bet":
            _notify_lock(
                outcome, notifier, bet_repo, match_repo, kelly_multiplier, min_odds,
                max_stake_fraction,
            )
        elif outcome.action == "done" and outcome.reason == "bet_settled":
            _notify_settle(outcome, notifier, bet_repo, match_repo, min_odds)


def _teams(match_repo, event_id: str) -> tuple[str, str, str]:  # type: ignore[no-untyped-def]
    """Resolve (home, away, league) for an event, with safe fallbacks."""

    record = match_repo.get_match(event_id)
    if record is None:
        return "Casa", "Trasferta", ""
    return record.home_team, record.away_team, record.league_name


def _notify_lock(outcome, notifier, bet_repo, match_repo, kelly_multiplier, min_odds, max_stake_fraction) -> None:  # type: ignore[no-untyped-def]
    """Send the bet-locked message for one outcome."""

    bet = bet_repo.get(outcome.event_id)
    if bet is None:
        return
    home, away, league = _teams(match_repo, outcome.event_id)
    stake_pct = _stake_pct(bet, kelly_multiplier, min_odds, max_stake_fraction)
    notifier.send(lock_message(bet, home, away, league, stake_pct))


def _notify_settle(outcome, notifier, bet_repo, match_repo, min_odds) -> None:  # type: ignore[no-untyped-def]
    """Send the bet-settled message for one outcome."""

    bet = bet_repo.get(outcome.event_id)
    if bet is None or not bet.settled:
        return
    home, away, _league = _teams(match_repo, outcome.event_id)
    notifier.send(settle_message(bet, home, away, _bet_profit_units(bet, min_odds)))
