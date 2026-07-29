import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sportsmodel.training import (
    ClassificationMetrics,
    MoneylineWalkForwardComparison,
    MoneylineWalkForwardVariant,
    compare_raw_and_matchup_walk_forward,
    load_moneyline_training_csv,
)


DEFAULT_DATASET_PATH = Path(
    "data/training/mlb_moneyline_training.csv"
)

DEFAULT_REPORT_OUTPUT_PATH = Path(
    "data/models/mlb_moneyline_walk_forward_report.json"
)


def main() -> None:
    arguments = _parse_arguments()

    dataset = load_moneyline_training_csv(
        arguments.dataset
    )

    comparison = compare_raw_and_matchup_walk_forward(
        dataset,
        initial_training_rows=(
            arguments.initial_training_rows
        ),
        test_block_size=arguments.test_block_size,
        regularization_candidates=tuple(
            arguments.regularization_candidates
        ),
        validation_splits=(
            arguments.validation_splits
        ),
        calibration_bin_width=(
            arguments.calibration_bin_width
        ),
    )

    report = _build_report(
        comparison=comparison,
        dataset_path=arguments.dataset,
    )

    _write_report(
        path=arguments.report_output,
        report=report,
    )

    _print_comparison(
        comparison=comparison,
        report_output=arguments.report_output,
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run expanding-window Moneyline evaluation for "
            "raw and matchup-difference feature sets."
        )
    )

    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
    )

    parser.add_argument(
        "--report-output",
        type=Path,
        default=DEFAULT_REPORT_OUTPUT_PATH,
    )

    parser.add_argument(
        "--initial-training-rows",
        type=int,
        default=300,
    )

    parser.add_argument(
        "--test-block-size",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--regularization-candidates",
        type=float,
        nargs="+",
        default=[
            0.0001,
            0.0003,
            0.001,
            0.003,
            0.01,
            0.03,
            0.10,
        ],
    )

    parser.add_argument(
        "--validation-splits",
        type=int,
        default=4,
    )

    parser.add_argument(
        "--calibration-bin-width",
        type=float,
        default=0.10,
    )

    return parser.parse_args()


def _build_report(
    *,
    comparison: MoneylineWalkForwardComparison,
    dataset_path: Path,
) -> dict[str, Any]:
    return {
        "experiment_name": (
            "mlb_moneyline_walk_forward_raw_vs_matchup"
        ),
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "dataset_path": str(dataset_path.resolve()),
        "matchup_transformation": {
            "source_feature_count": len(
                comparison.matchup_transformer
                .source_feature_names
            ),
            "output_feature_count": len(
                comparison.matchup_transformer
                .output_feature_names
            ),
            "paired_feature_count": (
                comparison.matchup_transformer
                .paired_feature_count
            ),
            "passthrough_feature_count": (
                comparison.matchup_transformer
                .passthrough_feature_count
            ),
        },
        "raw": _variant_to_mapping(
            comparison.raw
        ),
        "matchup": _variant_to_mapping(
            comparison.matchup
        ),
        "matchup_minus_raw": _metric_deltas(
            comparison.matchup.evaluation
            .aggregate_model_metrics,
            comparison.raw.evaluation
            .aggregate_model_metrics,
        ),
    }


def _variant_to_mapping(
    variant: MoneylineWalkForwardVariant,
) -> dict[str, Any]:
    evaluation = variant.evaluation

    return {
        "name": variant.name,
        "input_feature_count": (
            variant.input_feature_count
        ),
        "dataset_rows": evaluation.dataset_rows,
        "initial_training_rows": (
            evaluation.initial_training_rows
        ),
        "test_block_size": evaluation.test_block_size,
        "fold_count": len(evaluation.folds),
        "total_test_rows": evaluation.total_test_rows,
        "aggregate_model_metrics": (
            _metrics_to_mapping(
                evaluation.aggregate_model_metrics
            )
        ),
        "aggregate_naive_baseline_metrics": (
            _metrics_to_mapping(
                evaluation.aggregate_naive_baseline_metrics
            )
        ),
        "expected_calibration_error": (
            evaluation.expected_calibration_error
        ),
        "folds_beating_naive_log_loss": (
            evaluation.folds_beating_naive_log_loss
        ),
        "folds_beating_naive_brier_score": (
            evaluation.folds_beating_naive_brier_score
        ),
        "folds_beating_naive_accuracy": (
            evaluation.folds_beating_naive_accuracy
        ),
        "folds": [
            {
                "fold_number": fold.fold_number,
                "training_rows": fold.training_rows,
                "test_rows": fold.test_rows,
                "training_start_time": (
                    fold.training_start_time.isoformat()
                ),
                "training_end_time": (
                    fold.training_end_time.isoformat()
                ),
                "test_start_time": (
                    fold.test_start_time.isoformat()
                ),
                "test_end_time": (
                    fold.test_end_time.isoformat()
                ),
                "active_feature_count": (
                    fold.active_feature_count
                ),
                "selected_regularization_c": (
                    fold.selected_regularization_c
                ),
                "model_metrics": _metrics_to_mapping(
                    fold.model_metrics
                ),
                "naive_baseline_metrics": (
                    _metrics_to_mapping(
                        fold.naive_baseline_metrics
                    )
                ),
            }
            for fold in evaluation.folds
        ],
        "calibration_bins": [
            {
                "lower_bound": calibration_bin.lower_bound,
                "upper_bound": calibration_bin.upper_bound,
                "prediction_count": (
                    calibration_bin.prediction_count
                ),
                "mean_predicted_probability": (
                    calibration_bin
                    .mean_predicted_probability
                ),
                "observed_home_win_rate": (
                    calibration_bin
                    .observed_home_win_rate
                ),
                "absolute_calibration_error": (
                    calibration_bin
                    .absolute_calibration_error
                ),
            }
            for calibration_bin
            in evaluation.calibration_bins
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


def _metric_deltas(
    matchup: ClassificationMetrics,
    raw: ClassificationMetrics,
) -> dict[str, float | None]:
    return {
        "accuracy": matchup.accuracy - raw.accuracy,
        "log_loss": matchup.log_loss - raw.log_loss,
        "brier_score": (
            matchup.brier_score - raw.brier_score
        ),
        "roc_auc": _optional_difference(
            matchup.roc_auc,
            raw.roc_auc,
        ),
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


def _print_comparison(
    *,
    comparison: MoneylineWalkForwardComparison,
    report_output: Path,
) -> None:
    print("=" * 78)
    print("SportsModel MLB Moneyline Walk-Forward Evaluation")
    print("=" * 78)

    print(
        "Raw feature columns: "
        f"{comparison.raw.input_feature_count}"
    )
    print(
        "Matchup feature columns: "
        f"{comparison.matchup.input_feature_count}"
    )

    _print_variant(comparison.raw)
    _print_variant(comparison.matchup)

    raw_metrics = (
        comparison.raw.evaluation
        .aggregate_model_metrics
    )

    matchup_metrics = (
        comparison.matchup.evaluation
        .aggregate_model_metrics
    )

    print()
    print("Matchup minus raw aggregate deltas")
    print(
        "  Accuracy:    "
        f"{matchup_metrics.accuracy - raw_metrics.accuracy:+.4f}"
    )
    print(
        "  Log loss:    "
        f"{matchup_metrics.log_loss - raw_metrics.log_loss:+.4f}"
    )
    print(
        "  Brier score: "
        f"{matchup_metrics.brier_score - raw_metrics.brier_score:+.4f}"
    )

    if (
        matchup_metrics.roc_auc is not None
        and raw_metrics.roc_auc is not None
    ):
        print(
            "  ROC AUC:     "
            f"{matchup_metrics.roc_auc - raw_metrics.roc_auc:+.4f}"
        )

    print()
    print(
        f"Report: {report_output.resolve()}"
    )


def _print_variant(
    variant: MoneylineWalkForwardVariant,
) -> None:
    evaluation = variant.evaluation
    model = evaluation.aggregate_model_metrics
    naive = evaluation.aggregate_naive_baseline_metrics

    print()
    print("-" * 78)
    print(variant.name)
    print("-" * 78)

    print(f"Folds: {len(evaluation.folds)}")
    print(
        f"Out-of-sample rows: {evaluation.total_test_rows}"
    )

    print()
    print("Aggregate model metrics")
    _print_metrics(model)

    print()
    print("Aggregate naive baseline metrics")
    _print_metrics(naive)

    print()
    print(
        "Folds beating naive log loss: "
        f"{evaluation.folds_beating_naive_log_loss}"
        f"/{len(evaluation.folds)}"
    )
    print(
        "Folds beating naive Brier score: "
        f"{evaluation.folds_beating_naive_brier_score}"
        f"/{len(evaluation.folds)}"
    )
    print(
        "Folds beating naive accuracy: "
        f"{evaluation.folds_beating_naive_accuracy}"
        f"/{len(evaluation.folds)}"
    )
    print(
        "Expected calibration error: "
        f"{evaluation.expected_calibration_error:.4f}"
    )

    print()
    print("Fold details")

    for fold in evaluation.folds:
        print(
            "  "
            f"Fold {fold.fold_number}: "
            f"train={fold.training_rows}, "
            f"test={fold.test_rows}, "
            f"C={fold.selected_regularization_c:g}, "
            f"log_loss={fold.model_metrics.log_loss:.4f}, "
            f"naive={fold.naive_baseline_metrics.log_loss:.4f}"
        )

    print()
    print("Calibration")

    for calibration_bin in evaluation.calibration_bins:
        print(
            "  "
            f"[{calibration_bin.lower_bound:.1f}, "
            f"{calibration_bin.upper_bound:.1f}): "
            f"n={calibration_bin.prediction_count}, "
            "predicted="
            f"{calibration_bin.mean_predicted_probability:.3f}, "
            "observed="
            f"{calibration_bin.observed_home_win_rate:.3f}"
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
        print(f"  ROC AUC:     {metrics.roc_auc:.4f}")


if __name__ == "__main__":
    main()
