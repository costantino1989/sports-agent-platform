"""Tests for match selection: build a dossier for started matches lacking one.

The build selection unions two sources: pending runs due at their 30'/60'
checkpoints, and any match that has already kicked off but whose markdown file
has not been generated yet (regardless of minute).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.dossier.naming import build_dossier_filename
from src.models.live_models import (
    ApiReferencesModel,
    CompetitionModel,
    EventModel,
    LeagueModel,
    MatchRecordModel,
)
from src.models.schedule import MatchScheduleRecord
from src.schedule.db import ScheduleDatabase
from src.schedule.repositories.match_repo import MatchRepository
from src.schedule.services.selection import select_matches_to_build


def _match(event_id: str, slug: str = "ita.1") -> MatchRecordModel:
    return MatchRecordModel(
        league=LeagueModel(slug=slug, name="Serie A"),
        event=EventModel(id=event_id),
        competition=CompetitionModel(id=f"c{event_id}"),
        teams=[],
        api_refs=ApiReferencesModel(
            summary="https://x/summary", core_competition="https://x/comp"
        ),
    )


def _schedule_record(event_id: str, kickoff: datetime, slug: str = "ita.1") -> MatchScheduleRecord:
    now = datetime.now(timezone.utc)
    return MatchScheduleRecord(
        event_id=event_id,
        league_slug=slug,
        league_name="Serie A",
        competition_id=f"c{event_id}",
        kickoff_utc=kickoff,
        home_team="Home",
        away_team="Away",
        payload_json=_match(event_id, slug).model_dump_json(),
        updated_at=now,
    )


class _FakeRunRepo:
    def __init__(self, due: list[MatchRecordModel]) -> None:
        self._due = due

    def get_pending_runs_due(self) -> list[MatchRecordModel]:
        return self._due


class _FakeMatchRepo:
    def __init__(self, started: list[MatchRecordModel]) -> None:
        self._started = started

    def get_started_matches(self, now_utc: datetime) -> list[MatchRecordModel]:
        return self._started


class TestBuildDossierFilename:
    def test_dots_become_underscores_with_event_id(self) -> None:
        assert build_dossier_filename(_match("123", "eng.1")) == "eng_1_123.md"

    def test_missing_event_id_uses_unknown(self) -> None:
        match = _match("x")
        match.event.id = None
        assert build_dossier_filename(match) == "ita_1_unknown.md"


class TestSelectMatchesToBuild:
    def test_due_runs_are_always_included(self, tmp_path: Path) -> None:
        selected = select_matches_to_build(
            run_repo=_FakeRunRepo([_match("1")]),
            match_repo=_FakeMatchRepo([]),
            markdown_dir=tmp_path,
            now_utc=datetime.now(timezone.utc),
        )
        assert [m.event.id for m in selected] == ["1"]

    def test_started_match_without_markdown_is_included(self, tmp_path: Path) -> None:
        selected = select_matches_to_build(
            run_repo=_FakeRunRepo([]),
            match_repo=_FakeMatchRepo([_match("2")]),
            markdown_dir=tmp_path,
            now_utc=datetime.now(timezone.utc),
        )
        assert [m.event.id for m in selected] == ["2"]

    def test_started_match_with_existing_markdown_is_skipped(
        self, tmp_path: Path
    ) -> None:
        match = _match("3")
        (tmp_path / build_dossier_filename(match)).write_text("x", encoding="utf-8")
        selected = select_matches_to_build(
            run_repo=_FakeRunRepo([]),
            match_repo=_FakeMatchRepo([match]),
            markdown_dir=tmp_path,
            now_utc=datetime.now(timezone.utc),
        )
        assert selected == []

    def test_match_in_both_sources_is_not_duplicated(self, tmp_path: Path) -> None:
        selected = select_matches_to_build(
            run_repo=_FakeRunRepo([_match("4")]),
            match_repo=_FakeMatchRepo([_match("4")]),
            markdown_dir=tmp_path,
            now_utc=datetime.now(timezone.utc),
        )
        assert [m.event.id for m in selected] == ["4"]


class TestGetStartedMatches:
    def _repo(self, tmp_path: Path) -> MatchRepository:
        database = ScheduleDatabase(db_path=tmp_path / "schedule.db")
        return MatchRepository(connection=database.connect())

    def test_returns_only_matches_whose_kickoff_has_passed(
        self, tmp_path: Path
    ) -> None:
        now = datetime.now(timezone.utc)
        repo = self._repo(tmp_path)
        repo.upsert_matches(
            [
                _schedule_record("started", kickoff=now - timedelta(minutes=5)),
                _schedule_record("future", kickoff=now + timedelta(hours=2)),
            ]
        )
        started = repo.get_started_matches(now_utc=now)
        assert [m.event.id for m in started] == ["started"]

    def test_active_window_excludes_old_matches(self, tmp_path: Path) -> None:
        now = datetime.now(timezone.utc)
        repo = self._repo(tmp_path)
        repo.upsert_matches(
            [
                _schedule_record("recent", kickoff=now - timedelta(minutes=30)),
                _schedule_record("old", kickoff=now - timedelta(hours=5)),
            ]
        )
        started = repo.get_started_matches(now_utc=now, active_window_hours=3)
        assert [m.event.id for m in started] == ["recent"]


class TestGetMatchRecord:
    def _repo(self, tmp_path: Path) -> MatchRepository:
        database = ScheduleDatabase(db_path=tmp_path / "schedule.db")
        return MatchRepository(connection=database.connect())

    def test_returns_record_regardless_of_window(self, tmp_path: Path) -> None:
        now = datetime.now(timezone.utc)
        repo = self._repo(tmp_path)
        repo.upsert_matches(
            [_schedule_record("old", kickoff=now - timedelta(hours=6))]
        )
        record = repo.get_match_record("old")
        assert record is not None and record.event.id == "old"

    def test_missing_event_returns_none(self, tmp_path: Path) -> None:
        assert self._repo(tmp_path).get_match_record("nope") is None


class TestCountMatches:
    def _repo(self, tmp_path: Path) -> MatchRepository:
        database = ScheduleDatabase(db_path=tmp_path / "schedule.db")
        return MatchRepository(connection=database.connect())

    def test_empty_db_counts_zero(self, tmp_path: Path) -> None:
        assert self._repo(tmp_path).count_matches() == 0

    def test_counts_persisted_matches(self, tmp_path: Path) -> None:
        now = datetime.now(timezone.utc)
        repo = self._repo(tmp_path)
        repo.upsert_matches(
            [
                _schedule_record("a", kickoff=now + timedelta(hours=1)),
                _schedule_record("b", kickoff=now + timedelta(hours=2)),
            ]
        )
        assert repo.count_matches() == 2


class TestListScheduledMatches:
    def _repo(self, tmp_path: Path) -> MatchRepository:
        database = ScheduleDatabase(db_path=tmp_path / "schedule.db")
        return MatchRepository(connection=database.connect())

    def test_empty_returns_empty_list(self, tmp_path: Path) -> None:
        assert self._repo(tmp_path).list_scheduled_matches() == []

    def test_returns_all_rows_with_fields(self, tmp_path: Path) -> None:
        now = datetime.now(timezone.utc)
        repo = self._repo(tmp_path)
        repo.upsert_matches(
            [
                _schedule_record("a", kickoff=now + timedelta(hours=1)),
                _schedule_record("b", kickoff=now + timedelta(hours=2)),
            ]
        )
        rows = repo.list_scheduled_matches()
        assert {row.event_id for row in rows} == {"a", "b"}
        assert all(row.kickoff_utc is not None for row in rows)
