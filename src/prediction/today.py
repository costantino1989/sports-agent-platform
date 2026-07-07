"""Build the data for the "today's matches" dashboard page.

Lists every match scheduled for the current day (Europe/Rome) with its kickoff
time and a human-readable status: whether the live loop is tracking it, has
locked a bet, has skipped it (and why), or — for matches not yet started — a
best-effort forecast of whether it will be skipped, inferred from how other
matches of the same league behaved earlier today.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from src.models.schedule import MatchScheduleRecord
    from src.schedule.repositories.status_repo import MatchStatus

ROME = ZoneInfo("Europe/Rome")

# A match kicked off this long ago is certainly over (90' + stoppage + halftime
# never exceeds this). Past it, any "still following live" status is stale — ESPN
# status can lag and never flip to finished within the tracking window — so the
# page shows "Conclusa" instead of a frozen tracking label.
_MATCH_OVER_AFTER = timedelta(hours=3)

# Status kinds that assert the match is being followed live right now; once the
# match is over these are impossible and collapse to "done".
_LIVE_ONLY_KINDS = frozenset({"tracked", "no-book", "evaluating"})

# Reasons whose presence proves the league is covered with play-by-play (the
# match was actually predicted or tracked at least once).
_COVERED_SKIP_REASONS = frozenset({"stable", "locked"})

# Human-readable copy for a match's own persisted decision, keyed by (action,
# reason). Falls back to per-action defaults when a specific pair is absent.
_SKIP_REASONS = {
    "no_play_by_play": (
        "Lega senza play-by-play su ESPN: dossier troppo scarno per una predizione."
    ),
    "no_state": "Nessun dato di stato dal feed ESPN in questo ciclo.",
    "no_dossier": "Dossier non generato in questo ciclo.",
    "no_match": "Record della partita mancante nel DB.",
    "model_unavailable": (
        "Modello non disponibile (es. crediti esauriti): nessuna predizione "
        "generata e nulla salvato, per non sporcare i dati."
    ),
}


def build_today_data(
    matches: list["MatchScheduleRecord"],
    statuses: dict[str, "MatchStatus"],
    now: datetime,
) -> list[dict[str, Any]]:
    """Build the today-page rows from scheduled matches and cycle decisions.

    Args:
        matches: All persisted scheduled matches (any day).
        statuses: Latest per-event cycle decision, keyed by event id.
        now: Current time (its Europe/Rome date selects "today").

    Returns:
        Kickoff-sorted list of view rows for matches scheduled today.
    """

    today = now.astimezone(ROME).date()
    todays = [m for m in matches if m.kickoff_utc.astimezone(ROME).date() == today]
    todays.sort(key=lambda match: match.kickoff_utc)
    uncovered, covered = _league_coverage(matches, statuses)
    return [
        _row(match, statuses.get(match.event_id), now, uncovered, covered)
        for match in todays
    ]


def _league_coverage(
    matches: list["MatchScheduleRecord"], statuses: dict[str, "MatchStatus"]
) -> tuple[set[str], set[str]]:
    """Infer, per league, whether ESPN covers it with play-by-play.

    Returns:
        Pair ``(uncovered, covered)`` of league slugs, learned from how each
        match behaved this cycle: a ``no_play_by_play`` skip marks the league
        uncovered; an actual prediction/track marks it covered.
    """

    by_event = {match.event_id: match for match in matches}
    uncovered: set[str] = set()
    covered: set[str] = set()
    for event_id, status in statuses.items():
        match = by_event.get(event_id)
        if match is None:
            continue
        if status.action == "skip" and status.reason == "no_play_by_play":
            uncovered.add(match.league_slug)
        elif _implies_coverage(status):
            covered.add(match.league_slug)
    return uncovered, covered


def _implies_coverage(status: "MatchStatus") -> bool:
    """Whether a decision proves the match had usable play-by-play data."""

    if status.action in {"predict", "done"}:
        return True
    return status.action == "skip" and status.reason in _COVERED_SKIP_REASONS


def _row(
    match: "MatchScheduleRecord",
    status: "MatchStatus | None",
    now: datetime,
    uncovered: set[str],
    covered: set[str],
) -> dict[str, Any]:
    """Build one view row for a single match."""

    kickoff_rome = match.kickoff_utc.astimezone(ROME)
    kind, label, reason = _classify(match, status, now, uncovered, covered)
    return {
        "eventId": match.event_id,
        "league": match.league_name,
        "leagueSlug": match.league_slug,
        "home": match.home_team,
        "away": match.away_team,
        "kickoffUtc": match.kickoff_utc.isoformat(),
        "time": kickoff_rome.strftime("%H:%M"),
        "statusKind": kind,
        "statusLabel": label,
        "reason": reason,
    }


def _classify(
    match: "MatchScheduleRecord",
    status: "MatchStatus | None",
    now: datetime,
    uncovered: set[str],
    covered: set[str],
) -> tuple[str, str, str]:
    """Return ``(statusKind, statusLabel, reason)`` for a match."""

    kind, label, reason = (
        _classify_known(status)
        if status is not None
        else _classify_pending(match, now, uncovered, covered)
    )
    if kind in _LIVE_ONLY_KINDS and now - match.kickoff_utc >= _MATCH_OVER_AFTER:
        return "done", "Conclusa", ""
    return kind, label, reason


def _classify_known(status: "MatchStatus") -> tuple[str, str, str]:
    """Classify a match that already has a persisted cycle decision."""

    if status.action == "done":
        return "done", "Conclusa", ""
    if status.action == "predict":
        if status.reason == "locked_bet":
            return "bet", "Scommessa bloccata", ""
        if status.reason == "no_usable_odds":
            return "no-book", "Nessuna quota", (
                "Nessuna quota Betfair/Bet365 per questa partita: seguita ma senza "
                "scommessa (non piazzabile sui book scelti)."
            )
        return "tracked", "In tracking (predetta)", ""
    # action == "skip"
    if status.reason == "locked":
        return "bet", "Scommessa bloccata — in attesa esito", ""
    if status.reason == "stable":
        return "tracked", "In tracking (previsione stabile)", ""
    if status.reason == "past_bet_window":
        return "no-bet", "Nessuna scommessa (oltre l'80')", (
            "Superato il minuto 80: mercato ritirato, troppo tardi per scommettere."
        )
    return "skipped", "Saltata", _SKIP_REASONS.get(status.reason, status.reason)


def _classify_pending(
    match: "MatchScheduleRecord",
    now: datetime,
    uncovered: set[str],
    covered: set[str],
) -> tuple[str, str, str]:
    """Classify a match with no decision yet (upcoming or awaiting evaluation)."""

    started = match.kickoff_utc <= now
    if match.league_slug in uncovered:
        return "likely-skip", "Probabile skip", (
            "Lega senza play-by-play su ESPN: altre partite di oggi sono state saltate."
        )
    if started:
        return "evaluating", "In valutazione", ""
    if match.league_slug in covered:
        return "likely-tracked", "Sarà seguita", (
            "Lega con play-by-play su ESPN: verrà valutata all'inizio."
        )
    return "upcoming", "In programma", ""
