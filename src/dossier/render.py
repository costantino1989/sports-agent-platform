"""Markdown renderer for match prediction dossiers."""

from __future__ import annotations

import json
from typing import Any, TypeAlias

from src.dossier.render_context import MatchContextRenderer
from src.dossier.render_flow import MatchFlowRenderer
from src.dossier.render_tools import as_text, render_table
from src.models.dossier import EndpointPayload, MatchDossierData

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
        self._context_renderer = MatchContextRenderer(flow_renderer=flow_renderer)

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
            self._context_renderer.render_probabilities(data=data),
            self._context_renderer.render_standings(data=data),
            self._context_renderer.render_leaders(data=data),
            self._context_renderer.render_rankings(data=data),
            self._flow_renderer.render_news(data=data, section_index=15),
            self._context_renderer.render_summary(data=data),
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
            formation_suffix = f" | Formation: {team.formation}" if team.formation else ""
            lines.append(f"### {team.team_name} ({team.side}){formation_suffix}")
            if not team.players:
                missing_team_count += 1
                lines.append(self._no_data(section_name=f"Players - {team.team_name}"))
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
