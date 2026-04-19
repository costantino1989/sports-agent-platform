"""Markdown renderer for match prediction dossiers."""

from __future__ import annotations

import json
from typing import Any, TypeAlias

from src.dossier.schedule_events import extract_schedule_events
from src.dossier.render_context import MatchContextRenderer
from src.dossier.render_flow import MatchFlowRenderer
from src.dossier.render_tools import as_text, render_table
from src.models.dossier import EndpointPayload, MatchDossierData, TeamDossierData

JsonDict: TypeAlias = dict[str, Any]

NO_DATA_TEMPLATE = (
    "No data found (source: ESPN API, section: {section}). "
    "Suggested action: verify via web search."
)


class MatchMarkdownRenderer:
    """Render a match dossier into concise, decision-oriented markdown."""

    def __init__(self) -> None:
        """Initialize composed section renderers."""

        flow_renderer = MatchFlowRenderer()
        self._flow_renderer = flow_renderer
        self._context_renderer = MatchContextRenderer()

    def render(self, data: MatchDossierData) -> str:
        """Render the complete markdown dossier for one in-progress match."""

        sections = [
            self._render_match_snapshot(data=data),
            self._render_players(data=data),
            self._render_injuries(data=data),
            self._flow_renderer.render_team_stats(data=data),
            self._flow_renderer.render_head_to_head(data=data),
            self._flow_renderer.render_live_stats(data=data),
            self._flow_renderer.render_news(data=data, section_index=7),
            self._flow_renderer.render_odds(data=data),
            self._flow_renderer.render_match_details(data=data),
            self._context_renderer.render_standings(data=data),
            self._context_renderer.render_leaders(data=data),
            self._context_renderer.render_rankings(data=data),
            self._flow_renderer.render_news(data=data, section_index=13),
            self._render_recent_team_results(data=data),
        ]
        return "\n\n".join(sections).strip() + "\n"

    def _render_match_snapshot(self, data: MatchDossierData) -> str:
        """Render section 1 with live match snapshot."""

        match = data.match
        status = match.event.status or {}
        status_type = status.get("type", {}) if isinstance(status, dict) else {}
        status_detail = "N/A"
        if isinstance(status_type, dict):
            status_detail = str(status_type.get("detail") or status_type.get("description") or "N/A")
        if isinstance(status, dict) and status.get("detail"):
            status_detail = str(status["detail"])
        score_rows: list[list[str]] = []
        scoreline_parts: list[str] = []
        for team in data.match.teams:
            team_name = team.team.display_name or team.team.name or team.side or "Unknown team"
            side = as_text(team.side, "N/A").capitalize()
            score = as_text(team.score)
            score_rows.append([side, team_name, score])
            scoreline_parts.append(f"{team_name} {score}")
        details = "\n".join(
            [
                f"- League: {match.league.name} ({match.league.slug})",
                f"- Match: {match.event.name or match.event.short_name or 'Unknown match'}",
                f"- Date (UTC): {match.event.date or 'N/A'}",
                f"- Match clock/detail: {status_detail}",
                f"- Period: {status_type.get('description', 'N/A') if isinstance(status_type, dict) else 'N/A'}",
                f"- Scoreline: {' - '.join(scoreline_parts) if scoreline_parts else 'N/A'}",
                "",
                "Current score by team:",
                "",
                render_table(["Side", "Team", "Score"], score_rows)
                if score_rows
                else "No score data available.",
            ]
        )
        return f"## 1. Live match snapshot\n{details}"

    def _render_players(self, data: MatchDossierData) -> str:
        """Render section 2 with players and descriptions."""

        lines = ["## 2. Players currently on the field"]
        has_players = False
        missing_team_count = 0
        for team in data.teams:
            formation_suffix = f" - Formation: {team.formation}" if team.formation else ""
            lines.append(f"### {team.team_name} ({team.side}){formation_suffix}")
            lines.append("")
            if not team.players:
                missing_team_count += 1
                lines.append(self._no_data(section_name=f"Players - {team.team_name}"))
                lines.append("")
                continue
            has_players = True
            rows = [
                [player.name, player.role, player.description, player.stats]
                for player in team.players
            ]
            lines.append(
                render_table(
                    ["Player", "Role", "Description", "Season stats"],
                    rows,
                )
            )
            lines.append("")
        if not has_players and missing_team_count == 0:
            lines.append(self._no_data(section_name="Players on the field"))
        return "\n".join(lines)

    def _render_injuries(self, data: MatchDossierData) -> str:
        """Render section 3 with team injury reports."""

        lines = ["## 3. Team injury reports"]
        for team in data.teams:
            lines.append(f"### {team.team_name} ({team.side})")
            lines.append(self._payload_or_no_data(team.injuries, f"Injuries - {team.team_name}"))
        return "\n".join(lines)

    def _payload_or_no_data(self, payload: EndpointPayload, section_name: str) -> str:
        """Render a payload as JSON block, or a standardized no-data message."""

        if not payload.has_data():
            if payload.error:
                return self._no_data(section_name=section_name, reason=payload.error)
            return self._no_data(section_name=section_name)
        return self._json_block(payload.data)

    def _no_data(self, section_name: str, reason: str | None = None) -> str:
        """Build standardized no-data fallback text."""

        text = NO_DATA_TEMPLATE.format(section=section_name)
        if reason:
            return f"{text} Fetch note: {reason}."
        return text

    def _json_block(self, payload: JsonDict | list[Any] | None) -> str:
        """Render payload as a truncated JSON markdown block."""

        serialized = json.dumps(payload, indent=2, ensure_ascii=False)
        limit = 9000
        if len(serialized) > limit:
            serialized = serialized[:limit] + "\n... (truncated)"
        return f"```json\n{serialized}\n```"

    def _render_recent_team_results(self, data: MatchDossierData) -> str:
        """Render section 14 with each team's latest completed 10 results."""

        lines = [
            "## 14. Recent form (last 10 completed matches)",
            "Legend: W = win, D = draw, L = loss.",
            "",
        ]
        has_rows = False
        for team in data.teams:
            lines.append(f"### {team.team_name} ({team.side})")
            rows = self._build_recent_results_rows(team=team, limit=10)
            if not rows:
                lines.append(self._no_data(section_name=f"Recent form - {team.team_name}"))
                lines.append("")
                continue
            has_rows = True
            lines.append(
                render_table(
                    ["Date (UTC)", "Fixture", "Result"],
                    rows,
                )
            )
            lines.append("")
        if not has_rows:
            lines.append(self._no_data(section_name="Recent form (last 10 completed matches)"))
        return "\n".join(lines)

    def _build_recent_results_rows(self, team: TeamDossierData, limit: int) -> list[list[str]]:
        """Build recent completed match result rows for one team."""
        events = extract_schedule_events(team.schedule.data)
        completed_events: list[JsonDict] = []
        for event in events:
            if self._is_event_completed(event=event):
                completed_events.append(event)
        completed_events.sort(key=lambda item: as_text(item.get("date"), ""), reverse=True)
        rows: list[list[str]] = []
        for event in completed_events:
            row = self._build_event_result_row(team_id=team.team_id, event=event)
            if row is None:
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
        return rows

    def _is_event_completed(self, event: JsonDict) -> bool:
        """Return whether a schedule event is marked as completed."""
        competitions = event.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            return False
        competition = competitions[0]
        if not isinstance(competition, dict):
            return False
        status = competition.get("status")
        if not isinstance(status, dict):
            return False
        status_type = status.get("type")
        if not isinstance(status_type, dict):
            return False
        return bool(status_type.get("completed"))

    def _build_event_result_row(self, team_id: str, event: JsonDict) -> list[str] | None:
        """Build one markdown row for a completed event result."""
        competitions = event.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            return None
        competition = competitions[0]
        if not isinstance(competition, dict):
            return None
        competitors = competition.get("competitors")
        if not isinstance(competitors, list):
            return None
        team_competitor, opponent_competitor = self._split_competitors(
            competitors=competitors,
            team_id=team_id,
        )
        if team_competitor is None:
            return None
        fixture = as_text(event.get("name") or event.get("shortName"), "Unknown fixture")
        result = self._format_result(team_competitor=team_competitor, opponent_competitor=opponent_competitor)
        return [as_text(event.get("date")), fixture, result]

    def _split_competitors(
        self,
        competitors: list[Any],
        team_id: str,
    ) -> tuple[JsonDict | None, JsonDict | None]:
        """Split one event competitor list into target team and opponent dictionaries."""
        team_competitor: JsonDict | None = None
        opponent_competitor: JsonDict | None = None
        for competitor in competitors:
            if not isinstance(competitor, dict):
                continue
            competitor_team = competitor.get("team")
            competitor_team_id = ""
            if isinstance(competitor_team, dict):
                competitor_team_id = as_text(competitor_team.get("id"), "")
            if competitor_team_id == team_id:
                team_competitor = competitor
            elif opponent_competitor is None:
                opponent_competitor = competitor
        return team_competitor, opponent_competitor

    def _format_result(
        self,
        team_competitor: JsonDict,
        opponent_competitor: JsonDict | None,
    ) -> str:
        """Format one completed match result from team perspective."""
        team_score = self._extract_score(competitor=team_competitor)
        opponent_score = self._extract_score(competitor=opponent_competitor)
        outcome = self._extract_outcome(
            team_competitor=team_competitor,
            team_score=team_score,
            opponent_score=opponent_score,
        )
        return f"{outcome} {team_score}-{opponent_score}"

    def _extract_score(self, competitor: JsonDict | None) -> str:
        """Extract score text from one competitor dictionary."""
        if competitor is None:
            return "N/A"
        score = competitor.get("score")
        if isinstance(score, dict):
            return as_text(score.get("displayValue") or score.get("value"))
        return as_text(score)

    def _extract_outcome(
        self,
        team_competitor: JsonDict,
        team_score: str,
        opponent_score: str,
    ) -> str:
        """Extract W/D/L outcome from winner flag or score fallback."""
        winner = team_competitor.get("winner")
        if isinstance(winner, bool):
            if winner:
                return "W"
            if team_score != "N/A" and team_score == opponent_score:
                return "D"
            return "L"
        if team_score != "N/A" and team_score == opponent_score:
            return "D"
        return "N/A"
