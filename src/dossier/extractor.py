"""Extraction helpers for dossier team/player and head-to-head sections."""

from __future__ import annotations

from collections.abc import Callable

from src.dossier.client import DossierDataClient
from src.dossier.head_to_head import (
    extract_event_phase,
    extract_event_score,
    extract_event_status,
)
from src.espn import EspnApiError
from src.models.dossier import EndpointPayload, JsonData, JsonDict, PlayerLine, TeamDossierData
from src.models.live_models import MatchRecordModel


class DossierDataExtractor:
    """Extract and enrich team-level datasets used by markdown rendering.

    Attributes:
        _data_client: Endpoint client for team and athlete datasets.
    """

    def __init__(self, data_client: DossierDataClient) -> None:
        """Initialize extractor dependencies.

        Args:
            data_client: Endpoint client used for roster/schedule/athlete calls.
        """

        self._data_client = data_client

    def build_teams_data(
        self,
        match: MatchRecordModel,
        league_slug: str,
        safe_fetcher: Callable[[Callable[[], JsonData]], EndpointPayload],
    ) -> list[TeamDossierData]:
        """Build team-level payloads and player lines for one match.

        Args:
            match: Match record.
            league_slug: ESPN league slug.
            safe_fetcher: Safe endpoint wrapper function from action.

        Returns:
            Team dossier entries for both competitors.
        """

        teams_data: list[TeamDossierData] = []
        for team in match.teams:
            team_id = team.team.id or ""
            team_name = team.team.display_name or team.team.name or team.side or "Unknown team"
            roster = safe_fetcher(
                lambda team_id=team_id: self._data_client.fetch_team_roster(league_slug, team_id)
            )
            injuries = safe_fetcher(
                lambda team_id=team_id: self._data_client.fetch_team_injuries(
                    league_slug,
                    team_id,
                )
            )
            schedule = safe_fetcher(
                lambda team_id=team_id: self._data_client.fetch_team_schedule(
                    league_slug,
                    team_id,
                )
            )
            players = self._build_player_lines(league_slug=league_slug, roster=roster)
            teams_data.append(
                TeamDossierData(
                    team_id=team_id,
                    team_name=team_name,
                    side=team.side or "unknown",
                    roster=roster,
                    injuries=injuries,
                    schedule=schedule,
                    players=players,
                )
            )
        return teams_data

    def build_head_to_head(self, teams: list[TeamDossierData]) -> list[JsonDict]:
        """Build basic head-to-head entries from team schedules.

        Args:
            teams: Team-level dossier datasets.

        Returns:
            List of head-to-head event summaries.
        """

        if len(teams) != 2:
            return []
        home_id = teams[0].team_id
        away_id = teams[1].team_id
        events = self._extract_schedule_events(teams[0].schedule.data)
        head_to_head: list[JsonDict] = []
        for event in events:
            competitor_ids = self._extract_competitor_ids(event)
            if home_id in competitor_ids and away_id in competitor_ids:
                head_to_head.append(
                    {
                        "date": event.get("date"),
                        "name": event.get("name") or event.get("shortName"),
                        "phase": extract_event_phase(event),
                        "status": extract_event_status(event),
                        "score": extract_event_score(event),
                    }
                )
        return head_to_head[:10]

    def _build_player_lines(self, league_slug: str, roster: EndpointPayload) -> list[PlayerLine]:
        """Extract and enrich player lines from roster payload.

        Args:
            league_slug: ESPN league slug.
            roster: Team roster endpoint payload.

        Returns:
            Up to eleven player lines suitable for the markdown section.
        """

        athletes = self._extract_athletes(node=roster.data)
        selected = athletes[:11]
        player_lines: list[PlayerLine] = []
        for player in selected:
            name = str(player.get("displayName") or player.get("fullName") or "Unknown player")
            role = self._extract_role(player)
            athlete_id = str(player.get("id") or "")
            athlete_payload = self._fetch_athlete(league_slug=league_slug, athlete_id=athlete_id)
            description = self._build_player_description(player=player, athlete_payload=athlete_payload)
            player_lines.append(PlayerLine(name=name, role=role, description=description))
        return player_lines

    def _fetch_athlete(self, league_slug: str, athlete_id: str) -> EndpointPayload:
        """Fetch one athlete profile with endpoint-level safety."""

        if not athlete_id:
            return EndpointPayload(data=None)
        try:
            payload = self._data_client.fetch_athlete(league_slug, athlete_id)
        except EspnApiError as exc:
            return EndpointPayload(data=None, error=str(exc))
        if isinstance(payload, dict) and not payload:
            return EndpointPayload(data=None)
        if isinstance(payload, list) and not payload:
            return EndpointPayload(data=None)
        return EndpointPayload(data=payload)

    def _extract_athletes(self, node: JsonData | None) -> list[JsonDict]:
        """Recursively extract athlete-like entries from a roster payload."""

        if node is None:
            return []
        collected: list[JsonDict] = []
        self._collect_athletes(node=node, collected=collected)
        unique: dict[str, JsonDict] = {}
        for athlete in collected:
            athlete_id = str(athlete.get("id") or "")
            if not athlete_id or athlete_id in unique:
                continue
            unique[athlete_id] = athlete
        return list(unique.values())

    def _collect_athletes(self, node: JsonData | JsonDict, collected: list[JsonDict]) -> None:
        """Walk nested JSON and collect athlete-like dictionaries."""

        if isinstance(node, dict):
            if "id" in node and ("displayName" in node or "fullName" in node):
                collected.append(node)
            for value in node.values():
                self._collect_athletes(value, collected)
            return
        if isinstance(node, list):
            for item in node:
                self._collect_athletes(item, collected)

    def _extract_role(self, player: JsonDict) -> str:
        """Extract a role string for a player dictionary."""

        position = player.get("position")
        if isinstance(position, dict):
            return str(position.get("displayName") or position.get("name") or "Unknown role")
        if isinstance(position, str):
            return position
        return "Unknown role"

    def _build_player_description(
        self, player: JsonDict, athlete_payload: EndpointPayload
    ) -> str:
        """Build a short description for one player line."""

        details = athlete_payload.data if isinstance(athlete_payload.data, dict) else {}
        nationality = details.get("citizenship") or details.get("nationality")
        jersey = player.get("jersey")
        parts = []
        if jersey:
            parts.append(f"Jersey #{jersey}")
        if nationality:
            parts.append(f"Nationality: {nationality}")
        if athlete_payload.error:
            parts.append("Enrichment unavailable from athlete endpoint")
        return ". ".join(parts) if parts else "No additional athlete details found"

    def _extract_schedule_events(self, payload: JsonData | None) -> list[JsonDict]:
        """Extract schedule event entries from arbitrary nested payload."""

        events: list[JsonDict] = []
        if isinstance(payload, dict):
            direct_events = payload.get("events")
            if isinstance(direct_events, list):
                return [item for item in direct_events if isinstance(item, dict)]
        self._collect_event_nodes(node=payload, collected=events)
        return events

    def _collect_event_nodes(self, node: JsonData | None, collected: list[JsonDict]) -> None:
        """Recursively collect event-like dictionaries from nested payload."""

        if isinstance(node, dict):
            if "competitions" in node and "date" in node:
                collected.append(node)
            for value in node.values():
                self._collect_event_nodes(value, collected)
            return
        if isinstance(node, list):
            for item in node:
                self._collect_event_nodes(item, collected)

    def _extract_competitor_ids(self, event: JsonDict) -> set[str]:
        """Extract competitor IDs from an event dictionary."""

        competitor_ids: set[str] = set()
        competitions = event.get("competitions")
        if not isinstance(competitions, list):
            return competitor_ids
        for competition in competitions:
            competitors = competition.get("competitors", []) if isinstance(competition, dict) else []
            for competitor in competitors:
                team = competitor.get("team", {}) if isinstance(competitor, dict) else {}
                team_id = team.get("id")
                if team_id is not None:
                    competitor_ids.add(str(team_id))
        return competitor_ids

