"""Tests for the per-match live-cycle decision store (match_status)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.schedule.db import ScheduleDatabase
from src.schedule.repositories.status_repo import StatusRepository


class TestStatusRepository:
    def _repo(self, tmp_path: Path) -> StatusRepository:
        database = ScheduleDatabase(db_path=tmp_path / "schedule.db")
        return StatusRepository(connection=database.connect())

    def test_empty_returns_no_statuses(self, tmp_path: Path) -> None:
        assert self._repo(tmp_path).list_all() == {}

    def test_upsert_then_list(self, tmp_path: Path) -> None:
        now = datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc)
        repo = self._repo(tmp_path)
        repo.upsert(event_id="e1", action="skip", reason="no_play_by_play", updated_at=now)
        statuses = repo.list_all()
        assert statuses["e1"].action == "skip"
        assert statuses["e1"].reason == "no_play_by_play"

    def test_upsert_overwrites_previous_decision(self, tmp_path: Path) -> None:
        now = datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc)
        later = datetime(2026, 7, 5, 22, 5, tzinfo=timezone.utc)
        repo = self._repo(tmp_path)
        repo.upsert(event_id="e1", action="skip", reason="no_state", updated_at=now)
        repo.upsert(event_id="e1", action="predict", reason="locked_bet", updated_at=later)
        statuses = repo.list_all()
        assert statuses["e1"].action == "predict"
        assert statuses["e1"].reason == "locked_bet"
