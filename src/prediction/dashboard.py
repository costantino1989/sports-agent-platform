"""Build dashboard data (match cards + bankroll P/L) from persisted bets.

Turns the ``match_bets`` rows into the JSON the web page renders: one card per
locked bet (won / lost / pending / no-bet) plus the profit-loss simulation per
budget over the settled, bettable bets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.prediction.betting import (
    BetRecord,
    bankroll_by_budget,
    capped_kelly_stake,
    flat_bankroll_by_budget,
    is_bettable,
)

if TYPE_CHECKING:
    from src.schedule.repositories.bet_repo import Bet


def _card(
    bet: "Bet",
    meta: dict[str, Any],
    min_odds: float,
    kelly_mult: float,
    max_stake_fraction: float,
) -> dict[str, Any]:
    """Build one card dict for a bet."""

    if bet.settled:
        status = "won" if bet.outcome == "won" else "lost"
    else:
        status = "pending"

    bettable = bet.odds is not None and is_bettable(bet.odds, bet.model_prob, min_odds)
    # Stake as a percentage of bankroll (fractional Kelly, capped); None when no bet.
    stake_pct = (
        round(capped_kelly_stake(bet.model_prob, bet.odds, kelly_mult, max_stake_fraction) * 100, 1)
        if bettable
        else None
    )
    no_bet_reason = ""
    if not bettable:
        no_bet_reason = (
            f"Quota {bet.odds} < minimo {min_odds} o valore atteso non positivo "
            "→ nessuna scommessa piazzata."
        )

    detail = (
        f"Risultato {bet.final_home}-{bet.final_away} → {bet.outcome}."
        if bet.settled
        else "In attesa del risultato."
    )
    # Prefer the stored model analysis; fall back to a factual one-liner.
    if bet.rationale:
        rationale = [
            bet.rationale,
            f"Scommessa: {bet.predicted_result} @ {bet.odds} ({bet.model_prob}%). {detail}",
        ]
    else:
        rationale = [
            f"Scommessa bloccata: {bet.predicted_result} @ "
            f"{bet.odds if bet.odds is not None else 'n/d'} con confidenza "
            f"{bet.model_prob}% (minuto {bet.locked_minute}). {detail}"
        ]
    return {
        "league": meta.get("league_name", meta.get("league_slug", "")),
        "leagueSlug": meta.get("league_slug", ""),
        "kickoffUtc": meta.get("kickoff_utc", ""),
        "home": meta.get("home", ""),
        "away": meta.get("away", ""),
        "predicted": bet.predicted_result,
        "probability": bet.model_prob,
        "lockedMinute": bet.locked_minute,
        "stakePct": stake_pct,
        "odds": bet.odds if bettable else None,
        "bookmaker": bet.bookmaker,
        "status": status,
        "finalHome": bet.final_home,
        "finalAway": bet.final_away,
        "noBetReason": no_bet_reason,
        "rationale": rationale,
        "evidence": list(bet.evidence),
    }


def _synthetic_card(
    bet: "Bet", meta: dict[str, Any], stake_fraction: float
) -> dict[str, Any]:
    """Build one card for a synthetic (placeholder-odds) bet, flat-staked."""

    if bet.settled:
        status = "won" if bet.outcome == "won" else "lost"
    else:
        status = "pending"
    detail = (
        f"Risultato {bet.final_home}-{bet.final_away} → {bet.outcome}."
        if bet.settled
        else "In attesa del risultato."
    )
    rationale = [bet.rationale] if bet.rationale else []
    rationale.append(
        f"Scommessa simulata (nessuna quota reale): {bet.predicted_result} @ "
        f"{bet.odds} con confidenza {bet.model_prob}% (minuto {bet.locked_minute}). "
        f"{detail}"
    )
    return {
        "league": meta.get("league_name", meta.get("league_slug", "")),
        "leagueSlug": meta.get("league_slug", ""),
        "kickoffUtc": meta.get("kickoff_utc", ""),
        "home": meta.get("home", ""),
        "away": meta.get("away", ""),
        "predicted": bet.predicted_result,
        "probability": bet.model_prob,
        "lockedMinute": bet.locked_minute,
        "stakePct": round(stake_fraction * 100, 1),
        "odds": bet.odds,
        "bookmaker": bet.bookmaker or "Sintetica",
        "status": status,
        "finalHome": bet.final_home,
        "finalAway": bet.final_away,
        "noBetReason": "",
        "synthetic": True,
        "rationale": rationale,
        "evidence": list(bet.evidence),
    }


def _pl_by_budget(results: dict[float, Any]) -> dict[str, list[float]]:
    """Format a bankroll-by-budget result map into the page's P/L shape."""

    return {
        str(int(budget)): [round(result.end, 2), round(result.roi * 100, 1)]
        for budget, result in results.items()
    }


def _real_section(
    bets: list["Bet"],
    matches_meta: dict[str, dict[str, Any]],
    budgets: list[float],
    kelly_fraction: float,
    min_odds: float,
    max_stake_fraction: float,
) -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    """Cards + P/L for real (non-synthetic) staked bets, priced against Kelly."""

    staked = [
        bet
        for bet in bets
        if not bet.synthetic
        and bet.odds is not None
        and is_bettable(bet.odds, bet.model_prob, min_odds)
    ]
    cards = [
        _card(bet, matches_meta.get(bet.event_id, {}), min_odds, kelly_fraction, max_stake_fraction)
        for bet in staked
    ]
    cards.sort(key=lambda card: card["kickoffUtc"])
    records = [
        BetRecord(
            event_id=bet.event_id,
            odds=bet.odds,
            model_prob=bet.model_prob,
            outcome=bet.outcome or "lost",
        )
        for bet in staked
        if bet.settled
    ]
    return cards, _pl_by_budget(
        bankroll_by_budget(records, budgets, kelly_fraction, max_stake_fraction)
    )


def _synthetic_section(
    bets: list["Bet"],
    matches_meta: dict[str, dict[str, Any]],
    budgets: list[float],
    stake_fraction: float,
) -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    """Cards + P/L for synthetic bets, using a flat stake (no positive-EV gate)."""

    synthetic = [bet for bet in bets if bet.synthetic]
    cards = [
        _synthetic_card(bet, matches_meta.get(bet.event_id, {}), stake_fraction)
        for bet in synthetic
    ]
    cards.sort(key=lambda card: card["kickoffUtc"])
    records = [
        BetRecord(
            event_id=bet.event_id,
            odds=bet.odds,
            model_prob=bet.model_prob,
            outcome=bet.outcome or "lost",
        )
        for bet in synthetic
        if bet.settled and bet.odds is not None
    ]
    results = flat_bankroll_by_budget(records, budgets, stake_fraction)
    return cards, _pl_by_budget(results)


def build_dashboard_data(
    bets: list["Bet"],
    matches_meta: dict[str, dict[str, Any]],
    budgets: list[float],
    kelly_fraction: float,
    min_odds: float,
    synthetic_stake_fraction: float = 0.0,
    max_stake_fraction: float = 1.0,
) -> dict[str, Any]:
    """Build the dashboard payload (cards + P/L) from locked bets.

    Real bets (priced from a bookmaker) and synthetic bets (placeholder odds when
    no market exists) are reported separately: the real board measures beating
    the market, the synthetic board measures picking winners at a conservative
    price. They never share a bankroll.

    Args:
        bets: Locked bets (settled and pending).
        matches_meta: Per-event metadata (league/home/away/kickoff).
        budgets: Starting budgets for the bankroll simulation.
        kelly_fraction: Fraction of full Kelly to stake (real bets).
        min_odds: Minimum odds for a real bet.
        synthetic_stake_fraction: Flat fraction of bankroll staked per synthetic
            bet.

    Returns:
        Dict with ``matches``/``pl`` (real, kickoff-sorted) and a ``synthetic``
        sub-dict with its own ``matches``/``pl``.
    """

    cards, pl = _real_section(
        bets, matches_meta, budgets, kelly_fraction, min_odds, max_stake_fraction
    )
    synthetic_cards, synthetic_pl = _synthetic_section(
        bets, matches_meta, budgets, synthetic_stake_fraction
    )
    return {
        "matches": cards,
        "pl": pl,
        "synthetic": {"matches": synthetic_cards, "pl": synthetic_pl},
    }
