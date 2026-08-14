import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsmodel.predictions.moneyline_service import (
    DEFAULT_MODEL_DIRECTORY,
    run_moneyline_predictions,
)


PACIFIC_TIME_ZONE = ZoneInfo("America/Los_Angeles")


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)

    try:
        result = run_moneyline_predictions(
            target_date=arguments.target_date,
            model_directory=arguments.model_directory,
            run_type="preview",
        )
    except Exception as error:
        print(
            "Tomorrow Preview failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    print("=" * 84)
    print("SPORTSMODEL MLB MONEYLINE — TOMORROW PREVIEW")
    print("=" * 84)
    print(
        "PREVIEW ONLY — this is not the official "
        "forward-validation card."
    )
    print(
        "The official slate will be regenerated "
        "during the 8:00 AM workflow."
    )
    print()
    print(f"Preview run ID:      {result.moneyline_prediction_run_id}")
    print(f"Target date:         {result.target_date}")
    print(f"Model version:       {result.model_version}")
    print(f"Games received:      {result.games_received}")
    print(f"Predictions created: {result.predictions_created}")
    print(f"Games skipped:       {result.games_skipped}")
    print()
    print("=" * 84)
    print("MODEL LEANS — STRONGEST FIRST")
    print("=" * 84)

    ordered_predictions = sorted(
        result.predictions,
        key=lambda prediction: prediction.predicted_probability,
        reverse=True,
    )

    for rank, prediction in enumerate(ordered_predictions, start=1):
        print()
        print("-" * 84)
        print(
            f"#{rank}  {prediction.away_team_name} at "
            f"{prediction.home_team_name}"
        )
        print(
            "Model lean:        "
            f"{prediction.predicted_team_name} "
            f"{prediction.predicted_probability:.2%}"
        )
        print(
            "Away probability:  "
            f"{prediction.away_win_probability:.2%}"
        )
        print(
            "Home probability:  "
            f"{prediction.home_win_probability:.2%}"
        )
        print(
            "Away starter:      "
            f"{prediction.away_starting_pitcher_name or 'Unavailable'}"
        )
        print(
            "Home starter:      "
            f"{prediction.home_starting_pitcher_name or 'Unavailable'}"
        )
        print(f"Starter coverage:  {prediction.starter_coverage}")
        print(
            "Missing raw values: "
            f"{prediction.missing_raw_value_count}"
        )

    print()
    print("=" * 84)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a clearly separated early Moneyline "
            "preview for tomorrow's MLB slate."
        )
    )
    parser.add_argument(
        "--target-date",
        type=_parse_iso_date,
        default=_tomorrow_pacific(),
        help=(
            "Preview date in YYYY-MM-DD format. "
            "Default: tomorrow in Pacific time."
        ),
    )
    parser.add_argument(
        "--model-directory",
        type=Path,
        default=DEFAULT_MODEL_DIRECTORY,
    )
    return parser


def _tomorrow_pacific() -> date:
    return datetime.now(PACIFIC_TIME_ZONE).date() + timedelta(days=1)


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Date must use YYYY-MM-DD format."
        ) from error


if __name__ == "__main__":
    raise SystemExit(main())
