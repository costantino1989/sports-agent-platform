"""Deterministic in-play 1X2 baseline from the scoreline and time remaining.

Given the current score and the minutes left, the remaining goals of each side
are modelled as independent Poisson variables whose rate scales with the time
left. The final result is decided by the current goal difference plus the
difference of those two Poissons (a Skellam distribution), summed into P(home
win) / P(draw) / P(away win).

This is a calibrated statistical prior — it assumes only score, time, and each
side's goal rate, no run-of-play. It is meant as an anchor the model can adjust
from, not a replacement for it.
"""

from __future__ import annotations

import math

# Remaining-goal counts beyond this are negligible; bounds the convolution.
_MAX_GOALS = 15


def shrunk_rate(total_goals: float, games: int, league_avg: float, k: float) -> float:
    """Return a per-match goal rate shrunk toward the league average.

    With few games a raw rate is noisy, so it is regularised toward the league
    mean by ``k`` pseudo-matches: ``(total + league_avg*k) / (games + k)``. With
    no games it returns the league average.

    Args:
        total_goals: Goals scored (or conceded) over the sample.
        games: Number of matches in the sample.
        league_avg: League mean goals per team per match (shrinkage target).
        k: Strength of the pull toward the league mean, in pseudo-matches.

    Returns:
        The regularised per-match rate.
    """

    denominator = games + k
    if denominator <= 0:
        return league_avg
    return (total_goals + league_avg * k) / denominator


def expected_goals(
    gf_home: float,
    ga_home: float,
    gp_home: int,
    gf_away: float,
    ga_away: float,
    gp_away: int,
    league_avg: float,
    home_adv: float,
    k: float,
) -> tuple[float, float]:
    """Return full-match expected goals ``(mu_home, mu_away)`` for the two teams.

    Combines each side's shrunk attack (goals scored/match) with the opponent's
    shrunk defence (goals conceded/match), normalised by the league average so an
    average attack against an average defence yields the league average. The home
    side gets a mild scoring multiplier.

    Args:
        gf_home/ga_home/gp_home: Home goals for, against, and games played.
        gf_away/ga_away/gp_away: Away goals for, against, and games played.
        league_avg: League mean goals per team per match.
        home_adv: Multiplier applied to the home expectancy.
        k: Shrinkage strength (pseudo-matches).

    Returns:
        ``(mu_home, mu_away)`` expected goals over a full 90 minutes.
    """

    attack_home = shrunk_rate(gf_home, gp_home, league_avg, k)
    defence_home = shrunk_rate(ga_home, gp_home, league_avg, k)
    attack_away = shrunk_rate(gf_away, gp_away, league_avg, k)
    defence_away = shrunk_rate(ga_away, gp_away, league_avg, k)
    safe_league_avg = league_avg if league_avg > 0 else 1.0
    mu_home = attack_home * defence_away / safe_league_avg * home_adv
    mu_away = attack_away * defence_home / safe_league_avg
    return mu_home, mu_away


def _poisson_pmf(count: int, rate: float) -> float:
    """Probability of exactly ``count`` events for a Poisson with mean ``rate``."""

    if rate <= 0.0:
        return 1.0 if count == 0 else 0.0
    return math.exp(-rate) * rate**count / math.factorial(count)


def live_1x2_probabilities(
    home_score: int,
    away_score: int,
    minutes_remaining: float,
    mu_home: float,
    mu_away: float,
) -> tuple[float, float, float]:
    """Return ``(p_home, p_draw, p_away)`` for the final result.

    Args:
        home_score: Current home goals.
        away_score: Current away goals.
        minutes_remaining: Minutes left to play (including a stoppage estimate).
        mu_home: Home expected goals over a full 90 minutes (team-adjusted).
        mu_away: Away expected goals over a full 90 minutes (team-adjusted).

    Returns:
        The probabilities of a home win, draw, and away win, summing to 1.
    """

    fraction = max(0.0, minutes_remaining) / 90.0
    rate_home = max(0.0, mu_home) * fraction
    rate_away = max(0.0, mu_away) * fraction
    current_difference = home_score - away_score

    home_probs = [_poisson_pmf(goals, rate_home) for goals in range(_MAX_GOALS + 1)]
    away_probs = [_poisson_pmf(goals, rate_away) for goals in range(_MAX_GOALS + 1)]

    p_home = p_draw = p_away = 0.0
    for extra_home, prob_home in enumerate(home_probs):
        for extra_away, prob_away in enumerate(away_probs):
            joint = prob_home * prob_away
            final_difference = current_difference + extra_home - extra_away
            if final_difference > 0:
                p_home += joint
            elif final_difference == 0:
                p_draw += joint
            else:
                p_away += joint

    total = p_home + p_draw + p_away
    if total <= 0.0:  # pragma: no cover - guarded by Poisson normalisation
        return 0.0, 1.0, 0.0
    return p_home / total, p_draw / total, p_away / total


def over_under_probabilities(
    home_score: int,
    away_score: int,
    minutes_remaining: float,
    mu_home: float,
    mu_away: float,
    line: float,
) -> tuple[float, float]:
    """Return ``(p_over, p_under)`` for the final total goals versus ``line``.

    Remaining total goals follow a single Poisson with rate ``(mu_home+mu_away)``
    scaled by the time left (the sum of two independent Poissons is Poisson of the
    summed rate). The final total is the current total plus that count.

    Args:
        home_score: Current home goals.
        away_score: Current away goals.
        minutes_remaining: Minutes left to play (including a stoppage estimate).
        mu_home: Home expected goals over a full 90 minutes.
        mu_away: Away expected goals over a full 90 minutes.
        line: Over/Under line (e.g. 2.5).

    Returns:
        The probabilities that the final total is over and under the line,
        summing to 1.
    """

    fraction = max(0.0, minutes_remaining) / 90.0
    rate_total = max(0.0, mu_home + mu_away) * fraction
    current_total = home_score + away_score

    p_over = p_under = 0.0
    for remaining in range(_MAX_GOALS * 2 + 1):
        probability = _poisson_pmf(remaining, rate_total)
        if current_total + remaining > line:
            p_over += probability
        else:
            p_under += probability

    total = p_over + p_under
    if total <= 0.0:  # pragma: no cover - guarded by Poisson normalisation
        return 0.0, 1.0
    return p_over / total, p_under / total
