"""CLI entrypoint for weekly schedules and match markdown dossiers."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.dossier import (
    DossierDataClient,
    DossierDataExtractor,
    MatchDossierAction,
    MatchMarkdownRenderer,
    TodayInProgressSelector,
)
from src.espn import EspnSoccerClient
from src.utils import get_logger
from src.weekly import WeeklyMatchesAction

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


def build_today_selector(client: EspnSoccerClient) -> TodayInProgressSelector:
    """Build today's in-progress match selector.

    Args:
        client: Shared ESPN HTTP client.

    Returns:
        Configured selector used before markdown generation.
    """

    return TodayInProgressSelector(client=client)


def build_weekly_action(client: EspnSoccerClient) -> WeeklyMatchesAction:
    """Build the weekly matches action with concrete dependencies.

    Args:
        client: Shared ESPN HTTP client.

    Returns:
        Configured weekly matches action.
    """

    return WeeklyMatchesAction(client=client)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments for the action."""

    parser = argparse.ArgumentParser(
        description=(
            "Save current-week scheduled matches or build markdown dossiers for "
            "today's in-progress matches started at least 10 minutes ago."
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
        "--save-current-week",
        action="store_true",
        help="Save scheduled matches for the current week.",
    )
    parser.add_argument(
        "--markdown-dir",
        type=Path,
        default=Path("output") / "match_markdowns",
        help="Destination directory for per-match markdown dossiers.",
    )
    parser.add_argument(
        "--weekly-output",
        type=Path,
        default=Path("output") / "current_week_matches.json",
        help="Destination JSON path for current-week scheduled matches.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the action from the command line."""

    arguments = parse_arguments()
    shared_client = EspnSoccerClient()
    if arguments.build_markdowns:
        LOGGER.info(
            "Selecting today's in-progress matches started at least 10 minutes ago."
        )
        selector = build_today_selector(client=shared_client)
        selected_matches = selector.run()
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

    if arguments.save_current_week or not arguments.build_markdowns:
        LOGGER.info("Starting current-week match collection.")
        weekly_action = build_weekly_action(client=shared_client)
        weekly_payload = weekly_action.run(output_path=arguments.weekly_output)
        LOGGER.info(
            f"Saved {weekly_payload.match_count} weekly matches to "
            f"{arguments.weekly_output}"
        )


if __name__ == "__main__":
    main()
