"""Pydantic models for live soccer match payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IgnoreUnknownModel(BaseModel):
    """Base model that ignores extra fields from upstream ESPN responses."""

    model_config = ConfigDict(extra="ignore")


class LeagueModel(IgnoreUnknownModel):
    """League metadata included in the output payload."""

    slug: str = Field(description="ESPN league slug, for example 'ita.1'.")
    name: str = Field(description="Human-readable league display name.")


class TeamModel(IgnoreUnknownModel):
    """Team identifiers and naming metadata."""

    id: str | None = Field(default=None, description="ESPN numeric team identifier.")
    uid: str | None = Field(default=None, description="ESPN unique team UID.")
    slug: str | None = Field(default=None, description="ESPN team slug.")
    abbreviation: str | None = Field(
        default=None,
        description="Short team abbreviation shown in scoreboards.",
    )
    display_name: str | None = Field(
        default=None,
        validation_alias="displayName",
        description="Full display name of the team.",
    )
    location: str | None = Field(
        default=None,
        description="Location or city associated with the team.",
    )
    name: str | None = Field(default=None, description="Team short name.")


class TeamIdentifiersModel(IgnoreUnknownModel):
    """Competitor identifiers and scoreboard values for one side of a match."""

    side: str | None = Field(
        default=None,
        validation_alias="homeAway",
        description="Competitor side in the match, usually 'home' or 'away'.",
    )
    order: int | None = Field(
        default=None,
        description="Display order of the competitor in the competition payload.",
    )
    competitor_id: str | None = Field(
        default=None,
        validation_alias="id",
        description="Competition-level competitor identifier.",
    )
    competitor_uid: str | None = Field(
        default=None,
        validation_alias="uid",
        description="Competition-level unique competitor UID.",
    )
    team: TeamModel = Field(description="Nested team identifiers and names.")
    score: str | int | None = Field(
        default=None,
        description="Current competitor score from the scoreboard endpoint.",
    )
    record: list[dict[str, Any]] | None = Field(
        default=None,
        validation_alias="records",
        description="Team records attached to the competitor (for example, W-D-L).",
    )


class VenueIdentifiersModel(IgnoreUnknownModel):
    """Venue identifiers and venue metadata for a competition."""

    id: str | None = Field(default=None, description="ESPN venue identifier.")
    full_name: str | None = Field(
        default=None,
        validation_alias="fullName",
        description="Official full name of the stadium or venue.",
    )
    address: dict[str, Any] | None = Field(
        default=None,
        description="Venue address object returned by ESPN.",
    )


class EventModel(IgnoreUnknownModel):
    """Event-level identifiers and timing metadata."""

    id: str | None = Field(default=None, description="ESPN event identifier.")
    uid: str | None = Field(default=None, description="ESPN unique event UID.")
    date: str | None = Field(default=None, description="Scheduled event datetime in ISO form.")
    name: str | None = Field(default=None, description="Complete event name.")
    short_name: str | None = Field(
        default=None,
        validation_alias="shortName",
        description="Short event label.",
    )
    season: dict[str, Any] | None = Field(
        default=None,
        description="Season metadata attached to the event.",
    )
    status: dict[str, Any] | None = Field(
        default=None,
        description="Event status object with state and detail fields.",
    )


class CompetitionModel(IgnoreUnknownModel):
    """Competition-level identifiers and status metadata."""

    id: str | None = Field(default=None, description="ESPN competition identifier.")
    uid: str | None = Field(default=None, description="ESPN unique competition UID.")
    date: str | None = Field(
        default=None,
        description="Competition datetime in ISO form when available.",
    )
    status: dict[str, Any] | None = Field(
        default=None,
        description="Competition status object with period and clock data.",
    )
    attendance: int | None = Field(
        default=None,
        description="Reported attendance for the competition.",
    )
    venue: VenueIdentifiersModel | None = Field(
        default=None,
        description="Venue identifiers for the competition.",
    )


class ApiReferencesModel(IgnoreUnknownModel):
    """API references used for follow-up data retrieval."""

    summary: str = Field(description="ESPN Site API summary URL for the event.")
    core_competition: str = Field(
        description="ESPN Core API competition URL for detailed data retrieval.",
    )


class MatchRecordModel(IgnoreUnknownModel):
    """Normalized live match record with all relevant identifiers."""

    league: LeagueModel = Field(description="League identifiers for this match.")
    event: EventModel = Field(description="Event identifiers and status details.")
    competition: CompetitionModel = Field(
        description="Competition identifiers, status, and venue details.",
    )
    teams: list[TeamIdentifiersModel] = Field(
        description="List of competitors with team and score identifiers.",
    )
    api_refs: ApiReferencesModel = Field(
        description="Ready-to-use API URLs for follow-up enrichment.",
    )


class LiveMatchesPayloadModel(IgnoreUnknownModel):
    """Top-level payload persisted to disk for live matches."""

    generated_at_utc: str = Field(
        description="UTC timestamp indicating when this payload was generated.",
    )
    source: str = Field(description="Endpoint template used to query scoreboards.")
    leagues: list[str] = Field(
        description="Configured league slugs requested during collection.",
    )
    live_matches: list[MatchRecordModel] = Field(
        description="All live matches found across configured leagues.",
    )
    live_match_count: int = Field(
        default=0,
        description="Total number of live matches included in this payload.",
    )
