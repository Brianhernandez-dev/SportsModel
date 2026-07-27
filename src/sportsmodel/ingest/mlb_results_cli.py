import argparse
from collections.abc import Callable
from datetime import date
from typing import Any

from sportsmodel.ingest.mlb_stats import (
    HistoricalResultsBackfillSummary,
    fetch_historical_results,
)


HistoricalResultsFetcher = Callable[
    ...,
    HistoricalResultsBackfillSummary,
]

DEFAULT_START_DATE = date(2026, 6, 1)


def parse_iso_date(value: str) -> date:
    """
    Parse one ISO date for an MLB results command-line argument.
    """

    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from error


def build_parser() -> argparse.ArgumentParser:
    """
    Build the historical MLB results command-line parser.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Backfill finalized MLB results and complete box scores."
        )
    )

    parser.add_argument(
        "--start-date",
        type=parse_iso_date,
        default=DEFAULT_START_DATE,
        help=(
            "First schedule date to process in YYYY-MM-DD format. "
            f"Default: {DEFAULT_START_DATE.isoformat()}."
        ),
    )

    parser.add_argument(
        "--end-date",
        type=parse_iso_date,
        default=None,
        help=(
            "Last schedule date to process in YYYY-MM-DD format. "
            "Default: yesterday."
        ),
    )

    parser.add_argument(
        "--reingest-complete-boxscores",
        action="store_true",
        help=(
            "Download and persist box scores even when the database "
            "already contains two team-stat rows and two starters."
        ),
    )

    return parser


def main(
    argv: list[str] | None = None,
    *,
    historical_results_fetcher: HistoricalResultsFetcher = (
        fetch_historical_results
    ),
) -> int:
    """
    Execute the historical-results command.

    Return a nonzero exit code when any schedule date or box score
    fails so scheduled tasks can detect incomplete runs.
    """

    arguments = build_parser().parse_args(argv)

    summary = historical_results_fetcher(
        start_date=arguments.start_date,
        end_date=arguments.end_date,
        skip_complete_boxscores=(
            not arguments.reingest_complete_boxscores
        ),
    )

    if (
        summary.dates_failed > 0
        or summary.boxscores_failed > 0
    ):
        return 1

    return 0
