from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsmodel.nfl.dataset_audit import build_and_audit_production_dataset
from sportsmodel.nfl.moneyline_baseline import (
    NFL_DEVELOPMENT_FINAL_SEASON,
    NFL_DEVELOPMENT_FIRST_SEASON,
    build_nfl_moneyline_modeling_examples,
    evaluate_nfl_moneyline_development,
    nfl_development_evaluation_to_dict,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the NFL Moneyline logistic baseline on the locked "
            "2018-2024 development folds. The 2025 holdout is never loaded."
        )
    )
    parser.add_argument("--json-output", type=Path)
    arguments = parser.parse_args()

    audited = build_and_audit_production_dataset(
        season_from=NFL_DEVELOPMENT_FIRST_SEASON,
        season_to=NFL_DEVELOPMENT_FINAL_SEASON,
    )
    if not audited.report["integrity_passed"]:
        raise RuntimeError("audited NFL development dataset has integrity findings")
    examples = build_nfl_moneyline_modeling_examples(
        audited.dataset.rows,
        audited.canonical_games,
    )
    evaluation = evaluate_nfl_moneyline_development(examples)
    report = nfl_development_evaluation_to_dict(evaluation)
    report["development_dataset_fingerprint"] = audited.fingerprint
    report["development_dataset_rows"] = len(examples)
    report["schedule_structure_audit"] = _schedule_structure_audit(examples)

    _print_report(
        evaluation, audited.fingerprint, len(examples),
        report["schedule_structure_audit"],
    )
    if arguments.json_output:
        arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return 0


def _print_report(
    evaluation, dataset_fingerprint: str, row_count: int,
    schedule_audit: dict[str, object],
) -> None:
    print("NFL Phase 2D Moneyline Logistic Baseline")
    print("=" * 78)
    print(f"Development seasons loaded: 2018-{NFL_DEVELOPMENT_FINAL_SEASON}")
    print("Final holdout loaded/evaluated: NO (2025 untouched)")
    print(f"Development rows: {row_count}")
    print(f"Development dataset fingerprint: {dataset_fingerprint}")
    print(f"Representation: {evaluation.representation_version}")
    print(f"Feature count: {len(evaluation.feature_names)}")
    print(
        "Model: LogisticRegression("
        f"C={evaluation.regularization_c}, solver={evaluation.solver}, "
        f"max_iter={evaluation.max_iterations}, "
        f"random_state={evaluation.random_state})"
    )
    print("\nPolicy selection comparison (folds 1-2 only; validation 2022-2023)")
    for policy in evaluation.policies:
        metrics = policy.selection_model_metrics
        baseline = policy.selection_home_baseline_metrics
        print(
            f"  {policy.policy.value}: validation="
            f"{policy.selection_validation_rows_evaluated} "
            f"(excluded {policy.selection_validation_rows_excluded}, "
            f"retained {policy.selection_validation_retention_rate:.1%}), "
            f"train exposures={policy.selection_training_rows_retained} "
            f"(excluded {policy.selection_training_rows_excluded}, "
            f"retained {policy.selection_training_retention_rate:.1%}), "
            f"accuracy={metrics.accuracy:.6f}, "
            f"log_loss={metrics.log_loss:.6f}, "
            f"brier={metrics.brier_score:.6f}, "
            f"auc={_optional(metrics.roc_auc)}, "
            f"two_fold_log_loss_sd="
            f"{policy.selection_fold_log_loss_standard_deviation:.6f}, "
            f"home_baseline_log_loss={baseline.log_loss:.6f}"
        )

    selected = evaluation.selected_evaluation
    print(f"\nSelected policy: {evaluation.selected_policy.value}")
    print(f"Selection basis: {evaluation.selection_reason}")
    print("\nSelection-stage folds")
    for fold in selected.folds[:2]:
        _print_fold(fold)

    confirmation = selected.confirmation_fold
    print("\nFold 3 confirmation (2024 did not participate in policy choice)")
    _print_fold(confirmation)

    print("\nTraining-label shuffle leakage smoke test")
    for fold in selected.folds:
        shuffled = fold.shuffled_label_metrics
        print(
            f"  Fold {fold.fold_number}: accuracy={shuffled.accuracy:.6f}, "
            f"log_loss={shuffled.log_loss:.6f}, "
            f"brier={shuffled.brier_score:.6f}, "
            f"auc={_optional(shuffled.roc_auc)}"
        )
    shuffled = selected.aggregate_shuffled_label_metrics
    print(
        f"  Pooled folds 1-3: accuracy={shuffled.accuracy:.6f}, "
        f"log_loss={shuffled.log_loss:.6f}, "
        f"brier={shuffled.brier_score:.6f}, "
        f"auc={_optional(shuffled.roc_auc)}"
    )

    metrics = selected.aggregate_model_metrics
    baseline = selected.aggregate_home_baseline_metrics
    print("\nPost-selection descriptive aggregate (folds 1-3; not a policy-selection estimate)")
    print(
        f"  Model: accuracy={metrics.accuracy:.6f}, "
        f"log_loss={metrics.log_loss:.6f}, brier={metrics.brier_score:.6f}, "
        f"auc={_optional(metrics.roc_auc)}, "
        f"pred_mean={metrics.mean_predicted_probability:.6f}, "
        f"actual={metrics.actual_home_win_rate:.6f}"
    )
    print(
        f"  Empirical home baseline: accuracy={baseline.accuracy:.6f}, "
        f"log_loss={baseline.log_loss:.6f}, "
        f"brier={baseline.brier_score:.6f}, "
        f"pred_mean={baseline.mean_predicted_probability:.6f}; "
        "ROC-AUC omitted as non-informative for a constant fold probability"
    )
    _print_intervals(
        "  Model 95% paired-game bootstrap CIs",
        evaluation.selected_aggregate_confidence_intervals,
    )
    _print_intervals(
        "  Model minus home-baseline paired 95% CIs",
        evaluation.selected_paired_difference_intervals,
    )
    _print_intervals(
        "  Fold 3 model 95% paired-game bootstrap CIs",
        evaluation.confirmation_confidence_intervals,
    )
    _print_intervals(
        "  Fold 3 model minus baseline paired 95% CIs",
        evaluation.confirmation_paired_difference_intervals,
    )

    print("\nSelected-policy season-type breakouts (descriptive only)")
    for segment in evaluation.selected_segments:
        if segment.metrics is None:
            print(f"  {segment.name}: n={segment.row_count}; metrics suppressed")
            continue
        value = segment.metrics
        print(
            f"  {segment.name}: n={segment.row_count}, "
            f"accuracy={value.accuracy:.6f}, log_loss={value.log_loss:.6f}, "
            f"brier={value.brier_score:.6f}, auc={_optional(value.roc_auc)}"
        )

    print("\nCoverage limitation")
    minimum = evaluation.selected_policy.minimum_history
    if minimum is None:
        print("  Full-season coverage uses training-fold median imputation.")
    else:
        print(
            "  NOT a full-season production model: prediction is permitted only "
            f"when BOTH teams have at least {minimum} same-season prior eligible "
            "games. Weeks 1-3 or equivalent early-season games require a future "
            "explicit strategy and must not be silently imputed or predicted."
        )

    print("\nSchedule/PIT structural audit")
    print(
        "  Maximum same-season prior eligible counts by season "
        "(including postseason): "
        f"{schedule_audit['maximum_prior_games_by_season']}"
    )
    print(
        "  2018-2020 versus 2021+ schedule-length variation uses observed eligible "
        "game counts directly; no schedule normalization is applied."
    )
    print(
        "  2020 rescheduled games remain ordered solely by timezone-aware actual "
        "kickoff with strict source kickoff < target cutoff; week is not a boundary."
    )

    print("\nCalibration (descriptive only)")
    print(f"  Expected calibration error: {selected.expected_calibration_error:.6f}")
    print("  Calibration bins:")
    for item in selected.calibration_bins:
        print(
            f"    [{item.lower_bound:.1f}, {item.upper_bound:.1f}): "
            f"n={item.prediction_count}, "
            f"pred={item.mean_predicted_probability:.6f}, "
            f"actual={item.actual_home_win_rate:.6f}, "
            f"abs_error={item.absolute_calibration_error:.6f}"
        )

    coefficients = evaluation.selected_final_fold.coefficients
    print(
        "\nFold 3 standardized-feature intercept "
        f"(home context at mean matchup): "
        f"{evaluation.selected_final_fold.intercept:+.6f}"
    )
    positive = sorted(
        (item for item in coefficients if item.coefficient > 0),
        key=lambda item: item.coefficient,
        reverse=True,
    )[:8]
    negative = sorted(
        (item for item in coefficients if item.coefficient < 0),
        key=lambda item: item.coefficient,
    )[:8]
    print("\nLargest standardized coefficients (Fold 3, trained through 2023)")
    print("  Positive:")
    for item in positive:
        print(f"    {item.feature_name}: {item.coefficient:+.6f}")
    print("  Negative:")
    for item in negative:
        print(f"    {item.feature_name}: {item.coefficient:+.6f}")
    print(f"\nDeterministic report fingerprint: {evaluation.report_fingerprint}")


def _print_fold(fold) -> None:
    model = fold.model_metrics
    baseline = fold.home_baseline_metrics
    print(
        f"  Fold {fold.fold_number}: train 2018-{fold.training_seasons[-1]} "
        f"n={fold.training_rows_retained}/{fold.training_rows_available}; "
        f"validate {fold.validation_season} "
        f"n={fold.validation_rows_evaluated}/{fold.validation_rows_available}; "
        f"accuracy={model.accuracy:.6f}, log_loss={model.log_loss:.6f}, "
        f"brier={model.brier_score:.6f}, auc={_optional(model.roc_auc)}, "
        f"pred_mean={model.mean_predicted_probability:.6f}, "
        f"actual={model.actual_home_win_rate:.6f}; "
        f"home_baseline_accuracy={baseline.accuracy:.6f}, "
        f"home_baseline_log_loss={baseline.log_loss:.6f}"
    )


def _print_intervals(label: str, intervals) -> None:
    print(f"{label}:")
    for name in ("accuracy", "log_loss", "brier_score", "roc_auc"):
        value = getattr(intervals, name)
        if value is None:
            print(f"    {name}: omitted/non-informative")
        else:
            print(f"    {name}: [{value.lower:+.6f}, {value.upper:+.6f}]")


def _schedule_structure_audit(examples) -> dict[str, object]:
    seasons = sorted({item.season for item in examples})
    return {
        "maximum_prior_games_by_season": {
            str(season): max(
                max(item.home_prior_games, item.away_prior_games)
                for item in examples if item.season == season
            )
            for season in seasons
        },
        "schedule_length_normalization": False,
        "temporal_boundary": "actual kickoff strictly less than target kickoff",
        "week_used_as_temporal_boundary": False,
    }


def _optional(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
