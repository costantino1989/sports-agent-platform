"""Attach real market odds to a freshly built dossier.

Rather than thread a new field through the ESPN aggregation pipeline, real odds
are injected into the rendered markdown: a Betfair Exchange row is placed at the
top of section 8 so it (a) is what the model reads and (b) is the ``Current``
snapshot the betting parser picks up first, ahead of the ESPN snapshot which is
kept as a secondary reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.odds.models import MatchOdds
from src.utils import get_logger

if TYPE_CHECKING:
    from src.models.live_models import MatchRecordModel
    from src.odds.provider import OddsProvider

LOGGER = get_logger()


@dataclass(frozen=True, slots=True)
class MatchOddsQuery:
    """The fields needed to look up a match's odds, as ESPN describes it."""

    league_slug: str
    home_team: str
    away_team: str
    kickoff_utc: datetime | None


def match_odds_query(match: "MatchRecordModel") -> MatchOddsQuery:
    """Extract league, home/away team names and kickoff from a match record.

    Persisted records may carry the team name in ``name`` (not ``display_name``)
    and leave ``side`` unset, so names fall back to ``name`` and home/away fall
    back to team order (ESPN lists home first) when ``side`` is missing.
    """

    home = away = ""
    for index, competitor in enumerate(match.teams):
        name = competitor.team.display_name or competitor.team.name or ""
        side = competitor.side or _side_from_order(index)
        if side == "home":
            home = name
        elif side == "away":
            away = name
    return MatchOddsQuery(
        league_slug=match.league.slug or "",
        home_team=home,
        away_team=away,
        kickoff_utc=_parse_kickoff(match.event.date if match.event else None),
    )


def _side_from_order(index: int) -> str | None:
    """Assume ESPN's competitor order: first is home, second is away."""

    if index == 0:
        return "home"
    if index == 1:
        return "away"
    return None


def _parse_kickoff(raw: str | None) -> datetime | None:
    """Parse an ESPN ISO date into an aware datetime, or None."""

    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def render_market_odds_block(odds: MatchOdds) -> str:
    """Render the real-odds markdown subsection for section 8."""

    return (
        f"Real market odds — {_pretty_bookmaker(odds.bookmaker)} "
        f"(live, via The Odds API; snapshot {odds.last_update}):\n\n"
        "1X2 odds (decimal):\n\n"
        "| Provider | Snapshot | 1 (Home) | X (Draw) | 2 (Away) |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"| {_pretty_bookmaker(odds.bookmaker)} | Current | "
        f"{odds.home} | {odds.draw} | {odds.away} |\n"
    )


def _pretty_bookmaker(key: str) -> str:
    """Human label for a bookmaker key (Betfair Exchange for betfair_ex_*)."""

    if key.startswith("betfair_ex"):
        return "Betfair Exchange"
    return key


def _norm(text: str) -> str:
    """Lowercase and strip non-alphanumerics (so 'Bet 365' == 'bet365')."""

    return "".join(c for c in text.lower() if c.isalnum())


def extract_bookmaker_row(
    markdown: str, provider_names: list[str]
) -> MatchOdds | None:
    """Read a specific provider's 1X2 row from an ESPN section-8 table.

    Scans the rendered odds table for a row whose provider cell matches any of
    ``provider_names`` (ignoring case/spaces), preferring the ``Current``
    snapshot. Returns ``None`` when that provider is not present.
    """

    wanted = {_norm(name) for name in provider_names}
    fallback: MatchOdds | None = None
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 5:
            continue
        provider, snapshot, home, draw, away = cells[:5]
        provider_norm = _norm(provider)
        if not any(w == provider_norm or w in provider_norm for w in wanted):
            continue
        try:
            prices = tuple(float(v.replace(",", ".")) for v in (home, draw, away))
        except ValueError:
            continue
        odds = MatchOdds(
            home=prices[0],
            draw=prices[1],
            away=prices[2],
            bookmaker=provider,
            last_update="ESPN snapshot",
        )
        if snapshot.strip().lower() == "current":
            return odds
        if fallback is None:
            fallback = odds
    return fallback


def merge_best_odds(
    markdown: str, betfair_odds: MatchOdds | None, fallback_providers: list[str]
) -> str:
    """Inject the best available odds into section 8.

    Preference order: the Betfair Exchange odds from The Odds API, else a named
    fallback provider already present in ESPN's snapshot (e.g. Bet 365), else
    leave the dossier untouched.
    """

    if betfair_odds is not None:
        return inject_market_odds(markdown, betfair_odds)
    fallback = extract_bookmaker_row(markdown, fallback_providers)
    if fallback is not None:
        return inject_market_odds(markdown, fallback)
    return markdown


def inject_market_odds(markdown: str, odds: MatchOdds) -> str:
    """Insert the real-odds block at the top of section 8 (or append it)."""

    block = render_market_odds_block(odds)
    lines = markdown.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.lstrip().startswith("## 8."):
            insert_at = index + 1
            prefix = "" if block.startswith("\n") else "\n"
            lines.insert(insert_at, prefix + block + "\n")
            return "".join(lines)
    suffix = "" if markdown.endswith("\n") else "\n"
    return f"{markdown}{suffix}\n## 8. Odds\n{block}"


def attach_real_odds(
    markdown_path: Path | None,
    match: "MatchRecordModel",
    provider: "OddsProvider | None",
    fallback_providers: tuple[str, ...] = ("Bet 365",),
) -> Path | None:
    """Merge the best available odds into a match's dossier file.

    Preference: Betfair Exchange from The Odds API, else the named fallback
    provider already in ESPN's snapshot (Bet 365 by default), else no change.
    Always safe: any missing input or IO error leaves the file untouched.
    """

    if markdown_path is None:
        return markdown_path
    betfair: MatchOdds | None = None
    query = match_odds_query(match)
    if provider is not None:
        betfair = provider.get_1x2_odds(
            league_slug=query.league_slug,
            home_team=query.home_team,
            away_team=query.away_team,
            kickoff_utc=query.kickoff_utc,
        )
    try:
        original = markdown_path.read_text(encoding="utf-8")
    except OSError as error:
        LOGGER.warn(f"Could not read dossier {markdown_path}: {error}")
        return markdown_path
    merged = merge_best_odds(original, betfair, list(fallback_providers))
    if merged == original:
        LOGGER.info(
            f"No preferred odds for {query.home_team} vs {query.away_team} "
            f"[{query.league_slug}]; keeping ESPN snapshot as-is."
        )
        return markdown_path
    try:
        markdown_path.write_text(merged, encoding="utf-8")
    except OSError as error:
        LOGGER.warn(f"Could not attach odds to {markdown_path}: {error}")
        return markdown_path
    source = (
        _pretty_bookmaker(betfair.bookmaker)
        if betfair is not None
        else f"{fallback_providers[0]} (ESPN fallback)"
    )
    LOGGER.info(f"Attached {source} odds to {markdown_path.name}.")
    return markdown_path
