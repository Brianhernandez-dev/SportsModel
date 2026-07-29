import argparse
from datetime import date

from sportsmodel.ingest.mlb_schedule import (
    sync_mlb_schedule,
)


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    summary = sync_mlb_schedule(
        start_date=arguments.start_date,
        days_ahead=arguments.days_ahead,
    )

    return (
        1
        if summary.dates_failed > 0
        else 0
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize upcoming regular-season MLB "
            "games into the canonical games table."
        )
    )

    parser.add_argument(
        "--start-date",
        type=_parse_iso_date,
        default=None,
        help=(
            "First schedule date in YYYY-MM-DD format. "
            "Default: today."
        ),
    )

    parser.add_argument(
        "--days-ahead",
        type=_parse_nonnegative_integer,
        default=7,
        help=(
            "Number of calendar days after the start "
            "date to include. Default: 7."
        ),
    )

    return parser


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Date must use YYYY-MM-DD format."
        ) from error


def _parse_nonnegative_integer(
    value: str,
) -> int:
    try:
        parsed_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Days ahead must be an integer."
        ) from error

    if parsed_value < 0:
        raise argparse.ArgumentTypeError(
            "Days ahead cannot be negative."
        )

    return parsed_value


if __name__ == "__main__":
    raise SystemExit(main())
