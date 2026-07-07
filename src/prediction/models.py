"""Typed models for 1X2 prediction workflow."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PredictionUnavailableError(RuntimeError):
    """Raised when the model cannot produce a usable structured prediction.

    Signals that no prediction exists for this match — because the model call
    failed (e.g. out of credits) or returned no valid structured output. Callers
    must skip the match entirely rather than fabricate a placeholder: a fake
    "X at 50%" would pollute the persisted data used for later analysis.
    """


class RuleSignal(BaseModel):
    """Signal extracted from dossier content to guide uncertainty reduction."""

    name: str = Field(description="Short rule name.")
    triggered: bool = Field(description="Whether the rule is triggered.")
    details: str = Field(description="Human-readable reason for the signal.")
    search_query: str | None = Field(
        default=None,
        description="Suggested focused web query when additional evidence is needed.",
    )
    priority: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Signal priority where 5 means high impact on prediction.",
    )


class PredictionDraft(BaseModel):
    """Model-generated portion of a 1X2 prediction (structured output schema).

    This is the subset of :class:`PredictionResult` the language model is asked
    to produce. Runtime-only fields (``source_file`` and ``outcome``) are added
    by the agent after the model responds.
    """

    match: str = Field(description="Match label in the form Home vs Away.")
    predicted_result: Literal["1", "X", "2"] = Field(
        description="1=home win, X=draw, 2=away win."
    )
    success_probability: int = Field(
        ge=0,
        le=100,
        description="Estimated success probability percentage.",
    )
    rationale: str = Field(description="Detailed rationale supporting the prediction.")
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="List of short evidence references used by the rationale.",
    )
    over_under_result: Literal["Over", "Under"] | None = Field(
        default=None,
        description="Total-goals pick versus the line: 'Over' or 'Under' (null if unknown).",
    )
    over_under_line: float | None = Field(
        default=None,
        description="Over/Under goal line the pick refers to (e.g. 2.5).",
    )
    over_under_probability: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Estimated probability (%) that the Over/Under pick is correct.",
    )


class PredictionResult(BaseModel):
    """Final per-match 1X2 prediction returned by the agent."""

    match: str = Field(description="Match label in the form Home vs Away.")
    predicted_result: Literal["1", "X", "2"] = Field(
        description="1=home win, X=draw, 2=away win."
    )
    success_probability: int = Field(
        ge=0,
        le=100,
        description="Estimated success probability percentage.",
    )
    rationale: str = Field(description="Detailed rationale supporting the prediction.")
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="List of short evidence references used by the rationale.",
    )
    over_under_result: Literal["Over", "Under"] | None = Field(
        default=None,
        description="Total-goals pick versus the line: 'Over' or 'Under' (null if unknown).",
    )
    over_under_line: float | None = Field(
        default=None,
        description="Over/Under goal line the pick refers to (e.g. 2.5).",
    )
    over_under_probability: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Estimated probability (%) that the Over/Under pick is correct.",
    )
    source_file: str = Field(description="Source dossier markdown file name.")
    outcome: str = Field(
        default="",
        description="Empty placeholder to be filled in future with prediction outcome.",
    )

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str) -> str:
        """Ensure rationale contains meaningful text."""

        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Rationale must not be empty.")
        return cleaned

    @field_validator("match")
    @classmethod
    def _validate_match(cls, value: str) -> str:
        """Ensure match label contains meaningful text."""

        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Match must not be empty.")
        return cleaned
