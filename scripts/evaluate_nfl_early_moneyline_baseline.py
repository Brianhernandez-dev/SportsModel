from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsmodel.nfl.early_dataset_audit import (
    build_and_audit_production_early_dataset,
)
from sportsmodel.nfl.early_moneyline_baseline import (
    NFL_EARLY_BASELINE_C,
    NFL_EARLY_BASELINE_MAX_ITERATIONS,
    NFL_EARLY_BASELINE_RANDOM_STATE,
    NFL_EARLY_BASELINE_SOLVER,
    NFL_EARLY_BOOTSTRAP_ITERATIONS,
    assert_nfl_early_production_dataset_contract,
    build_nfl_early_modeling_examples,
    evaluate_nfl_early_moneyline_baseline,
    nfl_early_baseline_evaluation_to_dict,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the fixed NFL early-season Moneyline baseline on "
            "2019-2023 development and locked 2024 confirmation data."
        )
    )
    parser.add_argument("--json-output", type=Path)
    arguments = parser.parse_args()

    audited = build_and_audit_production_early_dataset(
        season_from=2019,
        season_to=2024,
    )
    if not audited.report["integrity_passed"]:
        raise RuntimeError("early dataset has PIT/integrity findings")
    assert_nfl_early_production_dataset_contract(
        audited.dataset.rows,
        audited.fingerprint,
    )
    examples = build_nfl_early_modeling_examples(audited.dataset.rows)
    first = evaluate_nfl_early_moneyline_baseline(
        examples,
        dataset_fingerprint=audited.fingerprint,
    )
    second = evaluate_nfl_early_moneyline_baseline(
        examples,
        dataset_fingerprint=audited.fingerprint,
    )
    reproducible = first == second
    _print_report(first, reproducible)

    report = nfl_early_baseline_evaluation_to_dict(first)
    report["reproducible"] = reproducible
    report["repeat_report_fingerprint"] = second.report_fingerprint
    report["dataset_integrity_findings"] = audited.report["integrity_findings"]
    if arguments.json_output:
        arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return 0 if reproducible else 1


def _print_report(evaluation, reproducible: bool) -> None:
    print("NFL Phase 3A2 Early-Season Moneyline Baseline")
    print("=" * 78)
    print(f"Dataset fingerprint: {evaluation.dataset_fingerprint}")
    print(f"Feature schema: {evaluation.source_feature_schema_version}")
    print(f"Feature count: {len(evaluation.feature_names)}")
    print(
        "Pipeline: SimpleImputer(strategy='median') -> StandardScaler -> "
        "LogisticRegression("
        f"C={NFL_EARLY_BASELINE_C}, solver='{NFL_EARLY_BASELINE_SOLVER}', "
        f"max_iter={NFL_EARLY_BASELINE_MAX_ITERATIONS}, "
        f"random_state={NFL_EARLY_BASELINE_RANDOM_STATE})"
    )
    print("Preprocessing fit scope: training rows only")
    print("Development choice seasons: 2019-2023 only")
    print("Locked confirmation: train 2019-2023; score 2024")
    print("2025 Phase 3 data accessed: NO")

    print("\nDevelopment folds")
    for fold in evaluation.development_folds:
        print(
            f"  Fold {fold.fold_number}: train={fold.training_seasons} "
            f"n={fold.training_rows}; validate={fold.validation_season} "
            f"n={fold.validation_rows}"
        )
        _print_metrics("    model", fold.model_metrics)
        _print_metrics("    empirical home baseline", fold.home_baseline_metrics)
        _print_metrics("    prior-season-only diagnostic", fold.prior_only_metrics)
        _print_metrics("    shuffled-label model", fold.shuffled_label_metrics)

    print("\nPooled development out-of-sample (validation 2021-2023)")
    _print_metrics("  full model", evaluation.development_model_metrics)
    _print_metrics(
        "  empirical home baseline",
        evaluation.development_home_baseline_metrics,
    )
    _print_metrics(
        "  prior-season-only diagnostic",
        evaluation.development_prior_only_metrics,
    )
    _print_metrics(
        "  shuffled-label model",
        evaluation.development_shuffled_label_metrics,
    )
    _print_intervals(
        "  full-model bootstrap 95% CIs",
        evaluation.development_confidence_intervals,
    )
    _print_intervals(
        "  model-minus-home-baseline paired 95% CIs",
        evaluation.development_paired_difference_intervals,
    )

    print("\nPooled development calibration (5 fixed equal-width bins)")
    print(f"  ECE={evaluation.development_expected_calibration_error:.6f}")
    _print_bins(evaluation.development_calibration_bins)
    print("\nPooled development history-state breakout")
    _print_states(evaluation.development_history_states)

    confirmation = evaluation.confirmation
    print("\nLocked 2024 confirmation (n is small; descriptive uncertainty)")
    print(
        f"  train={confirmation.training_seasons} n={confirmation.training_rows}; "
        f"confirm=2024 n={confirmation.validation_rows}"
    )
    _print_metrics("  full model", confirmation.model_metrics)
    _print_metrics("  empirical home baseline", confirmation.home_baseline_metrics)
    _print_metrics("  prior-season-only diagnostic", confirmation.prior_only_metrics)
    _print_intervals(
        "  full-model bootstrap 95% CIs",
        evaluation.confirmation_confidence_intervals,
    )
    _print_intervals(
        "  model-minus-home-baseline paired 95% CIs",
        evaluation.confirmation_paired_difference_intervals,
    )
    print(f"  ECE={evaluation.confirmation_expected_calibration_error:.6f}")
    print("  History states:")
    _print_states(evaluation.confirmation_history_states, indent="    ")

    print("\n2020 training-row sensitivity (official model still includes 2020)")
    for fold in evaluation.sensitivity_without_2020.folds:
        _print_metrics(
            f"  fold {fold.fold_number} without 2020 "
            f"(train={fold.training_rows_without_2020}, "
            f"validate={fold.validation_rows})",
            fold.metrics,
        )
    _print_metrics(
        "  pooled without-2020-training sensitivity",
        evaluation.sensitivity_without_2020.pooled_metrics,
    )

    print("\nFinal train-through-2023 standardized coefficients")
    print(f"  intercept: {confirmation.intercept:+.6f}")
    for item in confirmation.coefficients:
        print(f"  {item.feature_name}: {item.coefficient:+.6f}")
    positives = sorted(
        (item for item in confirmation.coefficients if item.coefficient > 0),
        key=lambda item: item.coefficient,
        reverse=True,
    )[:3]
    negatives = sorted(
        (item for item in confirmation.coefficients if item.coefficient < 0),
        key=lambda item: item.coefficient,
    )[:3]
    print("  Largest positive: " + ", ".join(
        f"{item.feature_name}={item.coefficient:+.6f}" for item in positives
    ))
    print("  Largest negative: " + ", ".join(
        f"{item.feature_name}={item.coefficient:+.6f}" for item in negatives
    ))
    print(
        "  Sign caution: both turnover-differential coefficients are negative, "
        "and the small points-against coefficient is positive. Similar-signal "
        "signs should be treated as unstable diagnostics, not feature decisions."
    )
    print("  Coefficients are non-causal and unstable at this sample size.")

    print("\nNeutral-site coverage")
    print(
        f"  development OOS={evaluation.development_neutral_site_rows}; "
        f"2024 confirmation={evaluation.confirmation_neutral_site_rows}"
    )
    print("  Sparse neutral-site coefficients are not reliably interpretable.")
    print(f"\nBootstrap iterations: {NFL_EARLY_BOOTSTRAP_ITERATIONS}")
    print(f"Report fingerprint: {evaluation.report_fingerprint}")
    print(f"Repeat deterministic: {'YES' if reproducible else 'NO'}")


def _print_metrics(label, metrics) -> None:
    if metrics is None:
        print(f"{label}: N/A")
        return
    print(
        f"{label}: accuracy={metrics.accuracy:.6f}, "
        f"log_loss={metrics.log_loss:.6f}, "
        f"brier={metrics.brier_score:.6f}, "
        f"auc={_optional(metrics.roc_auc)}, "
        f"pred_mean={metrics.mean_predicted_probability:.6f}, "
        f"actual={metrics.actual_home_win_rate:.6f}"
    )


def _print_intervals(label, intervals) -> None:
    print(label + ":")
    for name in ("accuracy", "log_loss", "brier_score", "roc_auc"):
        value = getattr(intervals, name)
        if value is None:
            print(f"    {name}: omitted/non-informative")
        else:
            print(f"    {name}: [{value.lower:+.6f}, {value.upper:+.6f}]")


def _print_bins(bins) -> None:
    for item in bins:
        print(
            f"  [{item.lower_bound:.1f}, {item.upper_bound:.1f}): "
            f"n={item.prediction_count}, "
            f"pred={item.mean_predicted_probability:.6f}, "
            f"actual={item.actual_home_win_rate:.6f}"
        )


def _print_states(states, *, indent="  ") -> None:
    for item in states:
        metrics = item.metrics
        print(
            f"{indent}minimum={item.minimum_current_prior_games}: "
            f"n={item.row_count}, accuracy={metrics.accuracy:.6f}, "
            f"log_loss={metrics.log_loss:.6f}, "
            f"brier={metrics.brier_score:.6f}, "
            f"auc={_optional(metrics.roc_auc)}, "
            f"pred_mean={metrics.mean_predicted_probability:.6f}, "
            f"actual={metrics.actual_home_win_rate:.6f}"
        )


def _optional(value) -> str:
    return "N/A" if value is None else f"{value:.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
