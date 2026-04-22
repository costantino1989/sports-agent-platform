"""Typed models for scheduling persistence and dispatcher results."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RunType = Literal["minute30", "minute60"]
RunStatus = Literal["pending", "running", "done", "failed", "skipped"]


class ScheduleBaseModel(BaseModel):
    """Base model for scheduler typed records."""

    model_config = ConfigDict(extra="ignore")


class MatchScheduleRecord(ScheduleBaseModel):
    """Persisted match row used by scheduler logic.

    Attributes:
        event_id: ESPN event identifier.
        league_slug: ESPN league slug.
        league_name: Human-readable league name.
        competition_id: ESPN competition identifier.
        kickoff_utc: Kickoff in UTC.
        status_state: Last known ESPN state.
        home_team: Home team display name.
        away_team: Away team display name.
        payload_json: Serialized MatchRecordModel payload.
        updated_at: Last update timestamp in UTC.
    """

    event_id: str = Field(description="ESPN event identifier.")
    league_slug: str = Field(description="ESPN league slug.")
    league_name: str = Field(description="Human-readable league name.")
    competition_id: str = Field(description="ESPN competition identifier.")
    kickoff_utc: datetime = Field(description="Kickoff in UTC.")
    status_state: str = Field(description="Last known ESPN state.")
    home_team: str = Field(description="Home team display name.")
    away_team: str = Field(description="Away team display name.")
    payload_json: str = Field(description="Serialized MatchRecordModel payload.")
    updated_at: datetime = Field(description="Last update timestamp in UTC.")


class ScheduledRunRecord(ScheduleBaseModel):
    """Persisted scheduled run row.

    Attributes:
        run_id: Internal run identifier.
        event_id: ESPN event identifier.
        run_type: Trigger type (`minute30` or `minute60`).
        scheduled_for_utc: Planned execution time in UTC.
        status: Current run status.

        finished_in: Completion time in seconds.
        error: Last error text.
    """

    run_id: int = Field(description="Internal run identifier.")
    event_id: str = Field(description="ESPN event identifier.")
    run_type: RunType = Field(description="Trigger type (`minute30` or `minute60`).")
    scheduled_for_utc: datetime = Field(description="Planned execution time in UTC.")
    status: RunStatus = Field(description="Current run status.")

    finished_in: int | None = Field(
        default=None,
        description="Completion time in seconds.",
    )
    error: str | None = Field(default=None, description="Last error text.")


class MatchSnapshotRecord(ScheduleBaseModel):
    """Append-only snapshot row for historical analysis.

    Attributes:
        event_id: ESPN event identifier.
        captured_at: Snapshot capture timestamp in UTC.
        status_state: Match state at capture time.
        minute: Detected minute from status detail.
        home_score: Home score string.
        away_score: Away score string.
        source: Snapshot source marker.
        payload_json: Optional serialized payload.
    """

    event_id: str = Field(description="ESPN event identifier.")
    captured_at: datetime = Field(description="Snapshot capture timestamp in UTC.")
    status_state: str = Field(description="Match state at capture time.")
    minute: int | None = Field(default=None, ge=0, description="Detected match minute.")
    home_score: str | None = Field(default=None, description="Home score value.")
    away_score: str | None = Field(default=None, description="Away score value.")
    source: str = Field(description="Snapshot source marker.")
    payload_json: str = Field(description="Optional serialized payload.")


class ScheduleTickResult(ScheduleBaseModel):
    """Result object returned by one scheduler tick execution.

    Attributes:
        synced_matches: Number of upserted matches in DB.
        ensured_runs: Number of newly created scheduled runs.
        recovered_runs: Number of stale runs reset from running to pending.
        executed_runs: Number of runs completed successfully.
        failed_runs: Number of runs that failed execution.
        skipped_runs: Number of runs skipped due to missing prerequisites.
    """

    synced_matches: int = Field(ge=0, description="Number of upserted matches in DB.")
    ensured_runs: int = Field(
        ge=0,
        description="Number of newly created scheduled runs.",
    )
    recovered_runs: int = Field(
        ge=0,
        description="Number of stale runs reset from running to pending.",
    )
    executed_runs: int = Field(
        ge=0,
        description="Number of runs completed successfully.",
    )
    failed_runs: int = Field(ge=0, description="Number of runs that failed execution.")
    skipped_runs: int = Field(
        ge=0,
        description="Number of runs skipped due to missing prerequisites.",
    )

