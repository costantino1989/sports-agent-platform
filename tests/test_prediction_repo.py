"""Tests for persisting the last prediction/state per match."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.prediction.live_decision import LastPrediction
from src.schedule.db import ScheduleDatabase
from src.schedule.repositories.prediction_repo import PredictionRepository


def _repo(tmp_path: Path) -> PredictionRepository:
    database = ScheduleDatabase(db_path=tmp_path / "schedule.db")
    return PredictionRepository(connection=database.connect())


class TestPredictionRepository:
    def test_get_last_returns_none_when_absent(self, tmp_path: Path) -> None:
        assert _repo(tmp_path).get_last("nope") is None

    def test_upsert_then_get_round_trips(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.upsert(
            event_id="e1",
            predicted_result="2",
            success_probability=85,
            home_score=0,
            away_score=1,
            red_cards=1,
            minute=52,
            cycles_since_full=0,
            status="live",
            updated_at=datetime.now(timezone.utc),
        )
        last = repo.get_last("e1")
        assert isinstance(last, LastPrediction)
        assert last.predicted_result == "2"
        assert last.success_probability == 85
        assert last.away_score == 1
        assert last.red_cards == 1
        assert last.cycles_since_full == 0

    def test_upsert_overwrites_same_event(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        common = dict(
            event_id="e1",
            predicted_result="1",
            success_probability=88,
            home_score=1,
            away_score=0,
            red_cards=0,
            minute=20,
            status="live",
            updated_at=datetime.now(timezone.utc),
        )
        repo.upsert(cycles_since_full=0, **common)
        repo.upsert(cycles_since_full=3, **common)
        assert repo.get_last("e1").cycles_since_full == 3
