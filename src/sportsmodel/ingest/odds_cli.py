import argparse
from collections.abc import Callable
from datetime import date
from typing import Any

from sportsmodel.ingest.odds_api import (
    fetch_live_odds,
)


AUXILIARY_SNAPSHOT_ROLES = (
    "manual",
    "opening",
    "evening",
    "late_night",
    "morning",
    "afternoon",
    "near_close",
)

OddsFetcher = Callable[..., Any]


def build_parser() -> argparse.ArgumentParser:
    """
    Build the live MLB Moneyline odds-ingestion parser.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Fetch and persist an ingestion-only "
            "MLB Moneyline odds snapshot."
        )
    )

    parser.add_argument(
        "--snapshot-role",
        choices=AUXILIARY_SNAPSHOT_ROLES,
        default="manual",
        help=(
            "Logical snapshot role. The entry role is reserved "
            "for the production pregame workflow. "
            "Default: manual."
        ),
    )

    parser.add_argument(
        "--target-date",
        type=_parse_iso_date,
        help=(
            "MLB slate date in YYYY-MM-DD format. "
            "Required for scheduled snapshot roles."
        ),
    )

    return parser


def main(
    argv: list[str] | None = None,
    *,
    odds_fetcher: OddsFetcher = fetch_live_odds,
) -> int:
    """
    Execute one ingestion-only MLB Moneyline odds snapshot.
    """

    parser = build_parser()
    arguments = parser.parse_args(argv)

    if (
        arguments.snapshot_role != "manual"
        and arguments.target_date is None
    ):
        parser.error(
            "--target-date is required for scheduled "
            "snapshot roles."
        )

    try:
        result = odds_fetcher(
            target_date=arguments.target_date,
            snapshot_role=arguments.snapshot_role,
        )
    except Exception as error:
        print(
            "MLB Moneyline odds ingestion failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    print("=" * 72)
    print("SportsModel MLB Moneyline Odds Snapshot")
    print("=" * 72)
    print(
        "Ingestion run ID:  "
        f"{result.odds_ingestion_run_id}"
    )
    print(
        "Target date:       "
        f"{result.target_date}"
    )
    print(
        "Snapshot role:     "
        f"{result.snapshot_role}"
    )
    print(
        "HTTP status:       "
        f"{result.status_code}"
    )
    print(
        "Requests remaining:"
        f" {result.remaining_requests}"
    )
    print(
        "Requests used:     "
        f"{result.used_requests}"
    )
    print(
        "Games returned:    "
        f"{result.games_returned}"
    )
    print(
        "Games processed:   "
        f"{result.games_processed}"
    )
    print(
        "Selections inserted:"
        f" {result.selections_inserted}"
    )
    print(
        "Selections skipped:"
        f" {result.selections_skipped}"
    )

    return 0


def _parse_iso_date(
    value: str,
) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Date must use YYYY-MM-DD format."
        ) from error


if __name__ == "__main__":
    raise SystemExit(main())
