"""Frozen one-time NFL 2025 holdout contract.

The Phase 2D baseline was frozen before any 2025-season evaluation. Once the
holdout is observed, later changes are new model development and 2025 is no
longer an untouched holdout. Minimum-history-3 intentionally excludes the
early season; this baseline does not solve Weeks 1-3.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from random import Random
from typing import Any, Callable

from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from sportsmodel.nfl.features import NFL_MONEYLINE_FEATURE_SCHEMA_VERSION
from sportsmodel.nfl.moneyline_baseline import (
    NFL_BASELINE_FEATURE_NAMES,
    NFL_BASELINE_MAX_ITERATIONS,
    NFL_BASELINE_RANDOM_STATE,
    NFL_BASELINE_REGULARIZATION_C,
    NFL_BASELINE_SOLVER,
    NFL_BOOTSTRAP_ITERATIONS,
    NFL_BOOTSTRAP_SEED,
    NFL_CALIBRATION_BIN_WIDTH,
    NFL_DEVELOPMENT_FINAL_SEASON,
    NFL_DEVELOPMENT_FIRST_SEASON,
    NFL_FINAL_HOLDOUT_SEASON,
    NFL_POSTSEASON_MINIMUM_REPORT_ROWS,
    NflCalibrationBin,
    NflConfidenceInterval,
    NflMetricConfidenceIntervals,
    NflMissingValuePolicy,
    NflMoneylineModelingExample,
    NflProbabilityMetrics,
    NflSegmentEvaluation,
    _interval,
    _matrix,
    _metrics,
    _pipeline,
    _raw_metric_values,
)
from sportsmodel.nfl.models import NflGame, NflSeasonType


FROZEN_NFL_BASELINE_SPECIFICATION_VERSION = "nfl_moneyline_frozen_0.1.0"
FROZEN_NFL_FEATURE_SCHEMA_VERSION = "nfl_moneyline_0.2.0"
FROZEN_NFL_TRAINING_SEASONS = tuple(range(2018, 2025))
FROZEN_NFL_HOLDOUT_SEASON = 2025
FROZEN_NFL_MINIMUM_HISTORY = 3
FROZEN_NFL_FEATURE_NAMES = (
    "minimum_prior_games",
    "matchup_prior_games_used_difference",
    "matchup_win_percentage_difference",
    "matchup_average_points_for_difference",
    "matchup_average_points_against_difference",
    "matchup_average_passing_yards_difference",
    "matchup_average_passing_yards_allowed_difference",
    "matchup_average_rushing_yards_difference",
    "matchup_average_rushing_yards_allowed_difference",
    "matchup_average_turnovers_difference",
    "matchup_average_takeaways_difference",
    "matchup_rolling_3_games_used_difference",
    "matchup_rolling_3_average_points_for_difference",
    "matchup_rolling_3_average_points_against_difference",
    "matchup_rolling_3_average_turnover_differential_difference",
    "matchup_rolling_5_games_used_difference",
    "matchup_rolling_5_average_points_for_difference",
    "matchup_rolling_5_average_points_against_difference",
    "matchup_rolling_5_average_turnover_differential_difference",
)


class FinalNflHoldoutConfirmationRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class FrozenNflBaselineSpecification:
    specification_version: str
    model_purpose: str
    target: str
    training_seasons: tuple[int, ...]
    holdout_season: int
    minimum_history_per_team: int
    feature_schema_version: str
    feature_names: tuple[str, ...]
    regularization_c: float
    solver: str
    max_iterations: int
    random_state: int
    imputation: str
    scaling: str


FROZEN_NFL_BASELINE_SPECIFICATION = FrozenNflBaselineSpecification(
    specification_version=FROZEN_NFL_BASELINE_SPECIFICATION_VERSION,
    model_purpose="First simple NFL Moneyline historical baseline",
    target="home_win",
    training_seasons=FROZEN_NFL_TRAINING_SEASONS,
    holdout_season=FROZEN_NFL_HOLDOUT_SEASON,
    minimum_history_per_team=FROZEN_NFL_MINIMUM_HISTORY,
    feature_schema_version=FROZEN_NFL_FEATURE_SCHEMA_VERSION,
    feature_names=FROZEN_NFL_FEATURE_NAMES,
    regularization_c=1.0,
    solver="lbfgs",
    max_iterations=5000,
    random_state=42,
    imputation="training-row median",
    scaling="training-row StandardScaler",
)


@dataclass(frozen=True)
class NflFinalHoldoutPrediction:
    game_id: int
    season: int
    season_type: NflSeasonType
    actual_home_win: bool
    model_home_win_probability: float
    home_baseline_probability: float


@dataclass(frozen=True)
class NflHoldoutMetricDifferences:
    accuracy: float
    log_loss: float
    brier_score: float


@dataclass(frozen=True)
class NflFinalHoldoutEvaluation:
    training_rows_available: int
    training_rows_eligible: int
    training_rows_excluded: int
    holdout_rows_available: int
    holdout_rows_eligible: int
    holdout_rows_excluded: int
    training_home_win_rate: float
    model_metrics: NflProbabilityMetrics
    home_baseline_metrics: NflProbabilityMetrics
    paired_differences: NflHoldoutMetricDifferences
    confidence_intervals: NflMetricConfidenceIntervals
    paired_difference_intervals: NflMetricConfidenceIntervals
    calibration_bins: tuple[NflCalibrationBin, ...]
    expected_calibration_error: float
    segments: tuple[NflSegmentEvaluation, ...]
    imputer_statistics: tuple[float, ...]
    scaler_means: tuple[float, ...]
    scaler_scales: tuple[float, ...]
    intercept: float
    coefficients: tuple[float, ...]
    predictions: tuple[NflFinalHoldoutPrediction, ...]
    report_fingerprint: str


LoadedPopulation = tuple[
    tuple[dict[str, object], ...],
    tuple[NflGame, ...],
]


def assert_frozen_nfl_baseline_specification() -> None:
    """Abort on drift before a final-holdout loader can be invoked."""
    spec = FROZEN_NFL_BASELINE_SPECIFICATION
    checks = {
        "feature schema": NFL_MONEYLINE_FEATURE_SCHEMA_VERSION
        == spec.feature_schema_version,
        "ordered feature representation": tuple(NFL_BASELINE_FEATURE_NAMES)
        == spec.feature_names,
        "training season start": NFL_DEVELOPMENT_FIRST_SEASON
        == spec.training_seasons[0],
        "training season end": NFL_DEVELOPMENT_FINAL_SEASON
        == spec.training_seasons[-1],
        "holdout season": NFL_FINAL_HOLDOUT_SEASON == spec.holdout_season,
        "minimum history": (
            FROZEN_NFL_MINIMUM_HISTORY == 3
            and NflMissingValuePolicy.MINIMUM_HISTORY_3.minimum_history
            == spec.minimum_history_per_team
        ),
        "regularization C": NFL_BASELINE_REGULARIZATION_C
        == spec.regularization_c,
        "solver": NFL_BASELINE_SOLVER == spec.solver,
        "maximum iterations": NFL_BASELINE_MAX_ITERATIONS
        == spec.max_iterations,
        "random state": NFL_BASELINE_RANDOM_STATE == spec.random_state,
        "bootstrap iterations": NFL_BOOTSTRAP_ITERATIONS == 500,
        "bootstrap seed": NFL_BOOTSTRAP_SEED == 20260818,
    }
    drift = [name for name, matches in checks.items() if not matches]
    if drift:
        raise RuntimeError(
            "frozen NFL baseline specification drift: " + ", ".join(drift)
        )

    pipeline = _pipeline(spec.regularization_c)
    if tuple(pipeline.named_steps) != ("imputer", "scaler", "classifier"):
        raise RuntimeError("frozen NFL baseline preprocessing order drift")
    imputer = pipeline.named_steps.get("imputer")
    scaler = pipeline.named_steps.get("scaler")
    classifier = pipeline.named_steps.get("classifier")
    if not (
        isinstance(imputer, SimpleImputer)
        and imputer.strategy == "median"
        and not imputer.add_indicator
    ):
        raise RuntimeError("frozen NFL baseline imputation configuration drift")
    if not (
        isinstance(scaler, StandardScaler)
        and scaler.with_mean
        and scaler.with_std
    ):
        raise RuntimeError("frozen NFL baseline scaler configuration drift")
    if not isinstance(classifier, LogisticRegression):
        raise RuntimeError("frozen NFL baseline classifier type drift")
    params = classifier.get_params()
    expected = {
        "C": spec.regularization_c,
        "solver": spec.solver,
        "max_iter": spec.max_iterations,
        "random_state": spec.random_state,
    }
    if any(params[name] != value for name, value in expected.items()):
        raise RuntimeError("frozen NFL baseline classifier parameter drift")


def run_guarded_final_nfl_holdout_evaluation(
    *,
    confirmed: bool,
    development_loader: Callable[[], LoadedPopulation],
    holdout_loader: Callable[[], LoadedPopulation],
) -> NflFinalHoldoutEvaluation:
    """Load the one-time holdout only after explicit opt-in and freeze checks."""
    if not confirmed:
        raise FinalNflHoldoutConfirmationRequired(
            "final 2025 NFL holdout requires explicit confirmation"
        )
    assert_frozen_nfl_baseline_specification()

    from sportsmodel.nfl.moneyline_baseline import (
        build_nfl_moneyline_holdout_examples,
        build_nfl_moneyline_modeling_examples,
    )

    development_rows, development_games = development_loader()
    training = build_nfl_moneyline_modeling_examples(
        development_rows, development_games,
    )
    holdout_rows, holdout_games = holdout_loader()
    holdout = build_nfl_moneyline_holdout_examples(holdout_rows, holdout_games)
    return evaluate_frozen_nfl_moneyline_holdout(training, holdout)


def evaluate_frozen_nfl_moneyline_holdout(
    training_examples: tuple[NflMoneylineModelingExample, ...],
    holdout_examples: tuple[NflMoneylineModelingExample, ...],
) -> NflFinalHoldoutEvaluation:
    """Evaluate synthetic/already-loaded rows; production loading stays guarded."""
    assert_frozen_nfl_baseline_specification()
    _validate_population(training_examples, holdout_examples)
    training = _eligible(training_examples)
    holdout = _eligible(holdout_examples)
    if not training or not holdout:
        raise ValueError("frozen NFL baseline requires eligible training and holdout rows")
    training_targets = [item.home_win for item in training]
    if len(set(training_targets)) != 2:
        raise ValueError("frozen NFL baseline training rows require both target classes")

    pipeline = _pipeline(FROZEN_NFL_BASELINE_SPECIFICATION.regularization_c)
    pipeline.fit(_matrix(training), training_targets)
    probabilities = [
        float(value) for value in pipeline.predict_proba(_matrix(holdout))[:, 1]
    ]
    holdout_targets = [item.home_win for item in holdout]
    training_home_rate = sum(training_targets) / len(training_targets)
    baseline_probabilities = [training_home_rate] * len(holdout)
    predictions = tuple(
        NflFinalHoldoutPrediction(
            game_id=item.game_id,
            season=item.season,
            season_type=item.season_type,
            actual_home_win=item.home_win,
            model_home_win_probability=probability,
            home_baseline_probability=training_home_rate,
        )
        for item, probability in zip(holdout, probabilities, strict=True)
    )
    bins = _holdout_calibration_bins(predictions)
    intervals, differences = _holdout_bootstrap_intervals(predictions)
    segments = _holdout_segments(predictions)
    imputer: SimpleImputer = pipeline.named_steps["imputer"]
    scaler: StandardScaler = pipeline.named_steps["scaler"]
    classifier: LogisticRegression = pipeline.named_steps["classifier"]
    model_metrics = _metrics(holdout_targets, probabilities)
    baseline_metrics = _metrics(
        holdout_targets, baseline_probabilities, include_auc=False,
    )
    point_differences = NflHoldoutMetricDifferences(
        accuracy=model_metrics.accuracy - baseline_metrics.accuracy,
        log_loss=model_metrics.log_loss - baseline_metrics.log_loss,
        brier_score=model_metrics.brier_score - baseline_metrics.brier_score,
    )
    imputer_statistics = tuple(float(value) for value in imputer.statistics_)
    scaler_means = tuple(float(value) for value in scaler.mean_)
    scaler_scales = tuple(float(value) for value in scaler.scale_)
    intercept = float(classifier.intercept_[0])
    coefficients = tuple(float(value) for value in classifier.coef_[0])
    payload = _holdout_report_payload(
        training_rows_available=len(training_examples),
        training_rows_eligible=len(training),
        holdout_rows_available=len(holdout_examples),
        holdout_rows_eligible=len(holdout),
        training_home_rate=training_home_rate,
        model_metrics=model_metrics,
        baseline_metrics=baseline_metrics,
        point_differences=point_differences,
        intervals=intervals,
        differences=differences,
        bins=bins,
        segments=segments,
        predictions=predictions,
        imputer_statistics=imputer_statistics,
        scaler_means=scaler_means,
        scaler_scales=scaler_scales,
        intercept=intercept,
        coefficients=coefficients,
    )
    fingerprint = sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return NflFinalHoldoutEvaluation(
        training_rows_available=len(training_examples),
        training_rows_eligible=len(training),
        training_rows_excluded=len(training_examples) - len(training),
        holdout_rows_available=len(holdout_examples),
        holdout_rows_eligible=len(holdout),
        holdout_rows_excluded=len(holdout_examples) - len(holdout),
        training_home_win_rate=training_home_rate,
        model_metrics=model_metrics,
        home_baseline_metrics=baseline_metrics,
        paired_differences=point_differences,
        confidence_intervals=intervals,
        paired_difference_intervals=differences,
        calibration_bins=bins,
        expected_calibration_error=sum(
            item.prediction_count / len(predictions)
            * item.absolute_calibration_error
            for item in bins
        ),
        segments=segments,
        imputer_statistics=imputer_statistics,
        scaler_means=scaler_means,
        scaler_scales=scaler_scales,
        intercept=intercept,
        coefficients=coefficients,
        predictions=predictions,
        report_fingerprint=fingerprint,
    )


def nfl_final_holdout_evaluation_to_dict(
    evaluation: NflFinalHoldoutEvaluation,
) -> dict[str, Any]:
    payload = _holdout_report_payload(
        training_rows_available=evaluation.training_rows_available,
        training_rows_eligible=evaluation.training_rows_eligible,
        holdout_rows_available=evaluation.holdout_rows_available,
        holdout_rows_eligible=evaluation.holdout_rows_eligible,
        training_home_rate=evaluation.training_home_win_rate,
        model_metrics=evaluation.model_metrics,
        baseline_metrics=evaluation.home_baseline_metrics,
        point_differences=evaluation.paired_differences,
        intervals=evaluation.confidence_intervals,
        differences=evaluation.paired_difference_intervals,
        bins=evaluation.calibration_bins,
        segments=evaluation.segments,
        predictions=evaluation.predictions,
        imputer_statistics=evaluation.imputer_statistics,
        scaler_means=evaluation.scaler_means,
        scaler_scales=evaluation.scaler_scales,
        intercept=evaluation.intercept,
        coefficients=evaluation.coefficients,
    )
    payload["report_fingerprint"] = evaluation.report_fingerprint
    return payload


def _eligible(
    examples: tuple[NflMoneylineModelingExample, ...],
) -> tuple[NflMoneylineModelingExample, ...]:
    return tuple(
        item for item in examples
        if item.home_prior_games >= FROZEN_NFL_MINIMUM_HISTORY
        and item.away_prior_games >= FROZEN_NFL_MINIMUM_HISTORY
    )


def _validate_population(
    training: tuple[NflMoneylineModelingExample, ...],
    holdout: tuple[NflMoneylineModelingExample, ...],
) -> None:
    if not training or not holdout:
        raise ValueError("frozen NFL baseline populations cannot be empty")
    if any(item.season not in FROZEN_NFL_TRAINING_SEASONS for item in training):
        raise ValueError("training population must use NFL seasons 2018-2024")
    if {item.season for item in training} != set(FROZEN_NFL_TRAINING_SEASONS):
        raise ValueError("training population must contain every NFL season 2018-2024")
    if any(item.season != FROZEN_NFL_HOLDOUT_SEASON for item in holdout):
        raise ValueError("holdout population must use NFL season 2025")
    for name, examples in (("training", training), ("holdout", holdout)):
        if tuple(sorted(examples, key=lambda item: (item.kickoff, item.game_id))) != examples:
            raise ValueError(f"{name} population must be deterministically ordered")
        if len({item.game_id for item in examples}) != len(examples):
            raise ValueError(f"{name} population game IDs must be unique")
        if any(len(item.feature_values) != len(FROZEN_NFL_FEATURE_NAMES) for item in examples):
            raise ValueError(f"{name} population feature representation drift")


def _holdout_calibration_bins(
    predictions: tuple[NflFinalHoldoutPrediction, ...],
) -> tuple[NflCalibrationBin, ...]:
    count = round(1 / NFL_CALIBRATION_BIN_WIDTH)
    grouped: list[list[NflFinalHoldoutPrediction]] = [[] for _ in range(count)]
    for item in predictions:
        index = min(int(item.model_home_win_probability / NFL_CALIBRATION_BIN_WIDTH), count - 1)
        grouped[index].append(item)
    output = []
    for index, items in enumerate(grouped):
        if not items:
            continue
        mean_probability = sum(item.model_home_win_probability for item in items) / len(items)
        actual_rate = sum(item.actual_home_win for item in items) / len(items)
        output.append(NflCalibrationBin(
            lower_bound=index * NFL_CALIBRATION_BIN_WIDTH,
            upper_bound=min((index + 1) * NFL_CALIBRATION_BIN_WIDTH, 1.0),
            prediction_count=len(items),
            mean_predicted_probability=mean_probability,
            actual_home_win_rate=actual_rate,
            absolute_calibration_error=abs(mean_probability - actual_rate),
        ))
    return tuple(output)


def _holdout_bootstrap_intervals(
    predictions: tuple[NflFinalHoldoutPrediction, ...],
) -> tuple[NflMetricConfidenceIntervals, NflMetricConfidenceIntervals]:
    random = Random(NFL_BOOTSTRAP_SEED)
    indexes = tuple(range(len(predictions)))
    model_samples: list[tuple[float, float, float, float | None]] = []
    difference_samples: list[tuple[float, float, float]] = []
    for _ in range(NFL_BOOTSTRAP_ITERATIONS):
        sample = tuple(predictions[random.choice(indexes)] for _ in indexes)
        targets = [item.actual_home_win for item in sample]
        model = _raw_metric_values(
            targets, [item.model_home_win_probability for item in sample],
        )
        baseline = _raw_metric_values(
            targets, [item.home_baseline_probability for item in sample],
        )
        model_samples.append(model)
        difference_samples.append(tuple(
            model[index] - baseline[index] for index in range(3)
        ))
    aucs = [item[3] for item in model_samples if item[3] is not None]
    return (
        NflMetricConfidenceIntervals(
            accuracy=_interval([item[0] for item in model_samples]),
            log_loss=_interval([item[1] for item in model_samples]),
            brier_score=_interval([item[2] for item in model_samples]),
            roc_auc=_interval(aucs) if aucs else None,
        ),
        NflMetricConfidenceIntervals(
            accuracy=_interval([item[0] for item in difference_samples]),
            log_loss=_interval([item[1] for item in difference_samples]),
            brier_score=_interval([item[2] for item in difference_samples]),
            roc_auc=None,
        ),
    )


def _holdout_segments(
    predictions: tuple[NflFinalHoldoutPrediction, ...],
) -> tuple[NflSegmentEvaluation, ...]:
    return tuple(
        _holdout_segment(name, tuple(
            item for item in predictions if item.season_type is season_type
        ), minimum_rows=minimum)
        for name, season_type, minimum in (
            ("regular_season", NflSeasonType.REGULAR, 1),
            ("postseason", NflSeasonType.POSTSEASON, NFL_POSTSEASON_MINIMUM_REPORT_ROWS),
        )
    )


def _holdout_segment(
    name: str,
    predictions: tuple[NflFinalHoldoutPrediction, ...],
    *,
    minimum_rows: int,
) -> NflSegmentEvaluation:
    targets = [item.actual_home_win for item in predictions]
    metrics = None
    if len(predictions) >= minimum_rows and len(set(targets)) == 2:
        metrics = _metrics(
            targets, [item.model_home_win_probability for item in predictions],
        )
    return NflSegmentEvaluation(name=name, row_count=len(predictions), metrics=metrics)


def _holdout_report_payload(
    *,
    training_rows_available: int,
    training_rows_eligible: int,
    holdout_rows_available: int,
    holdout_rows_eligible: int,
    training_home_rate: float,
    model_metrics: NflProbabilityMetrics,
    baseline_metrics: NflProbabilityMetrics,
    point_differences: NflHoldoutMetricDifferences,
    intervals: NflMetricConfidenceIntervals,
    differences: NflMetricConfidenceIntervals,
    bins: tuple[NflCalibrationBin, ...],
    segments: tuple[NflSegmentEvaluation, ...],
    predictions: tuple[NflFinalHoldoutPrediction, ...],
    imputer_statistics: tuple[float, ...],
    scaler_means: tuple[float, ...],
    scaler_scales: tuple[float, ...],
    intercept: float,
    coefficients: tuple[float, ...],
) -> dict[str, Any]:
    return {
        "evaluation_notice": "THIS IS THE FINAL HISTORICAL 2025 HOLDOUT EVALUATION",
        "freeze_notice": "BASELINE SPECIFICATION WAS FROZEN BEFORE HOLDOUT EXPOSURE",
        "specification": _specification_to_dict(),
        "training_rows_available": training_rows_available,
        "training_rows_eligible": training_rows_eligible,
        "training_rows_excluded": training_rows_available - training_rows_eligible,
        "holdout_rows_available": holdout_rows_available,
        "holdout_rows_eligible": holdout_rows_eligible,
        "holdout_rows_excluded": holdout_rows_available - holdout_rows_eligible,
        "training_home_win_rate": training_home_rate,
        "model_metrics": _metrics_to_dict(model_metrics),
        "home_baseline_metrics": _metrics_to_dict(baseline_metrics),
        "paired_model_minus_baseline_differences": {
            "accuracy": point_differences.accuracy,
            "log_loss": point_differences.log_loss,
            "brier_score": point_differences.brier_score,
        },
        "confidence_intervals": _intervals_to_dict(intervals),
        "paired_model_minus_baseline_intervals": _intervals_to_dict(differences),
        "expected_calibration_error": sum(
            item.prediction_count / len(predictions) * item.absolute_calibration_error
            for item in bins
        ),
        "calibration_bins": [item.__dict__ for item in bins],
        "segments": [
            {
                "name": item.name,
                "row_count": item.row_count,
                "metrics": None if item.metrics is None else _metrics_to_dict(item.metrics),
            }
            for item in segments
        ],
        "eligible_holdout_game_ids": [item.game_id for item in predictions],
        "eligible_holdout_predictions": [
            {
                "game_id": item.game_id,
                "season": item.season,
                "season_type": item.season_type.value,
                "actual_home_win": item.actual_home_win,
                "model_home_win_probability": item.model_home_win_probability,
                "home_baseline_probability": item.home_baseline_probability,
            }
            for item in predictions
        ],
        "baseline_and_model_row_identity": True,
        "constant_baseline_roc_auc": "omitted_non_informative",
        "fitted_training_pipeline": {
            "imputer_statistics": list(imputer_statistics),
            "scaler_means": list(scaler_means),
            "scaler_scales": list(scaler_scales),
            "intercept": intercept,
            "coefficients": list(coefficients),
        },
    }


def _specification_to_dict() -> dict[str, Any]:
    spec = FROZEN_NFL_BASELINE_SPECIFICATION
    return {
        "specification_version": spec.specification_version,
        "model_purpose": spec.model_purpose,
        "target": spec.target,
        "target_ties_excluded": True,
        "training_seasons": list(spec.training_seasons),
        "holdout_season": spec.holdout_season,
        "minimum_history_per_team": spec.minimum_history_per_team,
        "feature_schema_version": spec.feature_schema_version,
        "feature_names": list(spec.feature_names),
        "model": {
            "classifier": "sklearn.linear_model.LogisticRegression",
            "C": spec.regularization_c,
            "solver": spec.solver,
            "max_iter": spec.max_iterations,
            "random_state": spec.random_state,
        },
        "preprocessing": {
            "imputation": spec.imputation,
            "scaling": spec.scaling,
            "fit_population": "eligible training rows only",
        },
        "bootstrap": {
            "iterations": NFL_BOOTSTRAP_ITERATIONS,
            "seed": NFL_BOOTSTRAP_SEED,
        },
        "early_season_covered": False,
    }


def _metrics_to_dict(item: NflProbabilityMetrics) -> dict[str, Any]:
    return {
        "accuracy": item.accuracy,
        "log_loss": item.log_loss,
        "brier_score": item.brier_score,
        "roc_auc": item.roc_auc,
        "mean_predicted_probability": item.mean_predicted_probability,
        "actual_home_win_rate": item.actual_home_win_rate,
    }


def _intervals_to_dict(item: NflMetricConfidenceIntervals) -> dict[str, Any]:
    def value(interval: NflConfidenceInterval | None) -> dict[str, float] | None:
        if interval is None:
            return None
        return {"lower": interval.lower, "upper": interval.upper}

    return {
        "accuracy": value(item.accuracy),
        "log_loss": value(item.log_loss),
        "brier_score": value(item.brier_score),
        "roc_auc": value(item.roc_auc),
    }
