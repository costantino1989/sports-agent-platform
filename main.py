"""CLI entrypoint for weekly schedules and match markdown dossiers."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from src.dossier import (
    DossierDataClient,
    DossierDataExtractor,
    MatchDossierAction,
    MatchMarkdownRenderer,
)
from src.espn import EspnSoccerClient
from src.schedule.weekly import WeeklyMatchesAction
from src.utils import get_logger, get_runtime_config

if TYPE_CHECKING:
    from src.prediction import PredictionMarkdownPipeline
    from src.schedule import ScheduleDispatcherService

LOGGER = get_logger()


def build_dossier_action(client: EspnSoccerClient) -> MatchDossierAction:
    """Build the match dossier action with concrete dependencies.

    Args:
        client: Shared ESPN HTTP client.

    Returns:
        Configured match dossier action.
    """

    data_client = DossierDataClient(client=client)
    extractor = DossierDataExtractor(data_client=data_client)
    renderer = MatchMarkdownRenderer()
    return MatchDossierAction(
        data_client=data_client,
        extractor=extractor,
        renderer=renderer,
    )


def build_weekly_action(client: EspnSoccerClient) -> WeeklyMatchesAction:
    """Build the weekly matches action with concrete dependencies.

    Args:
        client: Shared ESPN HTTP client.

    Returns:
        Configured weekly matches action.
    """

    return WeeklyMatchesAction(client=client)


def build_prediction_pipeline() -> "PredictionMarkdownPipeline":
    """Build LangGraph 1X2 prediction pipeline dependencies."""

    from src.prediction import MatchPredictionAgent, PredictionMarkdownPipeline

    runtime_config = get_runtime_config()
    agent = MatchPredictionAgent(
        model_name=runtime_config.ollama_model,
        ollama_base_url=runtime_config.ollama_base_url,
        terminal_timeout_seconds=runtime_config.terminal_timeout_seconds,
        model_timeout_seconds=runtime_config.model_timeout_seconds
    )
    return PredictionMarkdownPipeline(agent=agent)


def build_schedule_dispatcher(
        client: EspnSoccerClient,
        db_path: Path,
        output_dir: Path,
) -> tuple["ScheduleDispatcherService", sqlite3.Connection]:
    """Build scheduler dispatcher and keep-alive DB connection.

    Args:
        client: Shared ESPN HTTP client.
        db_path: SQLite persistence path.
        output_dir: Markdown output directory for scheduled runs.

    Returns:
        Pair with configured dispatcher and active SQLite connection.
    """

    from src.schedule import (
        MatchRepository,
        RunRepository,
        ScheduleDatabase,
        ScheduleDispatcherService,
        ScheduleIngestionService,
    )

    runtime_config = get_runtime_config()
    weekly_action = build_weekly_action(client=client)
    dossier_action = build_dossier_action(client=client)
    schedule_db = ScheduleDatabase(db_path=db_path)
    connection = schedule_db.connect()
    match_repository = MatchRepository(connection=connection)
    run_repository = RunRepository(connection=connection)
    ingestion_service = ScheduleIngestionService(
        weekly_action=weekly_action,
        match_repository=match_repository,
        run_repository=run_repository,
    )
    dispatcher = ScheduleDispatcherService(
        ingestion_service=ingestion_service,
        match_repository=match_repository,
        run_repository=run_repository,
        dossier_action=dossier_action,
        output_dir=output_dir,
        stale_running_minutes=runtime_config.schedule_stale_minutes,
        max_attempts=runtime_config.schedule_max_attempts,
    )
    return dispatcher, connection


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments for the action."""

    parser = argparse.ArgumentParser(
        description=(
            "Save current-week scheduled matches, build markdown dossiers for "
            "today's in-progress matches, run end-to-end 1X2 prediction workflow, "
            "or execute scheduler persistence ticks."
        )
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--build-markdowns",
        action="store_true",
        help=(
            "Generate one markdown dossier per match that is in-progress today and "
            "started at least 10 minutes ago."
        ),
    )

    mode_group.add_argument(
        "--predict-1x2",
        action="store_true",
        help=(
            "Run end-to-end flow: build markdown dossiers for eligible live matches "
            "then generate one consolidated 1X2 prediction markdown report."
        ),
    )
    mode_group.add_argument(
        "--schedule-sync",
        action="store_true",
        help="Sync weekly matches into SQLite and ensure minute30/minute60 jobs.",
    )
    parser.add_argument(
        "--markdown-dir",
        type=Path,
        default=Path("output") / "match_markdowns",
        help="Destination directory for per-match markdown dossiers.",
    )

    parser.add_argument(
        "--prediction-output",
        type=Path,
        default=Path("output") / "predictions_1x2.md",
        help="Destination markdown file for consolidated 1X2 predictions.",
    )
    parser.add_argument(
        "--schedule-db",
        type=Path,
        default=Path("output") / "schedule_state.db",
        help="SQLite path used by scheduler persistence.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the action from the command line."""

    arguments = parse_arguments()
    shared_client = EspnSoccerClient()

    if arguments.schedule_sync:
        LOGGER.info(
            "Starting scheduler flow (SQLite persistence + minute30/minute60 triggers)."
        )
        dispatcher, schedule_connection = build_schedule_dispatcher(
            client=shared_client,
            db_path=arguments.schedule_db,
            output_dir=arguments.markdown_dir,
        )
        try:
            result = dispatcher.sync_only()
        finally:
            schedule_connection.close()
        LOGGER.info(
            "Scheduler result: "
            f"synced_matches={result.synced_matches}, ensured_runs={result.ensured_runs}."
        )
        return

    if arguments.build_markdowns and not arguments.predict_1x2:
        LOGGER.info(
            "Selecting today's in-progress matches started at least 10 minutes ago."
        )
        dispatcher, schedule_connection = build_schedule_dispatcher(
            client=shared_client,
            db_path=arguments.schedule_db,
            output_dir=arguments.markdown_dir,
        )
        try:
            from src.schedule import RunRepository
            run_repo = RunRepository(connection=schedule_connection)
            selected_matches = run_repo.get_pending_runs_due()
        finally:
            schedule_connection.close()

        if not selected_matches:
            LOGGER.warn("No eligible in-progress matches found for markdown generation.")
        LOGGER.info("Starting per-match markdown dossier generation.")
        dossier_action = build_dossier_action(client=shared_client)
        markdown_files = dossier_action.run(
            matches=selected_matches,
            output_dir=arguments.markdown_dir,
        )
        LOGGER.info(
            f"Saved {len(markdown_files)} match markdown files to {arguments.markdown_dir}"
        )
        return

    if arguments.predict_1x2:
        LOGGER.info(
            "Starting end-to-end 1X2 workflow."
        )
        dispatcher, schedule_connection = build_schedule_dispatcher(
            client=shared_client,
            db_path=arguments.schedule_db,
            output_dir=arguments.markdown_dir,
        )
        try:
            from src.schedule import RunRepository
            run_repo = RunRepository(connection=schedule_connection)
            selected_matches = run_repo.get_pending_runs_due()
        finally:
            schedule_connection.close()

        dossier_action = build_dossier_action(client=shared_client)
        markdown_files = dossier_action.run(
            matches=selected_matches,
            output_dir=arguments.markdown_dir,
        )
        LOGGER.info("Running LangGraph 1X2 prediction agent for generated markdown files.")
        prediction_pipeline = build_prediction_pipeline()
        prediction_output = prediction_pipeline.run_for_files(
            markdown_files=markdown_files,
            output_path=arguments.prediction_output,
        )
        LOGGER.info(
            f"Saved consolidated prediction markdown ({len(markdown_files)} matches) to "
            f"{prediction_output}"
        )
        return


if __name__ == "__main__":
    main()
