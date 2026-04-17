"""Render dossier sections for probabilities, standings, and summary context."""

from __future__ import annotations

from typing import Any, TypeAlias

from src.dossier.render_flow import MatchFlowRenderer
from src.dossier.render_tools import (
    as_text,
    build_stat_map,
    find_dicts_with_keys,
    first_value,
    render_table,
    sanitize_payload,
)
from src.models.dossier import MatchDossierData

JsonDict: TypeAlias = dict[str, Any]

NO_DATA_TEMPLATE = (
    "No data found (source: ESPN API, section: {section}). "
    "Suggested action: verify via web search."
)


class MatchContextRenderer:
    """Render sections that provide league context and closing summary."""

    def __init__(self, flow_renderer: MatchFlowRenderer) -> None:
        """Initialize context renderer dependencies.

        Args:
            flow_renderer: Live-flow renderer reused for shared signals.
        """

        self._flow_renderer = flow_renderer

    def render_probabilities(self, data: MatchDossierData) -> str:
        """Render section 11 with interpreted win probabilities."""

        payload = sanitize_payload(data.probabilities.data)
        if payload is None:
            return f"## 11. Real-time win probability\n{self._no_data('Real-time win probability')}"
        candidates = find_dicts_with_keys(payload, {"homeWinPercentage", "awayWinPercentage"}, limit=3)
        if not candidates:
            return f"## 11. Real-time win probability\n{self._no_data('Real-time win probability')}"
        point = candidates[0]
        rows = [
            ["Home win", self._format_probability(point.get("homeWinPercentage"))],
            ["Draw", self._format_probability(point.get("drawPercentage"))],
            ["Away win", self._format_probability(point.get("awayWinPercentage"))],
        ]
        return (
            "## 11. Real-time win probability\n"
            "Live model probabilities currently available.\n\n"
            + render_table(["Outcome", "Probability"], rows)
        )

    def render_standings(self, data: MatchDossierData) -> str:
        """Render section 12 with trimmed league standings table."""

        payload = sanitize_payload(data.standings.data)
        if payload is None:
            return f"## 12. League standings\n{self._no_data('League standings')}"
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
            return f"## 12. League standings\n{self._no_data('League standings')}"
        legend = "Legend: P = matches played, Pts = points, GD = goal difference, Form = wins-draws-losses."
        return (
            "## 12. League standings\n"
            f"{legend}\n\n"
            + render_table(["Team", "P", "Pts", "GD", "Form"], rows)
        )

    def render_leaders(self, data: MatchDossierData) -> str:
        """Render section 13 with season leaders table."""

        payload = sanitize_payload(data.leaders.data)
        if payload is None:
            return f"## 13. Top scorers and season leaders\n{self._no_data('Top scorers and season leaders')}"
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
            return f"## 13. Top scorers and season leaders\n{self._no_data('Top scorers and season leaders')}"
        return "## 13. Top scorers and season leaders\n\n" + render_table(["Category", "Leader", "Value", "Team"], rows)

    def render_rankings(self, data: MatchDossierData) -> str:
        """Render section 14 with ranking table when available."""

        payload = sanitize_payload(data.rankings.data)
        if payload is None:
            return f"## 14. Rankings\n{self._no_data('Rankings')}"
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
            return f"## 14. Rankings\n{self._no_data('Rankings')}"
        return "## 14. Rankings\n\n" + render_table(["Rank", "Team", "Rating", "Trend"], rows)

    def render_summary(self, data: MatchDossierData) -> str:
        """Render section 16 with a final decision-oriented narrative."""

        scoreline = self._extract_scoreline(data=data)
        status_detail = self._flow_renderer.extract_status_detail(data=data)
        play_rows = self._flow_renderer.extract_play_rows(data=data, limit=5)
        high_impact = [row for row in play_rows if row[3] != "General play update"]
        lines = [
            "## 16. Full match summary",
            f"- Current state: {scoreline}.",
            f"- Live context: {status_detail}.",
        ]
        if high_impact:
            lines.append("- Recent decisive signals:")
            lines.extend([f"  - {row[0]} | {row[2]} ({row[3]})" for row in high_impact[:3]])
        else:
            lines.append("- No major high-impact events were flagged in recent plays.")
        return "\n".join(lines)

    def _extract_scoreline(self, data: MatchDossierData) -> str:
        """Build scoreline sentence from match teams."""

        parts = []
        for team in data.match.teams:
            name = team.team.display_name or team.team.name or team.side or "Team"
            parts.append(f"{name} {as_text(team.score)}")
        return " vs ".join(parts) if parts else "Scoreline unavailable"

    def _format_probability(self, value: Any) -> str:
        """Format probability values into percentage text."""

        if value is None:
            return "N/A"
        if isinstance(value, (int, float)):
            normalized = value * 100 if value <= 1 else value
            return f"{normalized:.1f}%"
        return as_text(value)

    def _no_data(self, section_name: str) -> str:
        """Build standardized no-data fallback text."""

        return NO_DATA_TEMPLATE.format(section=section_name)
