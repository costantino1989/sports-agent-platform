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
    from src.prediction import MatchPredictionAgent, PredictionMarkdownPipeline
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


def build_prediction_agent() -> "MatchPredictionAgent":
    """Build the Agno 1X2 prediction agent from runtime configuration."""

    from src.prediction import MatchPredictionAgent

    runtime_config = get_runtime_config()
    return MatchPredictionAgent(
        model_id=runtime_config.model_id,
        base_url=runtime_config.model_base_url,
        api_key=runtime_config.model_api_key,
        terminal_timeout_seconds=runtime_config.terminal_timeout_seconds,
        model_timeout_seconds=runtime_config.model_timeout_seconds,
        recent_events=runtime_config.prediction_recent_events,
    )


def build_prediction_pipeline() -> "PredictionMarkdownPipeline":
    """Build Agno 1X2 prediction pipeline dependencies."""

    from src.prediction import PredictionMarkdownPipeline

    runtime_config = get_runtime_config()
    return PredictionMarkdownPipeline(
        agent=build_prediction_agent(),
        concurrency=runtime_config.prediction_concurrency,
    )


def run_live_tracking(
    client: EspnSoccerClient,
    schedule_connection: sqlite3.Connection,
    markdown_dir: Path,
) -> None:
    """Run one live-tracking cycle: probe started matches, skip or re-predict.

    Args:
        client: Shared ESPN HTTP client.
        schedule_connection: Active SQLite connection.
        markdown_dir: Directory where dossier markdown files are written.
    """

    from datetime import datetime, timezone

    from src.dossier import DossierDataClient
    from src.prediction.live_probe import parse_match_state
    from src.prediction.service.live import LivePredictionService
    from src.schedule import MatchRepository
    from src.schedule.repositories.bet_repo import BetRepository
    from src.schedule.repositories.prediction_repo import PredictionRepository
    from src.schedule.repositories.status_repo import StatusRepository

    from src.odds.factory import build_api_football_provider, build_odds_provider

    runtime_config = get_runtime_config()
    data_client = DossierDataClient(client=client)
    dossier_action = build_dossier_action(client=client)
    agent = build_prediction_agent()
    # One API-Football provider, shared for odds and the events dossier fallback.
    api_football_provider = build_api_football_provider(runtime_config.api_football_key)
    odds_provider = build_odds_provider(
        odds_api_key=runtime_config.odds_api_key,
        region=runtime_config.odds_api_region,
        bookmaker=runtime_config.odds_api_bookmaker,
        cache_minutes=runtime_config.odds_api_cache_minutes,
        api_football_provider=api_football_provider,
    )

    def prober(match):  # type: ignore[no-untyped-def]
        try:
            summary = data_client.fetch_summary(match.league.slug, match.event.id or "")
        except Exception as error:  # noqa: BLE001 - a probe failure just skips this match
            LOGGER.warn(f"Live probe fetch failed [{match.event.id}]: {error}")
            return None
        return parse_match_state(summary)

    fallback_hint = "".join(
        char for char in runtime_config.odds_fallback_provider.lower() if char.isalnum()
    )
    # Allowed bet sources: Betfair (live exchange), the ESPN fallback book, and
    # API-Football's aggregated LIVE odds ("API-Football Live"). The last is a real
    # in-play price (for faithful simulation), though not a single placeable book.
    bet_provider_hints = tuple(
        h for h in ("betfair", fallback_hint, "apifootball") if h
    )
    service = LivePredictionService(
        match_repo=MatchRepository(connection=schedule_connection),
        prediction_repo=PredictionRepository(connection=schedule_connection),
        bet_repo=BetRepository(connection=schedule_connection),
        status_repo=StatusRepository(connection=schedule_connection),
        bet_provider_hints=bet_provider_hints,
        prober=prober,
        dossier_runner=lambda match: _build_live_dossier(
            match=match,
            dossier_action=dossier_action,
            markdown_dir=markdown_dir,
            odds_provider=odds_provider,
            api_football_provider=api_football_provider,
            fallback_provider=runtime_config.odds_fallback_provider,
        ),
        predictor=agent.predict_from_markdown,
        force_refresh_every=runtime_config.prediction_force_refresh_every,
        lock_confidence=runtime_config.prediction_lock_confidence,
        lock_odds=runtime_config.prediction_lock_odds,
        min_odds=runtime_config.prediction_min_odds,
        kelly_fraction=runtime_config.prediction_kelly_fraction,
        active_window_hours=runtime_config.prediction_active_window_hours,
        max_bet_minute=runtime_config.prediction_max_bet_minute,
        synthetic_odds=runtime_config.prediction_synthetic_odds,
        max_stake_fraction=runtime_config.prediction_max_stake_fraction,
    )
    outcomes = service.run_cycle(now=datetime.now(timezone.utc))

    from src.notify.dispatch import notify_outcomes
    from src.notify.telegram import build_telegram_notifier

    notify_outcomes(
        outcomes=outcomes,
        notifier=build_telegram_notifier(
            runtime_config.telegram_bot_token, runtime_config.telegram_chat_id
        ),
        bet_repo=BetRepository(connection=schedule_connection),
        match_repo=MatchRepository(connection=schedule_connection),
        kelly_multiplier=runtime_config.prediction_kelly_fraction,
        min_odds=runtime_config.prediction_min_odds,
        max_stake_fraction=runtime_config.prediction_max_stake_fraction,
    )

    predicted = sum(1 for outcome in outcomes if outcome.action == "predict")
    skipped = sum(1 for outcome in outcomes if outcome.action == "skip")
    done = sum(1 for outcome in outcomes if outcome.action == "done")
    LOGGER.info(
        f"Live tracking cycle: {len(outcomes)} matches "
        f"(predicted={predicted}, skipped={skipped}, done={done})."
    )


def _build_live_dossier(
    match,  # type: ignore[no-untyped-def]
    dossier_action,  # type: ignore[no-untyped-def]
    markdown_dir: Path,
    odds_provider,  # type: ignore[no-untyped-def]
    api_football_provider,  # type: ignore[no-untyped-def]
    fallback_provider: str,
) -> Path | None:
    """Build a match dossier, then attach real odds and (if ESPN lacks it) events.

    Args:
        match: The match record to build a dossier for.
        dossier_action: Configured dossier action.
        markdown_dir: Output directory for dossier markdown.
        odds_provider: Composite odds provider (Betfair, then API-Football).
        api_football_provider: API-Football provider for the events fallback.
        fallback_provider: ESPN bookmaker used when no real odds are available.

    Returns:
        Path to the (enriched) dossier markdown, or None on build failure.
    """

    from src.dossier.events_fallback import attach_events
    from src.odds.dossier_odds import attach_real_odds

    path = dossier_action.run_one(match=match, output_dir=markdown_dir)
    path = attach_real_odds(
        path, match, odds_provider, fallback_providers=(fallback_provider,)
    )
    return attach_events(path, match, api_football_provider)


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


def select_matches_for_build(
    schedule_connection: sqlite3.Connection,
    markdown_dir: Path,
) -> list:
    """Select matches to build dossiers for from the schedule DB.

    Includes runs due at their 30'/60' checkpoints plus any already-started
    match whose markdown file has not been generated yet.

    Args:
        schedule_connection: Active SQLite connection.
        markdown_dir: Directory where dossier markdown files are written.

    Returns:
        Match records to build dossiers for.
    """

    from datetime import datetime, timezone

    from src.schedule import MatchRepository, RunRepository
    from src.schedule.services.selection import select_matches_to_build

    return select_matches_to_build(
        run_repo=RunRepository(connection=schedule_connection),
        match_repo=MatchRepository(connection=schedule_connection),
        markdown_dir=markdown_dir,
        now_utc=datetime.now(timezone.utc),
    )


DASHBOARD_TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "src"
    / "prediction"
    / "web"
    / "dashboard_template.html"
)

TODAY_TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "src"
    / "prediction"
    / "web"
    / "today_template.html"
)

PREDICTIONS_TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "src"
    / "prediction"
    / "web"
    / "predictions_template.html"
)


def render_dashboard_html(schedule_connection: sqlite3.Connection) -> str:
    """Build the dashboard HTML from persisted bets (fresh from the DB).

    Args:
        schedule_connection: Active SQLite connection.

    Returns:
        The full dashboard HTML with live data injected.
    """

    import json

    from src.prediction.dashboard import build_dashboard_data
    from src.schedule.repositories.bet_repo import BetRepository

    runtime_config = get_runtime_config()
    bets = BetRepository(connection=schedule_connection).list_all()
    matches_meta: dict[str, dict[str, object]] = {}
    for bet in bets:
        row = schedule_connection.execute(
            "SELECT league_slug, league_name, home_team, away_team, kickoff_utc "
            "FROM matches WHERE event_id = ?",
            (bet.event_id,),
        ).fetchone()
        if row is not None:
            matches_meta[bet.event_id] = {
                "league_slug": row["league_slug"],
                "league_name": row["league_name"],
                "home": row["home_team"],
                "away": row["away_team"],
                "kickoff_utc": row["kickoff_utc"],
            }

    data = build_dashboard_data(
        bets=bets,
        matches_meta=matches_meta,
        budgets=[10, 30, 50, 80, 100],
        kelly_fraction=runtime_config.prediction_kelly_fraction,
        min_odds=runtime_config.prediction_min_odds,
        synthetic_stake_fraction=runtime_config.prediction_synthetic_stake_fraction,
        max_stake_fraction=runtime_config.prediction_max_stake_fraction,
    )
    template = DASHBOARD_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__DASHBOARD_JSON__", json.dumps(data, ensure_ascii=False))


def render_predictions_html(schedule_connection: sqlite3.Connection) -> str:
    """Build the predictions page HTML (one card per prediction) from the DB.

    Args:
        schedule_connection: Active SQLite connection.

    Returns:
        The full predictions-page HTML with live data injected.
    """

    import json

    from src.prediction.predictions_page import build_predictions_data
    from src.schedule.repositories.bet_repo import BetRepository
    from src.schedule.repositories.prediction_repo import PredictionRepository

    predictions = PredictionRepository(connection=schedule_connection).list_all()
    matches_meta: dict[str, dict[str, object]] = {}
    for prediction in predictions:
        row = schedule_connection.execute(
            "SELECT league_slug, league_name, home_team, away_team, kickoff_utc "
            "FROM matches WHERE event_id = ?",
            (prediction.event_id,),
        ).fetchone()
        if row is not None:
            matches_meta[prediction.event_id] = {
                "league_slug": row["league_slug"],
                "league_name": row["league_name"],
                "home": row["home_team"],
                "away": row["away_team"],
                "kickoff_utc": row["kickoff_utc"],
            }
    bets_by_event = {
        bet.event_id: {
            "rationale": bet.rationale,
            "evidence": bet.evidence,
            "outcome": bet.outcome,
        }
        for bet in BetRepository(connection=schedule_connection).list_all()
    }
    cards = build_predictions_data(
        predictions=predictions,
        matches_meta=matches_meta,
        bets_by_event=bets_by_event,
    )
    template = PREDICTIONS_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace(
        "__PREDICTIONS_JSON__", json.dumps({"matches": cards}, ensure_ascii=False)
    )


def render_today_html(schedule_connection: sqlite3.Connection) -> str:
    """Build the today's-matches page HTML fresh from the DB.

    Args:
        schedule_connection: Active SQLite connection.

    Returns:
        The full HTML for the today page with live data injected.
    """

    import json
    from datetime import datetime, timezone

    from src.prediction.today import build_today_data
    from src.schedule import MatchRepository
    from src.schedule.repositories.status_repo import StatusRepository

    now = datetime.now(timezone.utc)
    matches = MatchRepository(connection=schedule_connection).list_scheduled_matches()
    statuses = StatusRepository(connection=schedule_connection).list_all()
    rows = build_today_data(matches=matches, statuses=statuses, now=now)
    payload = {"matches": rows, "generatedAt": now.isoformat()}
    template = TODAY_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__TODAY_JSON__", json.dumps(payload, ensure_ascii=False))


def run_export_dashboard(
    schedule_connection: sqlite3.Connection, output_path: Path
) -> None:
    """Write the dashboard HTML to a file.

    Args:
        schedule_connection: Active SQLite connection.
        output_path: Destination HTML file.
    """

    html = render_dashboard_html(schedule_connection)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    LOGGER.info(f"Dashboard exported to {output_path}.")


def run_telegram_summary(db_path: Path) -> None:
    """Send the daily bets/P&L recap to Telegram, if configured.

    Args:
        db_path: SQLite persistence path.
    """

    from src.notify.messages import daily_summary_message
    from src.notify.telegram import build_telegram_notifier
    from src.schedule import ScheduleDatabase
    from src.schedule.repositories.bet_repo import BetRepository

    runtime_config = get_runtime_config()
    notifier = build_telegram_notifier(
        runtime_config.telegram_bot_token, runtime_config.telegram_chat_id
    )
    if notifier is None:
        LOGGER.warn("Telegram not configured (token/chat_id missing); skipping summary.")
        return
    connection = ScheduleDatabase(db_path=db_path).connect()
    try:
        bets = BetRepository(connection=connection).list_all()
    finally:
        connection.close()
    message = daily_summary_message(bets, min_odds=runtime_config.prediction_min_odds)
    sent = notifier.send(message)
    LOGGER.info(f"Telegram daily summary sent={sent} ({len(bets)} bets).")


def serve_dashboard(db_path: Path, port: int) -> None:
    """Serve the always-live dashboard over HTTP on localhost.

    Each request re-reads the database and renders fresh HTML.

    Args:
        db_path: SQLite persistence path.
        port: TCP port to listen on (localhost only).
    """

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from src.schedule import ScheduleDatabase

    def _render_for_path(path: str, connection: sqlite3.Connection) -> str:
        """Pick the renderer for a request path (dashboard or today page)."""

        route = path.rstrip("/")
        if route == "/oggi":
            return render_today_html(connection)
        if route == "/pronostici":
            return render_predictions_html(connection)
        return render_dashboard_html(connection)

    class _DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            path = self.path.split("?", 1)[0]
            connection = ScheduleDatabase(db_path=db_path).connect()
            try:
                body = _render_for_path(path, connection).encode("utf-8")
            except Exception as error:  # noqa: BLE001 - report, don't crash the server
                body = f"<pre>Errore rendering pagina: {error}</pre>".encode()
                self.send_response(500)
            else:
                self.send_response(200)
            finally:
                connection.close()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:  # keep the console quiet
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), _DashboardHandler)
    LOGGER.info(f"Dashboard live su http://127.0.0.1:{port}  (Ctrl+C per fermare)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


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
    mode_group.add_argument(
        "--track-live",
        action="store_true",
        help=(
            "Run one live-tracking cycle: probe started matches and re-predict "
            "only those that changed, skipping confident/stable ones. Meant to be "
            "run periodically (e.g. cron every ~5 minutes)."
        ),
    )
    mode_group.add_argument(
        "--export-dashboard",
        action="store_true",
        help="Generate the web dashboard HTML from persisted bets (match_bets).",
    )
    mode_group.add_argument(
        "--serve",
        action="store_true",
        help="Serve the always-live dashboard over HTTP on localhost.",
    )
    mode_group.add_argument(
        "--telegram-summary",
        action="store_true",
        help="Send the daily bets/P&L recap to Telegram (run once a day via cron).",
    )
    parser.add_argument(
        "--dashboard-output",
        type=Path,
        default=Path("output") / "predictions.html",
        help="Destination HTML file for the exported dashboard.",
    )
    parser.add_argument(
        "--serve-port",
        type=int,
        default=8787,
        help="Port for --serve (localhost).",
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

    if arguments.serve:
        serve_dashboard(db_path=arguments.schedule_db, port=arguments.serve_port)
        return

    if arguments.telegram_summary:
        run_telegram_summary(db_path=arguments.schedule_db)
        return

    if arguments.export_dashboard:
        LOGGER.info("Exporting web dashboard from persisted bets.")
        from src.schedule import ScheduleDatabase

        schedule_db = ScheduleDatabase(db_path=arguments.schedule_db)
        connection = schedule_db.connect()
        try:
            run_export_dashboard(
                schedule_connection=connection,
                output_path=arguments.dashboard_output,
            )
        finally:
            connection.close()
        return

    if arguments.track_live:
        LOGGER.info("Starting live-tracking cycle (skip confident/stable matches).")
        dispatcher, schedule_connection = build_schedule_dispatcher(
            client=shared_client,
            db_path=arguments.schedule_db,
            output_dir=arguments.markdown_dir,
        )
        try:
            from src.schedule import MatchRepository
            from src.schedule.services.auto_heal import ensure_matches_available

            ensure_matches_available(
                MatchRepository(connection=schedule_connection),
                dispatcher.sync_only,
            )
            run_live_tracking(
                client=shared_client,
                schedule_connection=schedule_connection,
                markdown_dir=arguments.markdown_dir,
            )
        finally:
            schedule_connection.close()
        return

    if arguments.build_markdowns and not arguments.predict_1x2:
        LOGGER.info(
            "Selecting due runs plus already-started matches without a dossier yet."
        )
        dispatcher, schedule_connection = build_schedule_dispatcher(
            client=shared_client,
            db_path=arguments.schedule_db,
            output_dir=arguments.markdown_dir,
        )
        try:
            selected_matches = select_matches_for_build(
                schedule_connection=schedule_connection,
                markdown_dir=arguments.markdown_dir,
            )
        finally:
            schedule_connection.close()

        if not selected_matches:
            LOGGER.warn(
                "No eligible in-progress matches found for markdown generation."
            )
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
        LOGGER.info("Starting end-to-end 1X2 workflow.")
        dispatcher, schedule_connection = build_schedule_dispatcher(
            client=shared_client,
            db_path=arguments.schedule_db,
            output_dir=arguments.markdown_dir,
        )
        try:
            selected_matches = select_matches_for_build(
                schedule_connection=schedule_connection,
                markdown_dir=arguments.markdown_dir,
            )
        finally:
            schedule_connection.close()

        dossier_action = build_dossier_action(client=shared_client)
        markdown_files = dossier_action.run(
            matches=selected_matches,
            output_dir=arguments.markdown_dir,
        )
        LOGGER.info("Running Agno 1X2 prediction agent for generated markdown files.")
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
