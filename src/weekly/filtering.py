"""Filtering helpers for excluding already-started weekly matches."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypeAlias

JsonDict: TypeAlias = dict[str, Any]


class WeeklyUpcomingFilter:
    """Filter that keeps only matches not started yet."""

    def is_upcoming_match(
        self,
        event: JsonDict,
        competition: JsonDict,
        now_utc: datetime,
    ) -> bool:
        """Return whether a match is still to be played.

        Args:
            event: Event payload dictionary.
            competition: Competition payload dictionary.
            now_utc: Current UTC timestamp.

        Returns:
            True when the match has not started yet.
        """

        event_status = event.get("status")
        competition_status = competition.get("status")
        states = {
            self._extract_status_state(event_status),
            self._extract_status_state(competition_status),
        }
        if "post" in states or "in" in states:
            return False
        if self._extract_status_completed(event_status):
            return False
        if self._extract_status_completed(competition_status):
            return False

        kickoff = self._extract_kickoff_datetime(event=event, competition=competition)
        if kickoff is None:
            return "pre" in states
        return kickoff > now_utc

    def _extract_status_state(self, status: Any) -> str | None:
        """Extract status.type.state from an event or competition status object.

        Args:
            status: Status dictionary or arbitrary payload.

        Returns:
            Lowercased state string when available, otherwise None.
        """

        if not isinstance(status, dict):
            return None
        status_type = status.get("type")
        if not isinstance(status_type, dict):
            return None
        state = status_type.get("state")
        if not isinstance(state, str):
            return None
        return state.lower()

    def _extract_status_completed(self, status: Any) -> bool:
        """Extract completion flag from status object.

        Args:
            status: Status dictionary or arbitrary payload.

        Returns:
            True when the status explicitly marks the match as completed.
        """

        if not isinstance(status, dict):
            return False
        completed = status.get("completed")
        return bool(completed is True)

    def _extract_kickoff_datetime(
        self,
        event: JsonDict,
        competition: JsonDict,
    ) -> datetime | None:
        """Extract kickoff datetime from event/competition payloads.

        Args:
            event: Event dictionary.
            competition: Competition dictionary.

        Returns:
            Parsed UTC datetime when available; otherwise None.
        """

        for raw_value in (event.get("date"), competition.get("date")):
            parsed = self._parse_datetime(value=raw_value)
            if parsed:
                return parsed
        return None

    def _parse_datetime(self, value: Any) -> datetime | None:
        """Parse ESPN datetime values into UTC datetimes.

        Args:
            value: Date value from payload.

        Returns:
            UTC datetime when parse succeeds; otherwise None.
        """

        if not isinstance(value, str) or not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
