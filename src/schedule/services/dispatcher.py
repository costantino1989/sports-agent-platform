"""Scheduler dispatcher service for minute30/minute60 dossier runs."""

from __future__ import annotations

from pathlib import Path

from src.dossier import MatchDossierAction
from src.models.schedule import ScheduleTickResult
from src.schedule.repositories import MatchRepository, RunRepository
from src.schedule.services.ingestion import ScheduleIngestionService
from src.utils import get_logger

LOGGER = get_logger()


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
        """Run only DB sync without executing due jobs.

        This method enforces API-only ingestion. The configured ingestion
        service must use the ESPN API (WeeklyMatchesAction ->
        WeeklyScoreboardCollector -> EspnSoccerClient). If the configured
        ingestion pipeline does not match this contract, an exception is
        raised to avoid file-based or alternate ingestion paths.
        """

        # Defensive checks to ensure ingestion comes from ESPN API
        try:

            from src.schedule.weekly import WeeklyMatchesAction
            from src.schedule.weekly import WeeklyScoreboardCollector
            from src.espn import EspnSoccerClient
        except Exception as exc:  # pragma: no cover - import safety
            LOGGER.error(f"Failed importing weekly API components: {exc}")
            raise RuntimeError("Required weekly API components are unavailable.") from exc

        weekly_action = getattr(self._ingestion_service, "_weekly_action", None)
        if not isinstance(weekly_action, WeeklyMatchesAction):
            raise RuntimeError(
                "Ingestion service must be configured with WeeklyMatchesAction for API-only sync."
            )

        collector = getattr(weekly_action, "_collector", None)
        if not isinstance(collector, WeeklyScoreboardCollector):
            raise RuntimeError(
                "WeeklyMatchesAction must use WeeklyScoreboardCollector for API-only sync."
            )

        client = getattr(collector, "_client", None)
        if not isinstance(client, EspnSoccerClient):
            raise RuntimeError(
                "WeeklyScoreboardCollector must use EspnSoccerClient for API-only sync."
            )

        # Proceed with the ingestion sync which will use the API-backed weekly action
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
