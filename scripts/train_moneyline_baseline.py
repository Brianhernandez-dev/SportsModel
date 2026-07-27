import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sportsmodel.training import (
    MATCHUP_FEATURE_TRANSFORM_VERSION,
    ClassificationMetrics,
    FeatureCoefficient,
    MoneylineExperimentVariant,
    MoneylineModelComparison,
    compare_raw_and_matchup_moneyline_models,
    load_moneyline_training_csv,
    save_trained_matchup_moneyline_model,
    save_trained_moneyline_baseline,
)


DEFAULT_DATASET_PATH = Path(
    "data/training/mlb_moneyline_training.csv"
)

DEFAULT_RAW_MODEL_OUTPUT_PATH = Path(
    "data/models/mlb_moneyline_raw_tuned.joblib"
)

DEFAULT_MATCHUP_MODEL_OUTPUT_PATH = Path(
    "data/models/mlb_moneyline_matchup_tuned.joblib"
)

DEFAULT_REPORT_OUTPUT_PATH = Path(
    "data/models/mlb_moneyline_comparison_report.json"
)


def main() -> None:
    arguments = _parse_arguments()

    dataset = load_moneyline_training_csv(
        arguments.dataset
    )

    comparison = (
        compare_raw_and_matchup_moneyline_models(
            dataset,
            test_fraction=arguments.test_fraction,
            top_feature_count=arguments.top_features,
            regularization_candidates=tuple(
                arguments.regularization_candidates
            ),
            validation_splits=(
                arguments.validation_splits
            ),
        )
    )

    save_trained_moneyline_baseline(
        comparison.raw.evaluation.artifact,
        arguments.raw_model_output,
    )

    save_trained_matchup_moneyline_model(
        comparison.matchup_model,
        arguments.matchup_model_output,
    )

    report = _build_report(
        comparison=comparison,
        dataset_path=arguments.dataset,
        raw_model_output=arguments.raw_model_output,
        matchup_model_output=(
            arguments.matchup_model_output
        ),
    )

    _write_report(
        path=arguments.report_output,
        report=report,
    )

    _print_comparison(
        comparison=comparison,
        raw_model_output=arguments.raw_model_output,
        matchup_model_output=(
            arguments.matchup_model_output
        ),
        report_output=arguments.report_output,
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Tune and compare raw and matchup-difference "
            "MLB Moneyline logistic-regression models."
        )
    )

    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
    )

    parser.add_argument(
        "--raw-model-output",
        type=Path,
        default=DEFAULT_RAW_MODEL_OUTPUT_PATH,
    )

    parser.add_argument(
        "--matchup-model-output",
        type=Path,
        default=DEFAULT_MATCHUP_MODEL_OUTPUT_PATH,
    )

    parser.add_argument(
        "--report-output",
        type=Path,
        default=DEFAULT_REPORT_OUTPUT_PATH,
    )

    parser.add_argument(
        "--test-fraction",
        type=float,
        default=0.20,
    )

    parser.add_argument(
        "--top-features",
        type=int,
        default=15,
    )

    parser.add_argument(
        "--regularization-candidates",
        type=float,
        nargs="+",
        default=[
            0.01,
            0.03,
            0.10,
            0.30,
            1.00,
            3.00,
            10.00,
        ],
    )

    parser.add_argument(
        "--validation-splits",
        type=int,
        default=4,
    )

    return parser.parse_args()


def _build_report(
    *,
    comparison: MoneylineModelComparison,
    dataset_path: Path,
    raw_model_output: Path,
    matchup_model_output: Path,
) -> dict[str, Any]:
    return {
        "experiment_name": (
            "mlb_moneyline_raw_vs_matchup"
        ),
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "dataset_path": str(dataset_path.resolve()),
        "feature_schema_version": (
            comparison.raw.evaluation.artifact
            .feature_schema_version
        ),
        "matchup_transform_version": (
            MATCHUP_FEATURE_TRANSFORM_VERSION
        ),
        "raw_model_output": str(
            raw_model_output.resolve()
        ),
        "matchup_model_output": str(
            matchup_model_output.resolve()
        ),
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
            .model_metrics,
            comparison.raw.evaluation
            .model_metrics,
        ),
        "selection_note": (
            "The outer test set is used for final benchmark "
            "comparison only. This report does not designate a "
            "deployment winner."
        ),
    }


def _variant_to_mapping(
    variant: MoneylineExperimentVariant,
) -> dict[str, Any]:
    evaluation = variant.evaluation
    artifact = evaluation.artifact

    return {
        "name": variant.name,
        "input_feature_count": (
            variant.input_feature_count
        ),
        "active_feature_count": len(
            artifact.active_feature_names
        ),
        "selected_regularization_c": (
            variant.tuning.selected_c
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
        "dropped_all_missing_features": list(
            artifact.dropped_all_missing_features
        ),
        "dropped_constant_features": list(
            artifact.dropped_constant_features
        ),
        "dropped_duplicate_features": list(
            artifact.dropped_duplicate_features
        ),
        "model_metrics": _metrics_to_mapping(
            evaluation.model_metrics
        ),
        "naive_baseline_metrics": _metrics_to_mapping(
            evaluation.naive_baseline_metrics
        ),
        "regularization_candidates": [
            {
                "regularization_c": (
                    candidate.regularization_c
                ),
                "mean_log_loss": (
                    candidate.mean_log_loss
                ),
                "fold_log_losses": list(
                    candidate.fold_log_losses
                ),
            }
            for candidate in variant.tuning.candidates
        ],
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


def _coefficient_to_mapping(
    coefficient: FeatureCoefficient,
) -> dict[str, str | float]:
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


def _print_comparison(
    *,
    comparison: MoneylineModelComparison,
    raw_model_output: Path,
    matchup_model_output: Path,
    report_output: Path,
) -> None:
    print("=" * 76)
    print("SportsModel MLB Moneyline Model Comparison")
    print("=" * 76)

    transformer = comparison.matchup_transformer

    print(
        "Raw feature columns: "
        f"{len(transformer.source_feature_names)}"
    )
    print(
        "Matchup feature columns: "
        f"{len(transformer.output_feature_names)}"
    )
    print(
        "Paired home/away features: "
        f"{transformer.paired_feature_count}"
    )
    print(
        "Passthrough features: "
        f"{transformer.passthrough_feature_count}"
    )

    _print_variant(comparison.raw)
    _print_variant(comparison.matchup)

    raw_metrics = comparison.raw.evaluation.model_metrics
    matchup_metrics = (
        comparison.matchup.evaluation.model_metrics
    )

    print()
    print("Matchup minus raw metric deltas")
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
        "The outer test set is a final benchmark only; "
        "no deployment winner is selected from this comparison."
    )
    print(
        f"Raw artifact: {raw_model_output.resolve()}"
    )
    print(
        "Matchup artifact: "
        f"{matchup_model_output.resolve()}"
    )
    print(
        f"Comparison report: {report_output.resolve()}"
    )


def _print_variant(
    variant: MoneylineExperimentVariant,
) -> None:
    evaluation = variant.evaluation
    metrics = evaluation.model_metrics

    print()
    print("-" * 76)
    print(variant.name)
    print("-" * 76)
    print(
        f"Training rows: {evaluation.training_rows}"
    )
    print(f"Test rows: {evaluation.test_rows}")
    print(
        "Selected C: "
        f"{variant.tuning.selected_c:g}"
    )
    print(
        "Active features: "
        f"{len(evaluation.artifact.active_feature_names)}"
    )
    print(
        "Duplicate features dropped: "
        f"{len(evaluation.artifact.dropped_duplicate_features)}"
    )
    print(f"Accuracy:    {metrics.accuracy:.4f}")
    print(f"Log loss:    {metrics.log_loss:.4f}")
    print(f"Brier score: {metrics.brier_score:.4f}")

    if metrics.roc_auc is None:
        print("ROC AUC:     unavailable")
    else:
        print(f"ROC AUC:     {metrics.roc_auc:.4f}")

    print("Inner chronological tuning:")

    for candidate in variant.tuning.candidates:
        selected_marker = (
            " *"
            if (
                candidate.regularization_c
                == variant.tuning.selected_c
            )
            else ""
        )

        print(
            "  "
            f"C={candidate.regularization_c:g}: "
            f"{candidate.mean_log_loss:.4f}"
            f"{selected_marker}"
        )


if __name__ == "__main__":
    main()
