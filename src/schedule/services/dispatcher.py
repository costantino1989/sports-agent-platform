"""Scheduler dispatcher service for minute30/minute60 dossier runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.dossier import MatchDossierAction
from src.models.live_models import MatchRecordModel
from src.schedule.models import MatchSnapshotRecord, ScheduleTickResult
from src.schedule.repositories import MatchRepository, RunRepository
from src.schedule.services.ingestion import ScheduleIngestionService
from src.utils import get_logger

LOGGER = get_logger()
MINUTE_PATTERN = re.compile(r"(?P<minute>\\d+)")
ODDS_ROW_PATTERN = re.compile(
    r"^\\|\\s*(?P<provider>[^|]+)\\|\\s*(?P<snapshot>[^|]+)\\|\\s*"
    r"(?P<home>[^|]+)\\|\\s*(?P<draw>[^|]+)\\|\\s*(?P<away>[^|]+)\\|$"
)


class ScheduleDispatcherService:
    """Service for syncing weekly matches into SQLite and ensuring minute30/minute60 scheduled runs.

    This dispatcher no longer executes scheduled runs. Use the CLI '--schedule-sync' to populate the DB.
    """

    def __init__(
        self,
        ingestion_service: ScheduleIngestionService,
        match_repository: MatchRepository,
        run_repository: RunRepository,
        dossier_action: MatchDossierAction,
        output_dir: Path,
        stale_running_minutes: int = 30,
        max_attempts: int = 2,
    ) -> None:
        """Initialize dispatcher dependencies.

        Args:
            ingestion_service: Match ingestion service.
            match_repository: Match repository.
            run_repository: Scheduled run repository.
            dossier_action: Dossier generation action.
            output_dir: Markdown output directory.
            stale_running_minutes: Threshold to recover stale running jobs.
            max_attempts: Maximum run attempts before terminal failure.
        """

        self._ingestion_service = ingestion_service
        self._match_repository = match_repository
        self._run_repository = run_repository
        self._dossier_action = dossier_action
        self._output_dir = output_dir
        self._stale_running_minutes = max(5, stale_running_minutes)
        self._max_attempts = max(1, max_attempts)

    def sync_only(self) -> ScheduleTickResult:
        """Run only DB sync without executing due jobs."""

        synced_matches, ensured_runs = self._ingestion_service.sync()
        LOGGER.info(
            f"Schedule sync completed: synced_matches={synced_matches}, ensured_runs={ensured_runs}."
        )
        return ScheduleTickResult(
            synced_matches=synced_matches,
            ensured_runs=ensured_runs,
            recovered_runs=0,
            executed_runs=0,
            failed_runs=0,
            skipped_runs=0,
        )


    def _build_snapshot(self, match: MatchRecordModel, source: str) -> MatchSnapshotRecord:
        """Build append-only snapshot from one match payload."""

        status = match.event.status if isinstance(match.event.status, dict) else {}
        status_type = status.get("type") if isinstance(status.get("type"), dict) else {}
        state = str(status_type.get("state") or "unknown").lower()
        detail = str(status_type.get("detail") or status.get("detail") or "")
        minute = self._extract_minute(detail=detail)
        home_score = self._find_score(match=match, side="home")
        away_score = self._find_score(match=match, side="away")
        return MatchSnapshotRecord(
            event_id=match.event.id or "unknown",
            captured_at=datetime.now(timezone.utc),
            status_state=state,
            minute=minute,
            home_score=home_score,
            away_score=away_score,
            source=source,
            payload_json=json.dumps(match.model_dump(mode="json"), ensure_ascii=False),
        )

    @staticmethod
    def _extract_minute(detail: str) -> int | None:
        """Extract minute integer from ESPN status detail text."""

        match = MINUTE_PATTERN.search(detail)
        if match is None:
            return None
        return int(match.group("minute"))

    @staticmethod
    def _find_score(match: MatchRecordModel, side: str) -> str | None:
        """Find score value for one side from match team list."""

        for team in match.teams:
            if team.side == side:
                return str(team.score) if team.score is not None else None
        return None

    def _persist_odds_snapshots(self, event_id: str, markdown_path: Path) -> None:
        """Parse markdown odds section and append odds snapshots to DB."""

        markdown_text = markdown_path.read_text(encoding="utf-8")
        captured_at = datetime.now(timezone.utc)
        for provider, snapshot, home, draw, away in self._extract_odds_rows(
            markdown_text=markdown_text
        ):
            self._match_repository.add_odds_snapshot(
                event_id=event_id,
                captured_at=captured_at,
                provider=provider,
                snapshot_type=snapshot,
                home_odds=home,
                draw_odds=draw,
                away_odds=away,
                payload_json=json.dumps(
                    {
                        "provider": provider,
                        "snapshot": snapshot,
                        "home_odds": home,
                        "draw_odds": draw,
                        "away_odds": away,
                        "markdown_path": str(markdown_path),
                    },
                    ensure_ascii=False,
                ),
            )

    def _extract_odds_rows(
        self,
        markdown_text: str,
    ) -> list[tuple[str, str, float | None, float | None, float | None]]:
        """Extract three-way odds rows from rendered markdown section 8."""

        rows: list[tuple[str, str, float | None, float | None, float | None]] = []
        for line in markdown_text.splitlines():
            match = ODDS_ROW_PATTERN.match(line.strip())
            if match is None:
                continue
            provider = match.group("provider").strip()
            snapshot = match.group("snapshot").strip()
            if not provider or not snapshot:
                continue
            if provider == "Provider" or snapshot == "Snapshot":
                continue
            if provider.startswith("---"):
                continue
            rows.append(
                (
                    provider,
                    snapshot,
                    self._to_float(match.group("home")),
                    self._to_float(match.group("draw")),
                    self._to_float(match.group("away")),
                )
            )
        return rows

    @staticmethod
    def _to_float(raw_value: str) -> float | None:
        """Convert markdown numeric cell value to float when possible."""

        cleaned = raw_value.strip().replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None

