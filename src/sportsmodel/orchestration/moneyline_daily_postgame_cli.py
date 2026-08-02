import argparse
from collections.abc import Callable
from datetime import date
from typing import Any

from sportsmodel.orchestration.moneyline_daily import (
    run_moneyline_daily_postgame,
)


def main(
    argv: list[str] | None = None,
    *,
    postgame_runner: Callable[..., Any] = (
        run_moneyline_daily_postgame
    ),
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        result = postgame_runner(
            target_date=arguments.target_date,
        )
    except Exception as error:
        print(
            "Daily Moneyline postgame run failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    print("=" * 76)
    print(
        "SportsModel MLB Moneyline "
        "Daily Postgame Run"
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
        "Games processed:    "
        f"{result.games_processed}"
    )
    print(
        "Box scores processed:"
        f" {result.boxscores_processed}"
    )
    print(
        "Settlements saved:  "
        f"{result.settlements_saved}"
    )
    print(
        "Pending candidates: "
        f"{result.pending_candidates}"
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
            "Moneyline postgame pipeline."
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


if __name__ == "__main__":
    raise SystemExit(main())
