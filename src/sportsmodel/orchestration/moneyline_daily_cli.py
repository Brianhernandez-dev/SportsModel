import argparse
from collections.abc import Callable
from datetime import date
from typing import Any

from sportsmodel.orchestration.moneyline_daily import (
    DEFAULT_SCHEDULE_DAYS_AHEAD,
    run_moneyline_daily_pregame,
)
from sportsmodel.utils.transient_errors import operational_failure_exit_code


def main(
    argv: list[str] | None = None,
    *,
    pregame_runner: Callable[..., Any] = (
        run_moneyline_daily_pregame
    ),
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        result = pregame_runner(
            target_date=arguments.target_date,
            schedule_days_ahead=(
                arguments.schedule_days_ahead
            ),
        )
    except Exception as error:
        print(
            "Daily Moneyline pregame run failed: "
            f"{type(error).__name__}: {error}"
        )
        return operational_failure_exit_code(error)

    print("=" * 76)
    print(
        "SportsModel MLB Moneyline "
        "Daily Pregame Run"
    )
    print("=" * 76)
    print(
        "Workflow run ID:    "
        f"{result.workflow_run_id}"
    )
    print(
        "Target date:        "
        f"{result.target_date}"
    )
    print(
        "Prediction run ID:  "
        f"{result.prediction_run_id}"
    )
    print(
        "Odds run ID:        "
        f"{result.odds_ingestion_run_id}"
    )
    print(
        "Predictions created:"
        f" {result.predictions_created}"
    )
    print(
        "Evaluations saved:  "
        f"{result.evaluations_saved}"
    )
    print(
        "Paper candidates:   "
        f"{result.paper_candidates}"
    )
    print(
        "Odds requests left: "
        f"{result.odds_remaining_requests}"
    )
    print(
        "Pipeline state:     "
        f"{result.pipeline_state}"
    )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run or safely resume the daily MLB "
            "Moneyline pregame pipeline."
        )
    )

    parser.add_argument(
        "--target-date",
        type=_parse_iso_date,
        default=date.today(),
        help=(
            "MLB schedule date in YYYY-MM-DD "
            "format. Default: today."
        ),
    )

    parser.add_argument(
        "--schedule-days-ahead",
        type=_parse_positive_integer,
        default=DEFAULT_SCHEDULE_DAYS_AHEAD,
        help=(
            "Number of schedule dates to synchronize. "
            f"Default: {DEFAULT_SCHEDULE_DAYS_AHEAD}."
        ),
    )

    return parser


def _parse_iso_date(
    value: str,
) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Date must use YYYY-MM-DD format."
        ) from error


def _parse_positive_integer(
    value: str,
) -> int:
    try:
        parsed_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Value must be a positive integer."
        ) from error

    if parsed_value <= 0:
        raise argparse.ArgumentTypeError(
            "Value must be a positive integer."
        )

    return parsed_value


if __name__ == "__main__":
    raise SystemExit(main())


