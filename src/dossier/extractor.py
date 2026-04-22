"""Extraction helpers for team-level dossier datasets."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from src.dossier.client import DossierDataClient
from src.dossier.head_to_head import (
    extract_event_phase,
    extract_event_score,
    extract_event_status,
)
from src.dossier.lineup_players import (
    extract_formation,
    extract_on_field_roster_entries,
    extract_summary_rosters_by_team,
)
from src.dossier.player_season_stats import build_player_season_stats
from src.dossier.schedule_events import extract_competitor_ids, extract_schedule_events
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
        summary_payload: JsonData | None,
        safe_fetcher: Callable[[Callable[[], JsonData]], EndpointPayload],
    ) -> list[TeamDossierData]:
        """Build team-level payloads and current on-field player lines.

        Args:
            match: Match record.
            league_slug: ESPN league slug.
            summary_payload: Match summary payload used to detect current on-field players.
            safe_fetcher: Safe endpoint wrapper function from action.

        Returns:
            Team dossier entries for both competitors.
        """

        summary_rosters = extract_summary_rosters_by_team(summary_payload=summary_payload)
        teams_data: list[TeamDossierData] = []
        for team in match.teams:
            team_id = team.team.id or ""
            team_name = team.team.display_name or team.team.name or team.side or "Unknown team"
            roster = safe_fetcher(
                partial(self._data_client.fetch_team_roster, league_slug, team_id)
            )
            injuries = safe_fetcher(
                partial(self._data_client.fetch_team_injuries, league_slug, team_id)
            )
            schedule = safe_fetcher(
                partial(self._data_client.fetch_team_schedule, league_slug, team_id)
            )
            formation = None
            players: list[PlayerLine] = []
            summary_roster = summary_rosters.get(team_id)
            if isinstance(summary_roster, dict):
                formation = extract_formation(summary_roster=summary_roster)
                players = self._build_on_field_player_lines(
                    league_slug=league_slug,
                    roster_entries=summary_roster.get("roster"),
                    safe_fetcher=safe_fetcher,
                )
            teams_data.append(
                TeamDossierData(
                    team_id=team_id,
                    team_name=team_name,
                    side=team.side or "unknown",
                    formation=formation,
                    roster=roster,
                    injuries=injuries,
                    schedule=schedule,
                    players=players,
                )
            )
        return teams_data

    @staticmethod
    def build_head_to_head(teams: list[TeamDossierData]) -> list[JsonDict]:
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
        events = extract_schedule_events(teams[0].schedule.data)
        head_to_head: list[JsonDict] = []
        for event in events:
            competitor_ids = extract_competitor_ids(event)
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

    def _build_on_field_player_lines(
        self,
        league_slug: str,
        roster_entries: Any,
        safe_fetcher: Callable[[Callable[[], JsonData]], EndpointPayload],
    ) -> list[PlayerLine]:
        """Build player lines for athletes currently on the field.

        Args:
            league_slug: ESPN league slug.
            roster_entries: Summary roster entries for one team.
            safe_fetcher: Safe endpoint wrapper function with shared fetch limiter.

        Returns:
            Player lines for players currently on field.
        """

        on_field_entries = extract_on_field_roster_entries(roster_entries=roster_entries)
        player_lines: list[PlayerLine] = []
        for entry in on_field_entries:
            athlete = entry.get("athlete", {})
            if not isinstance(athlete, dict):
                continue
            name = str(
                athlete.get("displayName")
                or athlete.get("fullName")
                or athlete.get("shortName")
                or "Unknown player"
            )
            role = self._extract_role(entry)
            athlete_id = str(athlete.get("id") or "")
            athlete_payload = self._fetch_athlete(
                league_slug=league_slug,
                athlete_id=athlete_id,
                safe_fetcher=safe_fetcher,
            )
            description = self._build_player_description(player=entry, athlete_payload=athlete_payload)
            stats = self._build_player_season_stats(athlete_payload=athlete_payload, role=role)
            player_lines.append(
                PlayerLine(
                    name=name,
                    role=role,
                    description=description,
                    stats=stats,
                )
            )
        return player_lines

    def _fetch_athlete(
        self,
        league_slug: str,
        athlete_id: str,
        safe_fetcher: Callable[[Callable[[], JsonData]], EndpointPayload],
    ) -> EndpointPayload:
        """Fetch one athlete profile with endpoint-level safety."""

        if not athlete_id:
            return EndpointPayload(data=None)
        athlete_payload = safe_fetcher(
            partial(self._data_client.fetch_athlete, league_slug, athlete_id)
        )
        return self._resolve_athlete_statistics_reference(
            athlete_payload=athlete_payload,
            safe_fetcher=safe_fetcher,
        )

    @staticmethod
    def _extract_role(player: JsonDict) -> str:
        """Extract a role string for a player dictionary."""

        position = player.get("position")
        if isinstance(position, dict):
            return str(position.get("displayName") or position.get("name") or "Unknown role")
        if isinstance(position, str):
            return position
        return "Unknown role"

    @staticmethod
    def _build_player_description(
        player: JsonDict, athlete_payload: EndpointPayload
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

    def _resolve_athlete_statistics_reference(
        self,
        athlete_payload: EndpointPayload,
        safe_fetcher: Callable[[Callable[[], JsonData]], EndpointPayload],
    ) -> EndpointPayload:
        """Resolve athlete statistics reference into an inline payload when available."""

        if not isinstance(athlete_payload.data, dict):
            return athlete_payload
        statistics = athlete_payload.data.get("statistics")
        if not isinstance(statistics, dict):
            return athlete_payload
        reference_url = statistics.get("$ref")
        if not isinstance(reference_url, str) or not reference_url.strip():
            return athlete_payload
        statistics_payload = safe_fetcher(partial(self._data_client.fetch_by_url, reference_url))
        if not statistics_payload.has_data():
            return athlete_payload
        enriched_payload = dict(athlete_payload.data)
        enriched_payload["statistics"] = statistics_payload.data
        return EndpointPayload(data=enriched_payload, error=athlete_payload.error)

    @staticmethod
    def _build_player_season_stats(athlete_payload: EndpointPayload, role: str) -> str:
        """Build concise season stats for one player line."""

        details = athlete_payload.data if isinstance(athlete_payload.data, dict) else None
        return build_player_season_stats(athlete_data=details, role=role)
