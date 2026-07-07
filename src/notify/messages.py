"""Format Telegram message bodies from bets (pure, HTML parse mode)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.prediction.betting import is_bettable

if TYPE_CHECKING:
    from src.schedule.repositories.bet_repo import Bet

_PICK_LABEL = {"1": "Vittoria casa", "X": "Pareggio", "2": "Vittoria trasferta"}


def _bookmaker(bet: "Bet") -> str:
    """Bookmaker label, or a dash when unknown."""

    return bet.bookmaker or "n/d"


def lock_message(
    bet: "Bet", home: str, away: str, league: str, stake_pct: float | None
) -> str:
    """Format the message sent when a bet is locked.

    Args:
        bet: The freshly locked bet.
        home: Home team name.
        away: Away team name.
        league: League display name.
        stake_pct: Kelly stake as a percentage of bankroll, or None for no bet.

    Returns:
        HTML message body.
    """

    lines = [
        "🎯 <b>Scommessa bloccata</b>",
        f"{home} vs {away} · {league}",
        f"Esito: <b>{bet.predicted_result}</b> ({_PICK_LABEL.get(bet.predicted_result, '?')})",
        f"Quota: <b>{bet.odds}</b> [{_bookmaker(bet)}]",
        f"Confidenza: {bet.model_prob}% · minuto {bet.locked_minute}'",
    ]
    if stake_pct is not None:
        lines.append(f"Puntata: <b>{stake_pct}%</b> del bankroll (Kelly)")
    else:
        lines.append("Nessuna puntata (quota sotto minimo o valore ≤ 0)")
    return "\n".join(lines)


def settle_message(
    bet: "Bet", home: str, away: str, profit_units: float | None
) -> str:
    """Format the message sent when a bet is settled.

    Args:
        bet: The settled bet.
        home: Home team name.
        away: Away team name.
        profit_units: Profit/loss in units for a real bet, or None if no stake.

    Returns:
        HTML message body.
    """

    won = bet.outcome == "won"
    emoji = "✅" if won else "❌"
    lines = [
        f"{emoji} <b>Scommessa {'vinta' if won else 'persa'}</b>",
        f"{home} vs {away}",
        f"Risultato: <b>{bet.final_home}-{bet.final_away}</b>",
        f"Pronostico: {bet.predicted_result} @ {bet.odds} [{_bookmaker(bet)}]",
    ]
    if profit_units is not None:
        sign = "+" if profit_units >= 0 else ""
        lines.append(f"P/L: <b>{sign}{profit_units:.2f}</b> unità")
    return "\n".join(lines)


def _bet_profit_units(bet: "Bet", min_odds: float) -> float | None:
    """Profit/loss in units for one settled bet, or None when it was no bet."""

    if bet.odds is None or not is_bettable(bet.odds, bet.model_prob, min_odds):
        return None
    if bet.outcome == "won":
        return bet.odds - 1.0
    return -1.0


def daily_summary_message(bets: list["Bet"], min_odds: float) -> str:
    """Format the once-a-day recap of bets and profit/loss.

    Args:
        bets: All persisted bets.
        min_odds: Minimum odds for a bet to count in the P/L.

    Returns:
        HTML message body.
    """

    if not bets:
        return "📊 <b>Riepilogo giornaliero</b>\nNessuna scommessa registrata."
    settled = [bet for bet in bets if bet.settled]
    won = sum(1 for bet in settled if bet.outcome == "won")
    lost = sum(1 for bet in settled if bet.outcome == "lost")
    pending = len(bets) - len(settled)
    profits = [_bet_profit_units(bet, min_odds) for bet in settled]
    staked = [value for value in profits if value is not None]
    units = sum(staked)
    roi = (units / len(staked) * 100) if staked else 0.0
    sign = "+" if units >= 0 else ""
    return "\n".join(
        [
            "📊 <b>Riepilogo giornaliero</b>",
            f"Scommesse: <b>{len(bets)}</b> (vinte {won}, perse {lost}, in attesa {pending})",
            f"P/L: <b>{sign}{units:.2f}</b> unità · ROI {roi:.1f}%",
        ]
    )
