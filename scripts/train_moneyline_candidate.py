import argparse
from pathlib import Path

from sportsmodel.training import (
    build_moneyline_candidate,
    load_moneyline_training_csv,
)


DEFAULT_DATASET_PATH = Path(
    "data/training/mlb_moneyline_training.csv"
)

DEFAULT_EVALUATION_PATH = Path(
    "data/models/"
    "mlb_moneyline_walk_forward_report_v1_2_0_corrected.json"
)

DEFAULT_OUTPUT_DIRECTORY = Path(
    "data/models/mlb_moneyline_v1"
)


def main() -> None:
    arguments = _parse_arguments()

    dataset = load_moneyline_training_csv(
        arguments.dataset
    )

    result = build_moneyline_candidate(
        dataset,
        model_version=arguments.model_version,
        regularization_c=arguments.regularization_c,
        output_directory=arguments.output_directory,
        evaluation_report_path=(
            arguments.evaluation_report
        ),
        expected_feature_schema_version=(
            arguments.expected_feature_schema
        ),
        source_dataset_path=arguments.dataset,
    )

    print("=" * 72)
    print("SportsModel MLB Moneyline Candidate")
    print("=" * 72)
    print(f"Model version: {arguments.model_version}")
    print(
        "Feature schema: "
        f"{dataset.feature_schema_version}"
    )
    print(f"Training rows: {result.training_rows}")
    print(
        "Regularization C: "
        f"{arguments.regularization_c:g}"
    )
    print(
        "Smoke-test game ID: "
        f"{result.smoke_game_id}"
    )
    print(
        "Smoke-test home-win probability: "
        f"{result.smoke_home_win_probability:.6f}"
    )
    print(f"Model: {result.model_path.resolve()}")
    print(
        f"Manifest: {result.manifest_path.resolve()}"
    )
    print(
        "Evaluation: "
        f"{result.evaluation_path.resolve()}"
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fit and package the selected MLB Moneyline "
            "forward-prediction candidate."
        )
    )

    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
    )
    parser.add_argument(
        "--evaluation-report",
        type=Path,
        default=DEFAULT_EVALUATION_PATH,
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
    )
    parser.add_argument(
        "--model-version",
        default="mlb_moneyline_v1",
    )
    parser.add_argument(
        "--regularization-c",
        type=float,
        default=0.001,
    )
    parser.add_argument(
        "--expected-feature-schema",
        default="1.2.0",
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()
