"""Tests for listing all persisted predictions (for the predictions page)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.schedule.db import ScheduleDatabase
from src.schedule.repositories.prediction_repo import PredictionRepository


def _repo(tmp_path: Path) -> PredictionRepository:
    database = ScheduleDatabase(db_path=tmp_path / "schedule.db")
    return PredictionRepository(connection=database.connect())


class TestListAllPredictions:
    def test_empty(self, tmp_path: Path) -> None:
        assert _repo(tmp_path).list_all() == []

    def test_returns_persisted_rows(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        now = datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc)
        repo.upsert(
            event_id="e1", predicted_result="2", success_probability=73,
            home_score=0, away_score=1, red_cards=0, minute=80,
            cycles_since_full=0, status="live", updated_at=now,
        )
        rows = repo.list_all()
        assert len(rows) == 1
        row = rows[0]
        assert row.event_id == "e1"
        assert row.predicted_result == "2"
        assert row.success_probability == 73
        assert (row.home_score, row.away_score, row.minute) == (0, 1, 80)
        assert row.status == "live"

    def test_stores_and_returns_rationale_and_evidence(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        now = datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc)
        repo.upsert(
            event_id="e1", predicted_result="2", success_probability=88,
            home_score=1, away_score=1, red_cards=0, minute=60,
            cycles_since_full=0, status="live", updated_at=now,
            rationale="Chengdu controlling xG and shots.",
            evidence=["sec:6 shots 14-4", "sec:4 xG 1.9-0.6"],
        )
        row = repo.list_all()[0]
        assert row.rationale == "Chengdu controlling xG and shots."
        assert row.evidence == ["sec:6 shots 14-4", "sec:4 xG 1.9-0.6"]

    def test_stores_and_returns_over_under(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        now = datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc)
        repo.upsert(
            event_id="e1", predicted_result="2", success_probability=73,
            home_score=1, away_score=1, red_cards=0, minute=60,
            cycles_since_full=0, status="live", updated_at=now,
            over_under_result="Over", over_under_line=2.5, over_under_probability=64,
        )
        row = repo.list_all()[0]
        assert row.over_under_result == "Over"
        assert row.over_under_line == 2.5
        assert row.over_under_probability == 64

    def test_skip_cycle_preserves_over_under(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        now = datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc)
        repo.upsert(
            event_id="e1", predicted_result="2", success_probability=73,
            home_score=1, away_score=1, red_cards=0, minute=60,
            cycles_since_full=0, status="live", updated_at=now,
            over_under_result="Over", over_under_line=2.5, over_under_probability=64,
        )
        repo.upsert(  # skip cycle: no O/U passed
            event_id="e1", predicted_result="2", success_probability=73,
            home_score=1, away_score=1, red_cards=0, minute=65,
            cycles_since_full=1, status="live", updated_at=now,
        )
        row = repo.list_all()[0]
        assert row.over_under_result == "Over" and row.over_under_probability == 64

    def test_skip_cycle_preserves_existing_rationale(self, tmp_path: Path) -> None:
        # A re-predict stores the rationale; a later skip cycle re-upserts with no
        # rationale and must NOT wipe it (the reasoning stays visible).
        repo = _repo(tmp_path)
        now = datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc)
        repo.upsert(
            event_id="e1", predicted_result="2", success_probability=88,
            home_score=1, away_score=1, red_cards=0, minute=60,
            cycles_since_full=0, status="live", updated_at=now,
            rationale="Reasoning kept.", evidence=["sec:6"],
        )
        repo.upsert(  # skip cycle: no rationale passed
            event_id="e1", predicted_result="2", success_probability=88,
            home_score=1, away_score=1, red_cards=0, minute=65,
            cycles_since_full=1, status="live", updated_at=now,
        )
        row = repo.list_all()[0]
        assert row.rationale == "Reasoning kept."
        assert row.evidence == ["sec:6"]
        assert row.minute == 65  # the state still updated
