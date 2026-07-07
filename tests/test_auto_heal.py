"""Tests for the empty-DB self-heal used by the live-tracking flow."""

from __future__ import annotations

from dataclasses import dataclass

from src.schedule.services.auto_heal import ensure_matches_available


@dataclass
class _FakeResult:
    synced_matches: int


class _FakeRepo:
    def __init__(self, count: int) -> None:
        self._count = count

    def count_matches(self) -> int:
        return self._count


class TestEnsureMatchesAvailable:
    def test_syncs_when_db_is_empty(self) -> None:
        calls: list[int] = []

        def sync() -> _FakeResult:
            calls.append(1)
            return _FakeResult(synced_matches=37)

        synced = ensure_matches_available(_FakeRepo(count=0), sync)
        assert synced == 37
        assert calls == [1]  # sync ran exactly once

    def test_does_not_sync_when_matches_present(self) -> None:
        calls: list[int] = []

        def sync() -> _FakeResult:
            calls.append(1)
            return _FakeResult(synced_matches=99)

        synced = ensure_matches_available(_FakeRepo(count=5), sync)
        assert synced == 0
        assert calls == []  # sync never ran
