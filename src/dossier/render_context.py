"""Render dossier sections for league standings, leaders, and rankings."""

from __future__ import annotations

from typing import Any, TypeAlias

from src.dossier.render_tools import (
    as_text,
    build_stat_map,
    find_dicts_with_keys,
    first_value,
    render_table,
    sanitize_payload,
)
from src.models.dossier import MatchDossierData
from src.models.no_data import NO_DATA_TEMPLATE

JsonDict: TypeAlias = dict[str, Any]


class MatchContextRenderer:
    """Render sections that provide league context."""

    def __init__(self) -> None:
        """Initialize context renderer."""

    def render_standings(self, data: MatchDossierData) -> str:
        """Render section 10 with trimmed league standings table."""

        payload = sanitize_payload(data.standings.data)
        if payload is None:
            return f"## 10. League standings\n{self._no_data('League standings')}"
        entries = find_dicts_with_keys(payload, {"team", "stats"}, limit=40)
        rows: list[list[str]] = []
        seen_teams: set[str] = set()
        for entry in entries:
            team = entry.get("team", {})
            team_name = as_text(team.get("displayName") or team.get("name"), "Unknown team")
            if team_name in seen_teams:
                continue
            seen_teams.add(team_name)
            stat_map = build_stat_map(entry.get("stats"))
            rows.append(
                [
                    team_name,
                    first_value(stat_map, ["gamesPlayed", "games", "gp"]),
                    first_value(stat_map, ["points", "pts"]),
                    first_value(stat_map, ["goalDifference", "pointDifferential", "gd"]),
                    first_value(stat_map, ["summary", "form", "lastFive", "overall"]),
                ]
            )
            if len(rows) >= 12:
                break
        if not rows:
            return f"## 10. League standings\n{self._no_data('League standings')}"
        legend = "Legend: P = matches played, Pts = points, GD = goal difference, Form = wins-draws-losses."
        return (
            "## 10. League standings\n"
            f"{legend}\n\n"
            + render_table(["Team", "P", "Pts", "GD", "Form"], rows)
        )

    def render_leaders(self, data: MatchDossierData) -> str:
        """Render section 11 with season leaders table."""

        payload = sanitize_payload(data.leaders.data)
        if payload is None:
            return f"## 11. Top scorers and season leaders\n{self._no_data('Top scorers and season leaders')}"
        categories = find_dicts_with_keys(payload, {"leaders"}, limit=30)
        rows: list[list[str]] = []
        for category in categories:
            leaders = category.get("leaders", [])
            if not isinstance(leaders, list) or not leaders:
                continue
            leader = leaders[0] if isinstance(leaders[0], dict) else {}
            athlete = leader.get("athlete", {}) if isinstance(leader, dict) else {}
            team = leader.get("team", {}) if isinstance(leader, dict) else {}
            rows.append(
                [
                    as_text(category.get("displayName") or category.get("name"), "Category"),
                    as_text(athlete.get("displayName") or leader.get("displayName"), "Unknown player"),
                    as_text(leader.get("displayValue") or leader.get("value")),
                    as_text(team.get("displayName") or team.get("name"), "N/A"),
                ]
            )
            if len(rows) >= 10:
                break
        if not rows:
            return f"## 11. Top scorers and season leaders\n{self._no_data('Top scorers and season leaders')}"
        return "## 11. Top scorers and season leaders\n\n" + render_table(["Category", "Leader", "Value", "Team"], rows)

    def render_rankings(self, data: MatchDossierData) -> str:
        """Render section 12 with ranking table when available."""

        payload = sanitize_payload(data.rankings.data)
        if payload is None:
            return f"## 12. Rankings\n{self._no_data('Rankings')}"
        entries = find_dicts_with_keys(payload, {"rank"}, limit=40)
        rows: list[list[str]] = []
        for entry in entries:
            team = entry.get("team", {}) if isinstance(entry.get("team"), dict) else {}
            team_name = as_text(team.get("displayName") or entry.get("displayName") or entry.get("name"))
            rank = as_text(entry.get("rank"), "")
            if not rank:
                continue
            rows.append([rank, team_name, as_text(entry.get("rating") or entry.get("value")), as_text(entry.get("trend"), "Stable")])
            if len(rows) >= 12:
                break
        if not rows:
            return f"## 12. Rankings\n{self._no_data('Rankings')}"
        return "## 12. Rankings\n\n" + render_table(["Rank", "Team", "Rating", "Trend"], rows)

    @staticmethod
    def _no_data(section_name: str) -> str:
        """Build standardized no-data fallback text."""

        return NO_DATA_TEMPLATE.format(section=section_name)
