import argparse
from datetime import date
from pathlib import Path

from sportsmodel.predictions.moneyline_service import (
    DEFAULT_MODEL_DIRECTORY,
    run_moneyline_predictions,
)


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        result = run_moneyline_predictions(
            target_date=arguments.target_date,
            model_directory=(
                arguments.model_directory
            ),
        )
    except Exception as error:
        print(
            "Moneyline prediction run failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    print("=" * 76)
    print(
        "SportsModel MLB Moneyline "
        "Prediction Run"
    )
    print("=" * 76)
    print(
        "Run ID:             "
        f"{result.moneyline_prediction_run_id}"
    )
    print(
        "Target date:        "
        f"{result.target_date}"
    )
    print(
        "Prediction time:    "
        f"{result.prediction_time.isoformat()}"
    )
    print(
        "Model version:      "
        f"{result.model_version}"
    )
    print(
        "Feature schema:     "
        f"{result.feature_schema_version}"
    )
    print(
        "Games received:     "
        f"{result.games_received}"
    )
    print(
        "Predictions created:"
        f" {result.predictions_created}"
    )
    print(
        "Games skipped:      "
        f"{result.games_skipped}"
    )

    for prediction in result.predictions:
        print()
        print("-" * 76)
        print(
            f"{prediction.away_team_name} "
            f"at "
            f"{prediction.home_team_name}"
        )
        print(
            "Game start: "
            f"{prediction.game_start_time.isoformat()}"
        )
        print(
            "Away starter: "
            f"{prediction.away_starting_pitcher_name or 'Unavailable'}"
        )
        print(
            "Home starter: "
            f"{prediction.home_starting_pitcher_name or 'Unavailable'}"
        )
        print(
            "Starter coverage: "
            f"{prediction.starter_coverage}"
        )
        print(
            f"{prediction.away_team_name}: "
            f"{prediction.away_win_probability:.2%}"
        )
        print(
            f"{prediction.home_team_name}: "
            f"{prediction.home_win_probability:.2%}"
        )
        print(
            "Model lean: "
            f"{prediction.predicted_team_name} "
            f"({prediction.predicted_probability:.2%})"
        )
        print(
            "Missing raw values: "
            f"{prediction.missing_raw_value_count}"
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate and persist MLB Moneyline "
            "predictions for one schedule date."
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
        "--model-directory",
        type=Path,
        default=DEFAULT_MODEL_DIRECTORY,
        help=(
            "Directory containing model.joblib "
            "and manifest.json."
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
