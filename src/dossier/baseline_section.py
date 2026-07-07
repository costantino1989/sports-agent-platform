"""Render a deterministic 1X2 baseline section for the dossier.

Computes a calibrated statistical prior from the current score, the time
remaining, and each team's season goal rates (goals for/against from the
standings, shrunk toward the league average). The model is asked to treat this
as an anchor, not a replacement for its own read of the play-by-play.
"""

from __future__ import annotations

import re
from typing import Any, TypeAlias

from src.dossier.render_tools import (
    build_stat_map,
    extract_live_snapshot,
    find_dicts_with_keys,
    first_value,
)
from src.models.dossier import MatchDossierData
from src.prediction.live_baseline import (
    expected_goals,
    live_1x2_probabilities,
    over_under_probabilities,
)

JsonDict: TypeAlias = dict[str, Any]

_DEFAULT_LEAGUE_AVG = 1.35
_HOME_ADVANTAGE = 1.10
_SHRINK_K = 5.0
_STOPPAGE = 3.0
_OU_LINES = (1.5, 2.5, 3.5)
_SECTION_TITLE = "## 15. Baseline statistico 1X2 (punteggio + tempo)"


def _to_number(value: str) -> float | None:
    """Parse a stat string to a float, or None when not numeric."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize(name: str) -> str:
    """Lowercase alphanumeric key for tolerant team-name matching."""

    return "".join(char for char in name.lower() if char.isalnum())


def _standings_rates(data: MatchDossierData) -> tuple[dict[str, tuple[float, float, int]], float]:
    """Return per-team ``{norm_name: (gf, ga, gp)}`` and the league average.

    The league average is total goals for divided by total games across the
    parsed teams; it falls back to the default when standings are unavailable.
    """

    payload = data.standings.data
    rates: dict[str, tuple[float, float, int]] = {}
    if not isinstance(payload, (dict, list)):
        return rates, _DEFAULT_LEAGUE_AVG
    total_goals = 0.0
    total_games = 0
    for entry in find_dicts_with_keys(payload, {"team", "stats"}, limit=40):
        team = entry.get("team", {}) if isinstance(entry.get("team"), dict) else {}
        name = team.get("displayName") or team.get("name")
        stat_map = build_stat_map(entry.get("stats"))
        goals_for = _to_number(first_value(stat_map, ["pointsFor", "goalsFor"]))
        goals_against = _to_number(first_value(stat_map, ["pointsAgainst", "goalsAgainst"]))
        games = _to_number(first_value(stat_map, ["gamesPlayed", "games", "gp"]))
        if not name or goals_for is None or goals_against is None or not games:
            continue
        rates[_normalize(str(name))] = (goals_for, goals_against, int(games))
        total_goals += goals_for
        total_games += int(games)
    league_avg = total_goals / total_games if total_games > 0 else _DEFAULT_LEAGUE_AVG
    return rates, league_avg


def _minute_and_state(status_type: JsonDict | None) -> tuple[int, str]:
    """Return ``(minute, state)`` where state is 'pre' | 'in' | 'post'."""

    if not isinstance(status_type, dict):
        return 0, "pre"
    state = str(status_type.get("state") or "pre")
    if status_type.get("completed"):
        state = "post"
    minute = 0
    for key in ("detail", "shortDetail", "description"):
        text = status_type.get(key)
        if isinstance(text, str):
            match = re.search(r"\d+", text)
            if match:
                minute = int(match.group(0))
                break
    return minute, state


def _minutes_remaining(minute: int, state: str) -> float:
    """Estimate minutes left to play from the match minute and state."""

    if state == "post":
        return 0.0
    if state == "pre":
        return 90.0
    if minute >= 90:
        return _STOPPAGE
    return max(0.0, 90.0 - minute) + _STOPPAGE


def _live_sides(data: MatchDossierData) -> tuple[dict[str, Any], JsonDict | None]:
    """Return ``{'home': {...}, 'away': {...}}`` competitors and the status type.

    Falls back to the persisted match teams (index 0 = home) when the live
    summary header is absent, e.g. a genuine pre-match build.
    """

    competitors, status_type = extract_live_snapshot(data.summary.data)
    sides = {c["side"]: c for c in competitors if c.get("side") in ("home", "away")}
    if "home" in sides and "away" in sides:
        return sides, status_type
    teams = data.match.teams
    if len(teams) >= 2:
        sides = {
            "home": {"team_name": teams[0].team.display_name or teams[0].team.name or "", "score": teams[0].score or "0"},
            "away": {"team_name": teams[1].team.display_name or teams[1].team.name or "", "score": teams[1].score or "0"},
        }
    return sides, status_type


def _score(competitor: dict[str, Any]) -> int:
    """Parse a competitor's integer score, defaulting to 0."""

    value = _to_number(str(competitor.get("score", "0")))
    return int(value) if value is not None else 0


def _play_items(plays_data: Any) -> list[JsonDict]:
    """Return the list of play dicts from the plays payload, tolerantly."""

    if isinstance(plays_data, dict):
        items = plays_data.get("items") or plays_data.get("plays")
        return [p for p in items if isinstance(p, dict)] if isinstance(items, list) else []
    if isinstance(plays_data, list):
        return [p for p in plays_data if isinstance(p, dict)]
    return []


def _score_from_plays(plays_data: Any) -> tuple[int, int, int] | None:
    """Return ``(home, away, minute)`` from the latest scoring play, if any.

    Each scoring play carries the running ``homeScore``/``awayScore``; the play
    with the most total goals is the current score. This is fresher than the
    summary header, which can lag the play-by-play by a cycle.
    """

    scoring = [play for play in _play_items(plays_data) if play.get("scoringPlay")]
    if not scoring:
        return None

    def total(play: JsonDict) -> float:
        return (_to_number(str(play.get("homeScore", 0))) or 0.0) + (
            _to_number(str(play.get("awayScore", 0))) or 0.0
        )

    latest = max(scoring, key=total)
    home = _to_number(str(latest.get("homeScore", 0)))
    away = _to_number(str(latest.get("awayScore", 0)))
    clock = latest.get("clock")
    minute = 0
    text = clock.get("displayValue") if isinstance(clock, dict) else clock
    if isinstance(text, str):
        match = re.search(r"\d+", text)
        if match:
            minute = int(match.group(0))
    return int(home or 0), int(away or 0), minute


def _mu(
    home_name: str, away_name: str, rates: dict[str, tuple[float, float, int]], league_avg: float
) -> tuple[float, float, bool]:
    """Return ``(mu_home, mu_away, team_specific)`` expected goals."""

    home = rates.get(_normalize(home_name))
    away = rates.get(_normalize(away_name))
    if home is None or away is None:
        return league_avg * _HOME_ADVANTAGE, league_avg, False
    mu_home, mu_away = expected_goals(
        gf_home=home[0], ga_home=home[1], gp_home=home[2],
        gf_away=away[0], ga_away=away[1], gp_away=away[2],
        league_avg=league_avg, home_adv=_HOME_ADVANTAGE, k=_SHRINK_K,
    )
    return mu_home, mu_away, True


def render_baseline_section(data: MatchDossierData) -> str:
    """Render the statistical 1X2 baseline section for the dossier."""

    sides, status_type = _live_sides(data)
    if "home" not in sides or "away" not in sides:
        return f"{_SECTION_TITLE}\nDati insufficienti per calcolare il baseline."
    home_name = str(sides["home"].get("team_name") or "Home")
    away_name = str(sides["away"].get("team_name") or "Away")
    home_score, away_score = _score(sides["home"]), _score(sides["away"])
    minute, state = _minute_and_state(status_type)
    # The header can lag the play-by-play by a cycle; trust the fresher running
    # score from the plays feed when it shows more goals than the header.
    plays_score = _score_from_plays(data.plays.data)
    if plays_score is not None and sum(plays_score[:2]) > home_score + away_score:
        home_score, away_score, play_minute = plays_score
        minute = max(minute, play_minute)
        state = "in"
    remaining = _minutes_remaining(minute, state)
    rates, league_avg = _standings_rates(data)
    mu_home, mu_away, team_specific = _mu(home_name, away_name, rates, league_avg)
    p_home, p_draw, p_away = live_1x2_probabilities(
        home_score, away_score, remaining, mu_home, mu_away
    )
    clock = {
        "pre": "pre-partita",
        "post": "partita finita",
    }.get(state, f"in corso, {minute}'")
    mu_note = (
        f"μ casa {mu_home:.2f}, μ trasf {mu_away:.2f}"
        + ("" if team_specific else " (medie di default: classifica assente)")
    )
    return (
        f"{_SECTION_TITLE}\n"
        "Prior statistico calibrato da punteggio attuale e tempo rimanente, tarato "
        f"sui gol/partita delle due squadre ({mu_note}). NON è la predizione: è un "
        "ancoraggio. Parti da questi valori e scostati SOLO se le statistiche e la "
        "cronaca lo giustificano (dominio, uomo in più/meno, occasioni), spiegando "
        "il motivo.\n\n"
        f"Stato: {clock} · punteggio {home_score}-{away_score} · minuti rimanenti "
        f"stimati {remaining:.0f}.\n\n"
        "| Esito | Probabilità baseline |\n"
        "| --- | --- |\n"
        f"| 1 ({home_name} casa) | {p_home * 100:.0f}% |\n"
        f"| X (pareggio) | {p_draw * 100:.0f}% |\n"
        f"| 2 ({away_name} trasferta) | {p_away * 100:.0f}% |\n\n"
        + _over_under_table(home_score, away_score, remaining, mu_home, mu_away)
    )


def _over_under_table(
    home_score: int, away_score: int, remaining: float, mu_home: float, mu_away: float
) -> str:
    """Render the Under/Over baseline (same Poisson) for the standard lines."""

    rows = []
    for line in _OU_LINES:
        p_over, p_under = over_under_probabilities(
            home_score, away_score, remaining, mu_home, mu_away, line
        )
        rows.append(f"| {line} | {p_under * 100:.0f}% | {p_over * 100:.0f}% |")
    return (
        "Under/Over (gol totali), stessa Poisson — stesso ancoraggio, scostati con "
        "motivo:\n\n"
        "| Linea | Under | Over |\n"
        "| --- | --- | --- |\n"
        + "\n".join(rows)
    )
