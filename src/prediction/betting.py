"""Betting engine: settle picks and simulate profit/loss across budgets.

Bets are placed only when the odds clear a floor and the model shows positive
expected value. Stakes use fractional Kelly. Bankroll is simulated sequentially
per starting budget so different budgets can be compared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Column index (after provider, snapshot) for each 1X2 outcome in the odds table.
_ODDS_COLUMN = {"1": 0, "X": 1, "2": 2}
_ODDS_ROW = re.compile(
    r"^\|\s*(?P<provider>[^|]+)\|\s*(?P<snapshot>[^|]+)\|\s*(?P<home>[^|]+)\|\s*(?P<draw>[^|]+)\|\s*(?P<away>[^|]+)\|"
)
# Provider-name hints that mark a row as live/real odds (reflecting the current
# score) rather than a frozen pre-match snapshot. A live/exchange row is
# preferred so the bet is priced against the market as it stands, not kickoff.
_LIVE_PROVIDER_HINTS = ("live", "exchange")


def _odds_row_rank(provider: str, snapshot: str) -> int:
    """Rank an odds row: live current > plain current > non-current fallback."""

    if snapshot.strip().lower() != "current":
        return 0
    provider_lower = provider.lower()
    if any(hint in provider_lower for hint in _LIVE_PROVIDER_HINTS):
        return 2
    return 1


def _provider_allowed(provider: str, allowed_hints: tuple[str, ...] | None) -> bool:
    """Whether a row's bookmaker may be used to price a bet.

    When ``allowed_hints`` is given, only providers whose name contains one of
    the (already lowercased, alphanumeric) hints qualify — e.g. ``("betfair",
    "bet365")`` restricts betting to Betfair/Bet365 and rejects ESPN books such
    as DraftKings. ``None`` allows any provider.
    """

    if allowed_hints is None:
        return True
    normalized = "".join(char for char in provider.lower() if char.isalnum())
    return any(hint in normalized for hint in allowed_hints)


def parse_predicted_odds(dossier_markdown: str, predicted_result: str) -> float | None:
    """Extract the decimal odds of the predicted outcome from the dossier.

    Reads the section 8 "1X2 odds" table, preferring the ``Current`` snapshot
    (falling back to the first parseable row).

    Args:
        dossier_markdown: Full rendered dossier markdown.
        predicted_result: Predicted outcome, one of "1", "X", "2".

    Returns:
        Decimal odds for the outcome, or None when unavailable.
    """

    pick = select_predicted_odds(dossier_markdown, predicted_result)
    return pick[0] if pick is not None else None


def select_predicted_odds(
    dossier_markdown: str,
    predicted_result: str,
    allowed_provider_hints: tuple[str, ...] | None = None,
) -> tuple[float, str] | None:
    """Extract the predicted outcome's odds and the bookmaker they came from.

    Same selection as :func:`parse_predicted_odds` (live current > plain current
    > fallback), but also returns the provider name of the chosen row so the
    bookmaker can be shown and stored alongside the price.

    Args:
        dossier_markdown: Full rendered dossier markdown.
        predicted_result: Predicted outcome, one of "1", "X", "2".
        allowed_provider_hints: Optional lowercased-alphanumeric substrings; only
            rows from a matching bookmaker are considered (e.g. ``("betfair",
            "bet365")``). ``None`` allows any bookmaker.

    Returns:
        Pair ``(odds, bookmaker)`` for the outcome, or None when no allowed row
        carries a usable price.
    """

    column = _ODDS_COLUMN.get(predicted_result)
    if column is None:
        return None
    best_rank = -1
    best: tuple[float, str] | None = None
    for line in dossier_markdown.splitlines():
        match = _ODDS_ROW.match(line)
        if match is None:
            continue
        provider = match.group("provider").strip()
        if not _provider_allowed(provider, allowed_provider_hints):
            continue
        values = (match.group("home"), match.group("draw"), match.group("away"))
        raw = values[column].strip().replace(",", ".")
        try:
            odds = float(raw)
        except ValueError:
            continue
        rank = _odds_row_rank(provider, match.group("snapshot"))
        # Strictly greater so the first row wins ties: an injected exchange row
        # (placed at the top of section 8) stays ahead of equal-rank ESPN rows.
        if rank > best_rank:
            best_rank = rank
            best = (odds, provider)
    return best


def result_from_score(home_score: int, away_score: int) -> str:
    """Map a final score to a 1X2 result code."""

    if home_score > away_score:
        return "1"
    if home_score < away_score:
        return "2"
    return "X"


def settle_bet(predicted_result: str, final_home: int, final_away: int) -> str:
    """Return 'won' if the pick matches the final result, else 'lost'."""

    return (
        "won"
        if predicted_result == result_from_score(final_home, final_away)
        else "lost"
    )


def is_bettable(odds: float, model_prob: int, min_odds: float) -> bool:
    """Return whether a pick is worth betting.

    A bet is placed only when the odds are at least ``min_odds`` and the model
    probability exceeds the odds-implied probability (positive expected value).

    Args:
        odds: Decimal odds of the predicted outcome.
        model_prob: Model success probability, 0-100.
        min_odds: Minimum odds allowed.

    Returns:
        True when the bet clears both the floor and the value check.
    """

    if odds < min_odds or odds <= 1.0:
        return False
    return (model_prob / 100.0) > (1.0 / odds)


def kelly_fraction(model_prob: int, odds: float) -> float:
    """Full Kelly stake fraction for a pick, clamped to [0, 1].

    Args:
        model_prob: Model success probability, 0-100.
        odds: Decimal odds.

    Returns:
        Optimal fraction of bankroll to stake (0 when there is no edge).
    """

    probability = model_prob / 100.0
    net_odds = odds - 1.0
    if net_odds <= 0:
        return 0.0
    fraction = (probability * odds - 1.0) / net_odds
    return max(0.0, min(1.0, fraction))


# Internal alias so simulate_bankroll can call the Kelly function without being
# shadowed by its own ``kelly_fraction`` parameter.
_full_kelly = kelly_fraction


def capped_kelly_stake(
    model_prob: int, odds: float, kelly_multiplier: float, max_fraction: float
) -> float:
    """Fractional-Kelly stake as a bankroll fraction, capped at ``max_fraction``.

    At low odds the Kelly fraction can be large for a tiny payout (risking a big
    slice of the bankroll to win a little), so a single loss hurts. The cap bounds
    that downside while leaving normal bets untouched.

    Args:
        model_prob: Model success probability, 0-100.
        odds: Decimal odds of the predicted outcome.
        kelly_multiplier: Fraction of full Kelly to stake (e.g. 0.25).
        max_fraction: Hard ceiling on the bankroll fraction staked.

    Returns:
        The bankroll fraction to stake, in ``[0, max_fraction]``.
    """

    return min(max_fraction, kelly_multiplier * _full_kelly(model_prob, odds))


@dataclass(frozen=True)
class BetRecord:
    """One settled, bettable pick used in the bankroll simulation."""

    event_id: str
    odds: float
    model_prob: int
    outcome: str  # "won" or "lost"


@dataclass(frozen=True)
class BankrollResult:
    """Outcome of simulating a starting budget over a sequence of bets."""

    start: float
    end: float
    roi: float


def simulate_bankroll(
    bets: list[BetRecord],
    budget: float,
    kelly_fraction: float,
    max_stake_fraction: float = 1.0,
) -> BankrollResult:
    """Simulate a bankroll over settled bets in order, using fractional Kelly.

    Args:
        bets: Settled bettable bets, in chronological order.
        budget: Starting bankroll.
        kelly_fraction: Fraction of full Kelly to stake (e.g. 0.5 for half-Kelly).
        max_stake_fraction: Hard ceiling on the bankroll fraction staked per bet.

    Returns:
        Start, end balance, and ROI for this budget.
    """

    balance = float(budget)
    for bet in bets:
        stake = balance * capped_kelly_stake(
            bet.model_prob, bet.odds, kelly_fraction, max_stake_fraction
        )
        if bet.outcome == "won":
            balance += stake * (bet.odds - 1.0)
        else:
            balance -= stake
    roi = (balance - budget) / budget if budget else 0.0
    return BankrollResult(start=float(budget), end=balance, roi=roi)


def bankroll_by_budget(
    bets: list[BetRecord],
    budgets: list[float],
    kelly_fraction: float,
    max_stake_fraction: float = 1.0,
) -> dict[float, BankrollResult]:
    """Simulate each starting budget over the same sequence of bets.

    Args:
        bets: Settled bettable bets, in chronological order.
        budgets: Starting budgets to compare.
        kelly_fraction: Fraction of full Kelly to stake.
        max_stake_fraction: Hard ceiling on the bankroll fraction staked per bet.

    Returns:
        Mapping of each budget to its bankroll result.
    """

    return {
        budget: simulate_bankroll(bets, budget, kelly_fraction, max_stake_fraction)
        for budget in budgets
    }


def simulate_flat_bankroll(
    bets: list[BetRecord], budget: float, stake_fraction: float
) -> BankrollResult:
    """Simulate a bankroll staking a flat fraction of balance on each bet.

    Used for synthetic (placeholder-odds) bets: their conservative odds make the
    expected value non-positive, so Kelly would stake nothing. A flat stake lets
    us still measure how the model's confident picks would fare at that
    pessimistic price — a win adds ``stake * (odds - 1)``, a loss removes the
    whole stake.

    Args:
        bets: Settled bets, in chronological order.
        budget: Starting bankroll.
        stake_fraction: Flat fraction of the current balance staked per bet.

    Returns:
        Start, end balance, and ROI for this budget.
    """

    balance = float(budget)
    for bet in bets:
        stake = balance * stake_fraction
        if bet.outcome == "won":
            balance += stake * (bet.odds - 1.0)
        else:
            balance -= stake
    roi = (balance - budget) / budget if budget else 0.0
    return BankrollResult(start=float(budget), end=balance, roi=roi)


def flat_bankroll_by_budget(
    bets: list[BetRecord], budgets: list[float], stake_fraction: float
) -> dict[float, BankrollResult]:
    """Simulate each starting budget over the same synthetic bets (flat stake)."""

    return {
        budget: simulate_flat_bankroll(bets, budget, stake_fraction)
        for budget in budgets
    }
