"""Tests for persisting locked bets and their settlement."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.schedule.db import ScheduleDatabase
from src.schedule.repositories.bet_repo import Bet, BetRepository


def _repo(tmp_path: Path) -> BetRepository:
    database = ScheduleDatabase(db_path=tmp_path / "schedule.db")
    return BetRepository(connection=database.connect())


class TestBetRepository:
    def test_is_locked_false_when_absent(self, tmp_path: Path) -> None:
        assert _repo(tmp_path).is_locked("e1") is False

    def test_lock_then_get_pending(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.lock(
            event_id="e1", predicted_result="2", model_prob=84, odds=2.55,
            minute=15, locked_at=datetime.now(timezone.utc),
        )
        assert repo.is_locked("e1") is True
        bet = repo.get("e1")
        assert isinstance(bet, Bet)
        assert bet.predicted_result == "2" and bet.odds == 2.55
        assert bet.settled is False and bet.outcome is None

    def test_settle_records_outcome(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.lock(
            event_id="e1", predicted_result="2", model_prob=84, odds=2.55,
            minute=15, locked_at=datetime.now(timezone.utc),
        )
        repo.settle(event_id="e1", final_home=2, final_away=1, outcome="lost")
        bet = repo.get("e1")
        assert bet.settled is True
        assert bet.outcome == "lost"
        assert (bet.final_home, bet.final_away) == (2, 1)

    def test_lock_persists_bookmaker(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.lock(
            event_id="e1", predicted_result="2", model_prob=88, odds=1.29,
            minute=45, locked_at=datetime.now(timezone.utc),
            bookmaker="DraftKings - Live Odds",
        )
        assert repo.get("e1").bookmaker == "DraftKings - Live Odds"

    def test_bookmaker_defaults_to_none(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.lock(
            event_id="e1", predicted_result="1", model_prob=80, odds=1.5,
            minute=10, locked_at=datetime.now(timezone.utc),
        )
        assert repo.get("e1").bookmaker is None

    def test_lock_persists_synthetic_flag(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.lock(
            event_id="e1", predicted_result="2", model_prob=82, odds=1.2,
            minute=70, locked_at=datetime.now(timezone.utc),
            bookmaker="Sintetica", synthetic=True,
        )
        assert repo.get("e1").synthetic is True

    def test_synthetic_defaults_to_false(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.lock(
            event_id="e1", predicted_result="1", model_prob=80, odds=1.5,
            minute=10, locked_at=datetime.now(timezone.utc),
        )
        assert repo.get("e1").synthetic is False

    def test_list_settled_only_returns_settled(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        now = datetime.now(timezone.utc)
        repo.lock(event_id="won1", predicted_result="1", model_prob=90, odds=1.8, minute=20, locked_at=now)
        repo.lock(event_id="pending1", predicted_result="2", model_prob=85, odds=2.4, minute=10, locked_at=now)
        repo.settle(event_id="won1", final_home=3, final_away=0, outcome="won")
        settled = repo.list_settled()
        assert [b.event_id for b in settled] == ["won1"]
