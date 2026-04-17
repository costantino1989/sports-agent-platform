"""Data models used by the match dossier pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from src.models.live_models import MatchRecordModel

JsonDict: TypeAlias = dict[str, Any]
JsonData: TypeAlias = JsonDict | list[Any]


@dataclass(slots=True, frozen=True)
class EndpointPayload:
    """Represents one fetched endpoint payload with optional fetch error.

    Attributes:
        data: Parsed JSON payload when available.
        error: Endpoint fetch error, when request failed.
    """

    data: JsonData | None
    error: str | None = None

    def has_data(self) -> bool:
        """Return whether the payload contains meaningful data.

        Returns:
            True when endpoint data is present and non-empty.
        """

        if self.data is None:
            return False
        if isinstance(self.data, dict):
            return bool(self.data)
        if isinstance(self.data, list):
            return bool(self.data)
        return True


@dataclass(slots=True, frozen=True)
class PlayerLine:
    """Represents one player line in the markdown dossier.

    Attributes:
        name: Player display name.
        role: Player role or position.
        description: Human-readable player description.
    """

    name: str
    role: str
    description: str


@dataclass(slots=True, frozen=True)
class TeamDossierData:
    """Aggregated team-level payloads for one match dossier.

    Attributes:
        team_id: ESPN team identifier.
        team_name: Team display name.
        side: Home or away side.
        roster: Team roster payload.
        injuries: Team injury report payload.
        schedule: Team schedule payload.
        players: Extracted players for the dossier section.
    """

    team_id: str
    team_name: str
    side: str
    roster: EndpointPayload
    injuries: EndpointPayload
    schedule: EndpointPayload
    players: list[PlayerLine]


@dataclass(slots=True, frozen=True)
class MatchDossierData:
    """Aggregated match-level payloads required by the markdown renderer.

    Attributes:
        match: Normalized live match record.
        output_path: Destination markdown path.
        summary: Match summary payload.
        core_event: Core event payload.
        core_competition: Core competition payload.
        plays: Play-by-play payload.
        situation: Live situation payload.
        probabilities: Win probability payload.
        odds: Odds payload.
        standings: Standings payload.
        leaders: Season leaders payload.
        rankings: Rankings payload.
        news: League news payload.
        teams: Team-level aggregated payloads.
        head_to_head: Extracted head-to-head list.
    """

    match: MatchRecordModel
    output_path: Path
    summary: EndpointPayload
    core_event: EndpointPayload
    core_competition: EndpointPayload
    plays: EndpointPayload
    situation: EndpointPayload
    probabilities: EndpointPayload
    odds: EndpointPayload
    standings: EndpointPayload
    leaders: EndpointPayload
    rankings: EndpointPayload
    news: EndpointPayload
    teams: list[TeamDossierData]
    head_to_head: list[JsonDict]
