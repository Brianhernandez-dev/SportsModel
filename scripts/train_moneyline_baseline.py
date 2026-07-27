import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sportsmodel.training.moneyline_baseline import (
    ClassificationMetrics,
    FeatureCoefficient,
    MoneylineBaselineEvaluation,
    load_moneyline_training_csv,
    save_trained_moneyline_baseline,
    train_moneyline_baseline,
)


DEFAULT_DATASET_PATH = Path(
    "data/training/mlb_moneyline_training.csv"
)

DEFAULT_MODEL_OUTPUT_PATH = Path(
    "data/models/mlb_moneyline_baseline.joblib"
)

DEFAULT_REPORT_OUTPUT_PATH = Path(
    "data/models/mlb_moneyline_baseline_report.json"
)


def main() -> None:
    arguments = _parse_arguments()

    dataset = load_moneyline_training_csv(
        arguments.dataset
    )

    evaluation = train_moneyline_baseline(
        dataset,
        test_fraction=arguments.test_fraction,
        top_feature_count=arguments.top_features,
    )

    save_trained_moneyline_baseline(
        evaluation.artifact,
        arguments.model_output,
    )

    report = _build_report(
        evaluation=evaluation,
        dataset_path=arguments.dataset,
        model_output_path=arguments.model_output,
    )

    _write_report(
        path=arguments.report_output,
        report=report,
    )

    _print_evaluation(
        evaluation=evaluation,
        model_output_path=arguments.model_output,
        report_output_path=arguments.report_output,
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Train and evaluate the MLB Moneyline logistic "
            "regression baseline."
        )
    )

    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help=(
            "Generated Moneyline training CSV."
        ),
    )

    parser.add_argument(
        "--model-output",
        type=Path,
        default=DEFAULT_MODEL_OUTPUT_PATH,
        help=(
            "Destination for the serialized fitted model."
        ),
    )

    parser.add_argument(
        "--report-output",
        type=Path,
        default=DEFAULT_REPORT_OUTPUT_PATH,
        help=(
            "Destination for the JSON evaluation report."
        ),
    )

    parser.add_argument(
        "--test-fraction",
        type=float,
        default=0.20,
        help=(
            "Fraction of the latest chronological games "
            "reserved for testing."
        ),
    )

    parser.add_argument(
        "--top-features",
        type=int,
        default=15,
        help=(
            "Number of positive and negative coefficients "
            "included in the report."
        ),
    )

    return parser.parse_args()


def _build_report(
    *,
    evaluation: MoneylineBaselineEvaluation,
    dataset_path: Path,
    model_output_path: Path,
) -> dict[str, Any]:
    return {
        "model_name": "mlb_moneyline_baseline",
        "model_type": "logistic_regression",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "dataset_path": str(dataset_path.resolve()),
        "model_output_path": str(
            model_output_path.resolve()
        ),
        "feature_schema_version": (
            evaluation.artifact.feature_schema_version
        ),
        "training_rows": evaluation.training_rows,
        "test_rows": evaluation.test_rows,
        "training_start_time": (
            evaluation.training_start_time.isoformat()
        ),
        "training_end_time": (
            evaluation.training_end_time.isoformat()
        ),
        "test_start_time": (
            evaluation.test_start_time.isoformat()
        ),
        "test_end_time": (
            evaluation.test_end_time.isoformat()
        ),
        "training_home_win_rate": (
            evaluation.training_home_win_rate
        ),
        "active_feature_count": len(
            evaluation.artifact.active_feature_names
        ),
        "dropped_all_missing_features": list(
            evaluation.artifact
            .dropped_all_missing_features
        ),
        "dropped_constant_features": list(
            evaluation.artifact
            .dropped_constant_features
        ),
        "model_metrics": _metrics_to_mapping(
            evaluation.model_metrics
        ),
        "naive_baseline_metrics": _metrics_to_mapping(
            evaluation.naive_baseline_metrics
        ),
        "metric_deltas": {
            "accuracy": (
                evaluation.model_metrics.accuracy
                - evaluation.naive_baseline_metrics.accuracy
            ),
            "log_loss": (
                evaluation.model_metrics.log_loss
                - evaluation.naive_baseline_metrics.log_loss
            ),
            "brier_score": (
                evaluation.model_metrics.brier_score
                - evaluation.naive_baseline_metrics.brier_score
            ),
            "roc_auc": _optional_difference(
                evaluation.model_metrics.roc_auc,
                evaluation.naive_baseline_metrics.roc_auc,
            ),
        },
        "top_positive_coefficients": [
            _coefficient_to_mapping(coefficient)
            for coefficient
            in evaluation.top_positive_coefficients
        ],
        "top_negative_coefficients": [
            _coefficient_to_mapping(coefficient)
            for coefficient
            in evaluation.top_negative_coefficients
        ],
    }


def _metrics_to_mapping(
    metrics: ClassificationMetrics,
) -> dict[str, float | None]:
    return {
        "accuracy": metrics.accuracy,
        "log_loss": metrics.log_loss,
        "brier_score": metrics.brier_score,
        "roc_auc": metrics.roc_auc,
    }


def _coefficient_to_mapping(
    coefficient: FeatureCoefficient,
) -> dict[str, float | str]:
    return {
        "feature_name": coefficient.feature_name,
        "coefficient": coefficient.coefficient,
    }


def _optional_difference(
    first_value: float | None,
    second_value: float | None,
) -> float | None:
    if (
        first_value is None
        or second_value is None
    ):
        return None

    return first_value - second_value


def _write_report(
    *,
    path: Path,
    report: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        mode="w",
        encoding="utf-8",
    ) as output_file:
        json.dump(
            report,
            output_file,
            indent=2,
            sort_keys=True,
        )

        output_file.write("\n")


def _print_evaluation(
    *,
    evaluation: MoneylineBaselineEvaluation,
    model_output_path: Path,
    report_output_path: Path,
) -> None:
    print("=" * 72)
    print("SportsModel MLB Moneyline Baseline")
    print("=" * 72)

    print(
        f"Training rows: {evaluation.training_rows}"
    )
    print(f"Test rows: {evaluation.test_rows}")
    print(
        "Training window: "
        f"{evaluation.training_start_time.isoformat()} "
        "through "
        f"{evaluation.training_end_time.isoformat()}"
    )
    print(
        "Test window: "
        f"{evaluation.test_start_time.isoformat()} "
        "through "
        f"{evaluation.test_end_time.isoformat()}"
    )
    print(
        "Training home-win rate: "
        f"{evaluation.training_home_win_rate:.4f}"
    )
    print(
        "Active features: "
        f"{len(evaluation.artifact.active_feature_names)}"
    )
    print(
        "All-missing features dropped: "
        f"{len(evaluation.artifact.dropped_all_missing_features)}"
    )
    print(
        "Constant features dropped: "
        f"{len(evaluation.artifact.dropped_constant_features)}"
    )

    print()
    print("Model metrics")
    _print_metrics(evaluation.model_metrics)

    print()
    print("Naive home-win-rate baseline")
    _print_metrics(evaluation.naive_baseline_metrics)

    print()
    print("Strongest positive coefficients")
    _print_coefficients(
        evaluation.top_positive_coefficients
    )

    print()
    print("Strongest negative coefficients")
    _print_coefficients(
        evaluation.top_negative_coefficients
    )

    print()
    print(
        f"Model artifact: {model_output_path.resolve()}"
    )
    print(
        f"Evaluation report: {report_output_path.resolve()}"
    )


def _print_metrics(
    metrics: ClassificationMetrics,
) -> None:
    print(f"  Accuracy:    {metrics.accuracy:.4f}")
    print(f"  Log loss:    {metrics.log_loss:.4f}")
    print(f"  Brier score: {metrics.brier_score:.4f}")

    if metrics.roc_auc is None:
        print("  ROC AUC:     unavailable")
    else:
        print(
            f"  ROC AUC:     {metrics.roc_auc:.4f}"
        )


def _print_coefficients(
    coefficients: tuple[FeatureCoefficient, ...],
) -> None:
    if not coefficients:
        print("  None")
        return

    for coefficient in coefficients:
        print(
            "  "
            f"{coefficient.coefficient:+.4f}  "
            f"{coefficient.feature_name}"
        )


if __name__ == "__main__":
    main()
