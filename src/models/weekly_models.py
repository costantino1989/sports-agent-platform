"""Pydantic models for weekly scheduled soccer matches payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WeeklyBaseModel(BaseModel):
    """Base output model used by weekly match payload objects."""

    model_config = ConfigDict(extra="ignore")


class WeeklyEventModel(WeeklyBaseModel):
    """Event metadata for one scheduled match."""

    id: str | None = Field(default=None, description="ESPN event identifier.")
    uid: str | None = Field(default=None, description="ESPN event UID.")
    date: str | None = Field(default=None, description="Event date-time in ISO format.")
    name: str | None = Field(default=None, description="Full event name.")
    short_name: str | None = Field(default=None, description="Short event name.")
    status: dict[str, Any] | None = Field(
        default=None,
        description="Event status object from ESPN scoreboard.",
    )


class WeeklyCompetitionModel(WeeklyBaseModel):
    """Competition metadata for one scheduled match."""

    id: str | None = Field(default=None, description="ESPN competition identifier.")
    uid: str | None = Field(default=None, description="ESPN competition UID.")
    date: str | None = Field(default=None, description="Competition date-time in ISO format.")
    status: dict[str, Any] | None = Field(
        default=None,
        description="Competition status object from ESPN scoreboard.",
    )


class WeeklyTeamModel(WeeklyBaseModel):
    """Team identifiers and scoreboard info for weekly scheduled matches."""

    side: str | None = Field(
        default=None,
        description="Home/away side in the competition.",
    )
    competitor_id: str | None = Field(
        default=None,
        description="Competition-level competitor identifier.",
    )
    competitor_uid: str | None = Field(
        default=None,
        description="Competition-level competitor UID.",
    )
    team_id: str | None = Field(default=None, description="ESPN team identifier.")
    team_uid: str | None = Field(default=None, description="ESPN team UID.")
    team_slug: str | None = Field(default=None, description="ESPN team slug.")
    abbreviation: str | None = Field(default=None, description="Team abbreviation.")
    display_name: str | None = Field(default=None, description="Team display name.")
    score: str | int | None = Field(
        default=None,
        description="Current scoreboard value when available.",
    )


class WeeklyMatchModel(WeeklyBaseModel):
    """One scheduled match entry for the current week."""

    event: WeeklyEventModel = Field(description="Event metadata.")
    competition: WeeklyCompetitionModel = Field(description="Competition metadata.")
    teams: list[WeeklyTeamModel] = Field(description="Teams involved in the match.")


class WeeklyLeagueScheduleModel(WeeklyBaseModel):
    """Grouped schedule data for one league within a given date."""

    description: str = Field(description="Human-readable league description.")
    matches_by_time: dict[str, list[WeeklyMatchModel]] = Field(
        default_factory=dict,
        description="Matches grouped by kickoff time in HH:MM format.",
    )


WeeklyDataTree = dict[str, dict[str, WeeklyLeagueScheduleModel]]


class WeeklyMatchesPayloadModel(WeeklyBaseModel):
    """Top-level payload persisted for all weekly scheduled matches."""

    generated_at_utc: str = Field(description="UTC timestamp when payload was generated.")
    week_start_utc: str = Field(description="Current week start date (UTC, Monday).")
    week_end_utc: str = Field(description="Current week end date (UTC, Sunday).")
    data: WeeklyDataTree = Field(
        default_factory=dict,
        description=(
            "Nested weekly schedule grouped as date -> league -> "
            "{description, matches_by_time}."
        ),
    )
    match_count: int = Field(default=0, description="Total weekly matches collected.")
    fetch_errors: list[str] = Field(
        default_factory=list,
        description="League/date fetch errors encountered during collection.",
    )
