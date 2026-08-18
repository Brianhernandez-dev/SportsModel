from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
import math
from random import Random
from statistics import fmean, pstdev
from typing import Any, Iterable

from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from sportsmodel.nfl.features import NFL_MONEYLINE_FEATURE_SCHEMA_VERSION
from sportsmodel.nfl.models import NflGame, NflSeasonType


NFL_BASELINE_REPRESENTATION_VERSION = "nfl_moneyline_matchup_0.1.0"
NFL_DEVELOPMENT_FIRST_SEASON = 2018
NFL_DEVELOPMENT_FINAL_SEASON = 2024
NFL_FINAL_HOLDOUT_SEASON = 2025
NFL_BASELINE_REGULARIZATION_C = 1.0
NFL_BASELINE_RANDOM_STATE = 42
NFL_BASELINE_SOLVER = "lbfgs"
NFL_BASELINE_MAX_ITERATIONS = 5000
NFL_CALIBRATION_BIN_WIDTH = 0.10
NFL_BASELINE_MINIMUM_RETENTION = 0.80
NFL_LABEL_SHUFFLE_SEED = 42
NFL_BOOTSTRAP_SEED = 20260818
NFL_BOOTSTRAP_ITERATIONS = 500
NFL_POSTSEASON_MINIMUM_REPORT_ROWS = 30

NFL_DEVELOPMENT_FOLDS = (
    (1, 2021, 2022),
    (2, 2022, 2023),
    (3, 2023, 2024),
)

_DIFFERENCE_SOURCE_SUFFIXES = (
    "prior_games_used",
    "win_percentage",
    "average_points_for",
    "average_points_against",
    "average_passing_yards",
    "average_passing_yards_allowed",
    "average_rushing_yards",
    "average_rushing_yards_allowed",
    "average_turnovers",
    "average_takeaways",
    "rolling_3_games_used",
    "rolling_3_average_points_for",
    "rolling_3_average_points_against",
    "rolling_3_average_turnover_differential",
    "rolling_5_games_used",
    "rolling_5_average_points_for",
    "rolling_5_average_points_against",
    "rolling_5_average_turnover_differential",
)

NFL_BASELINE_FEATURE_NAMES = (
    "minimum_prior_games",
    *(
        f"matchup_{suffix}_difference"
        for suffix in _DIFFERENCE_SOURCE_SUFFIXES
    ),
)


class NflMissingValuePolicy(StrEnum):
    TRAINING_MEDIAN = "training_median"
    MINIMUM_HISTORY_1 = "minimum_history_1"
    MINIMUM_HISTORY_3 = "minimum_history_3"
    MINIMUM_HISTORY_5 = "minimum_history_5"

    @property
    def minimum_history(self) -> int | None:
        return {
            self.TRAINING_MEDIAN: None,
            self.MINIMUM_HISTORY_1: 1,
            self.MINIMUM_HISTORY_3: 3,
            self.MINIMUM_HISTORY_5: 5,
        }[self]


NFL_MISSING_VALUE_POLICIES = tuple(NflMissingValuePolicy)


@dataclass(frozen=True)
class NflMoneylineModelingExample:
    game_id: int
    kickoff: datetime
    season: int
    season_type: NflSeasonType
    home_win: bool
    home_prior_games: int
    away_prior_games: int
    feature_values: tuple[float | None, ...]


@dataclass(frozen=True)
class NflProbabilityMetrics:
    accuracy: float
    log_loss: float
    brier_score: float
    roc_auc: float | None
    mean_predicted_probability: float
    actual_home_win_rate: float


@dataclass(frozen=True)
class NflFeatureCoefficient:
    feature_name: str
    coefficient: float


@dataclass(frozen=True)
class NflCalibrationBin:
    lower_bound: float
    upper_bound: float
    prediction_count: int
    mean_predicted_probability: float
    actual_home_win_rate: float
    absolute_calibration_error: float


@dataclass(frozen=True)
class NflFoldPrediction:
    game_id: int
    kickoff: datetime
    season: int
    season_type: NflSeasonType
    actual_home_win: bool
    model_home_win_probability: float
    home_baseline_probability: float
    shuffled_label_probability: float


@dataclass(frozen=True)
class NflBaselineFoldEvaluation:
    fold_number: int
    training_seasons: tuple[int, ...]
    validation_season: int
    training_rows_available: int
    training_rows_retained: int
    training_rows_excluded: int
    validation_rows_available: int
    validation_rows_evaluated: int
    validation_rows_excluded: int
    training_game_ids: tuple[int, ...]
    validation_game_ids: tuple[int, ...]
    training_end_time: datetime
    validation_start_time: datetime
    training_home_win_rate: float
    model_metrics: NflProbabilityMetrics
    home_baseline_metrics: NflProbabilityMetrics
    shuffled_label_metrics: NflProbabilityMetrics
    imputer_statistics: tuple[float, ...]
    scaler_means: tuple[float, ...]
    scaler_scales: tuple[float, ...]
    intercept: float
    coefficients: tuple[NflFeatureCoefficient, ...]
    predictions: tuple[NflFoldPrediction, ...]


@dataclass(frozen=True)
class NflMissingPolicyEvaluation:
    policy: NflMissingValuePolicy
    folds: tuple[NflBaselineFoldEvaluation, ...]
    selection_model_metrics: NflProbabilityMetrics
    selection_home_baseline_metrics: NflProbabilityMetrics
    selection_fold_log_loss_standard_deviation: float
    selection_training_rows_retained: int
    selection_training_rows_excluded: int
    selection_validation_rows_evaluated: int
    selection_validation_rows_excluded: int
    aggregate_model_metrics: NflProbabilityMetrics
    aggregate_home_baseline_metrics: NflProbabilityMetrics
    aggregate_shuffled_label_metrics: NflProbabilityMetrics
    calibration_bins: tuple[NflCalibrationBin, ...]
    expected_calibration_error: float
    fold_log_loss_standard_deviation: float
    total_training_rows_retained: int
    total_training_rows_excluded: int
    total_validation_rows_evaluated: int
    total_validation_rows_excluded: int

    @property
    def training_retention_rate(self) -> float:
        available = self.total_training_rows_retained + self.total_training_rows_excluded
        return self.total_training_rows_retained / available

    @property
    def validation_retention_rate(self) -> float:
        available = self.total_validation_rows_evaluated + self.total_validation_rows_excluded
        return self.total_validation_rows_evaluated / available

    @property
    def selection_training_retention_rate(self) -> float:
        available = (
            self.selection_training_rows_retained
            + self.selection_training_rows_excluded
        )
        return self.selection_training_rows_retained / available

    @property
    def selection_validation_retention_rate(self) -> float:
        available = (
            self.selection_validation_rows_evaluated
            + self.selection_validation_rows_excluded
        )
        return self.selection_validation_rows_evaluated / available

    @property
    def confirmation_fold(self) -> NflBaselineFoldEvaluation:
        return self.folds[-1]


@dataclass(frozen=True)
class NflConfidenceInterval:
    lower: float
    upper: float


@dataclass(frozen=True)
class NflMetricConfidenceIntervals:
    accuracy: NflConfidenceInterval
    log_loss: NflConfidenceInterval
    brier_score: NflConfidenceInterval
    roc_auc: NflConfidenceInterval | None


@dataclass(frozen=True)
class NflSegmentEvaluation:
    name: str
    row_count: int
    metrics: NflProbabilityMetrics | None


@dataclass(frozen=True)
class NflBaselineDevelopmentEvaluation:
    source_feature_schema_version: str
    representation_version: str
    feature_names: tuple[str, ...]
    policies: tuple[NflMissingPolicyEvaluation, ...]
    selected_policy: NflMissingValuePolicy
    selection_reason: str
    regularization_c: float
    solver: str
    random_state: int
    max_iterations: int
    bootstrap_iterations: int
    selected_aggregate_confidence_intervals: NflMetricConfidenceIntervals
    selected_paired_difference_intervals: NflMetricConfidenceIntervals
    confirmation_confidence_intervals: NflMetricConfidenceIntervals
    confirmation_paired_difference_intervals: NflMetricConfidenceIntervals
    selected_segments: tuple[NflSegmentEvaluation, ...]
    report_fingerprint: str

    @property
    def selected_evaluation(self) -> NflMissingPolicyEvaluation:
        return next(
            item for item in self.policies
            if item.policy is self.selected_policy
        )

    @property
    def selected_final_fold(self) -> NflBaselineFoldEvaluation:
        return self.selected_evaluation.folds[-1]


def build_nfl_moneyline_modeling_examples(
    rows: Iterable[dict[str, object]],
    canonical_games: Iterable[NflGame],
) -> tuple[NflMoneylineModelingExample, ...]:
    games = tuple(canonical_games)
    _reject_holdout_games(games)
    return _build_nfl_moneyline_modeling_examples(
        rows,
        games,
        allowed_seasons=frozenset(range(
            NFL_DEVELOPMENT_FIRST_SEASON,
            NFL_DEVELOPMENT_FINAL_SEASON + 1,
        )),
        population_label="development",
    )


def build_nfl_moneyline_holdout_examples(
    rows: Iterable[dict[str, object]],
    canonical_games: Iterable[NflGame],
) -> tuple[NflMoneylineModelingExample, ...]:
    """Build already-loaded holdout rows; this function performs no database I/O."""
    games = tuple(canonical_games)
    return _build_nfl_moneyline_modeling_examples(
        rows,
        games,
        allowed_seasons=frozenset({NFL_FINAL_HOLDOUT_SEASON}),
        population_label="final holdout",
    )


def _build_nfl_moneyline_modeling_examples(
    rows: Iterable[dict[str, object]],
    games: tuple[NflGame, ...],
    *,
    allowed_seasons: frozenset[int],
    population_label: str,
) -> tuple[NflMoneylineModelingExample, ...]:
    game_by_id = {game.game_id: game for game in games}
    if len(game_by_id) != len(games):
        raise ValueError("canonical NFL modeling games must have unique IDs")
    if any(game.season not in allowed_seasons for game in games):
        raise ValueError(
            f"canonical NFL {population_label} games have an invalid season"
        )

    examples: list[NflMoneylineModelingExample] = []
    seen_ids: set[int] = set()
    for row in rows:
        game_id = _required_int(row, "target_game_id")
        if game_id in seen_ids:
            raise ValueError(f"duplicate NFL modeling target game ID: {game_id}")
        seen_ids.add(game_id)
        game = game_by_id.get(game_id)
        if game is None:
            raise ValueError(f"NFL modeling row {game_id} has no canonical game")
        if game.season not in allowed_seasons:
            raise ValueError(
                f"NFL modeling row {game_id} is outside the {population_label} seasons"
            )
        if row.get("feature_schema_version") != NFL_MONEYLINE_FEATURE_SCHEMA_VERSION:
            raise ValueError(
                f"NFL modeling row {game_id} has an unsupported feature schema"
            )
        kickoff = row.get("target_kickoff")
        if not isinstance(kickoff, datetime):
            raise ValueError(f"NFL modeling row {game_id} kickoff must be a datetime")
        if kickoff.tzinfo is None or kickoff.utcoffset() is None:
            raise ValueError(f"NFL modeling row {game_id} kickoff must be timezone-aware")
        if kickoff != game.scheduled_start_time:
            raise ValueError(f"NFL modeling row {game_id} kickoff differs from canonical game")
        home_win = row.get("home_win")
        if not isinstance(home_win, bool):
            raise ValueError(f"NFL modeling row {game_id} target must be boolean")
        if game.home_score is None or game.away_score is None:
            raise ValueError(f"NFL modeling row {game_id} canonical game is not final")
        if home_win != (game.home_score > game.away_score):
            raise ValueError(f"NFL modeling row {game_id} target differs from canonical result")

        home_prior = _required_int(row, "home_prior_games_used")
        away_prior = _required_int(row, "away_prior_games_used")
        values: list[float | None] = [float(min(home_prior, away_prior))]
        for suffix in _DIFFERENCE_SOURCE_SUFFIXES:
            home_value = _optional_number(row, f"home_{suffix}")
            away_value = _optional_number(row, f"away_{suffix}")
            values.append(
                None
                if home_value is None or away_value is None
                else home_value - away_value
            )
        examples.append(NflMoneylineModelingExample(
            game_id=game_id,
            kickoff=kickoff,
            season=game.season,
            season_type=game.season_type,
            home_win=home_win,
            home_prior_games=home_prior,
            away_prior_games=away_prior,
            feature_values=tuple(values),
        ))

    ordered = tuple(sorted(
        examples,
        key=lambda item: (item.kickoff, item.game_id),
    ))
    if tuple(examples) != ordered:
        raise ValueError("NFL modeling rows must be in deterministic chronological order")
    if set(seen_ids) != {
        game.game_id for game in games
        if game.season in allowed_seasons and game.home_score != game.away_score
    }:
        raise ValueError("NFL modeling rows differ from canonical eligible target games")
    return ordered


def evaluate_nfl_moneyline_development(
    examples: Iterable[NflMoneylineModelingExample],
    *,
    policies: tuple[NflMissingValuePolicy, ...] = NFL_MISSING_VALUE_POLICIES,
    regularization_c: float = NFL_BASELINE_REGULARIZATION_C,
) -> NflBaselineDevelopmentEvaluation:
    ordered = tuple(examples)
    _validate_examples(ordered)
    if regularization_c <= 0:
        raise ValueError("regularization C must be positive")
    if not policies or len(policies) != len(set(policies)):
        raise ValueError("missing-value policies must be nonempty and unique")

    selection_results = tuple(
        _evaluate_policy(
            ordered,
            policy=policy,
            regularization_c=regularization_c,
            fold_definitions=NFL_DEVELOPMENT_FOLDS[:2],
        )
        for policy in policies
    )
    selection_winner, reason = _select_policy(selection_results)
    selected = _evaluate_policy(
        ordered,
        policy=selection_winner.policy,
        regularization_c=regularization_c,
        fold_definitions=NFL_DEVELOPMENT_FOLDS,
    )
    policy_results = tuple(
        selected if item.policy is selected.policy else item
        for item in selection_results
    )
    selected_predictions = tuple(
        prediction
        for fold in selected.folds
        for prediction in fold.predictions
    )
    (
        aggregate_intervals,
        aggregate_difference_intervals,
    ) = _bootstrap_intervals(
        selected_predictions,
        seed=NFL_BOOTSTRAP_SEED,
    )
    (
        confirmation_intervals,
        confirmation_difference_intervals,
    ) = _bootstrap_intervals(
        selected.confirmation_fold.predictions,
        seed=NFL_BOOTSTRAP_SEED + selected.confirmation_fold.fold_number,
    )
    segments = _segment_evaluations(selected_predictions)
    report_payload = _development_report_payload(
        policy_results,
        selected_policy=selected.policy,
        selection_reason=reason,
        regularization_c=regularization_c,
        aggregate_intervals=aggregate_intervals,
        aggregate_difference_intervals=aggregate_difference_intervals,
        confirmation_intervals=confirmation_intervals,
        confirmation_difference_intervals=confirmation_difference_intervals,
        segments=segments,
    )
    fingerprint = sha256(json.dumps(
        report_payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return NflBaselineDevelopmentEvaluation(
        source_feature_schema_version=NFL_MONEYLINE_FEATURE_SCHEMA_VERSION,
        representation_version=NFL_BASELINE_REPRESENTATION_VERSION,
        feature_names=NFL_BASELINE_FEATURE_NAMES,
        policies=policy_results,
        selected_policy=selected.policy,
        selection_reason=reason,
        regularization_c=regularization_c,
        solver=NFL_BASELINE_SOLVER,
        random_state=NFL_BASELINE_RANDOM_STATE,
        max_iterations=NFL_BASELINE_MAX_ITERATIONS,
        bootstrap_iterations=NFL_BOOTSTRAP_ITERATIONS,
        selected_aggregate_confidence_intervals=aggregate_intervals,
        selected_paired_difference_intervals=aggregate_difference_intervals,
        confirmation_confidence_intervals=confirmation_intervals,
        confirmation_paired_difference_intervals=(
            confirmation_difference_intervals
        ),
        selected_segments=segments,
        report_fingerprint=fingerprint,
    )


def nfl_development_evaluation_to_dict(
    evaluation: NflBaselineDevelopmentEvaluation,
) -> dict[str, Any]:
    payload = _development_report_payload(
        evaluation.policies,
        selected_policy=evaluation.selected_policy,
        selection_reason=evaluation.selection_reason,
        regularization_c=evaluation.regularization_c,
        aggregate_intervals=evaluation.selected_aggregate_confidence_intervals,
        aggregate_difference_intervals=(
            evaluation.selected_paired_difference_intervals
        ),
        confirmation_intervals=evaluation.confirmation_confidence_intervals,
        confirmation_difference_intervals=(
            evaluation.confirmation_paired_difference_intervals
        ),
        segments=evaluation.selected_segments,
    )
    payload["report_fingerprint"] = evaluation.report_fingerprint
    return payload


def _evaluate_policy(
    examples: tuple[NflMoneylineModelingExample, ...],
    *,
    policy: NflMissingValuePolicy,
    regularization_c: float,
    fold_definitions: tuple[tuple[int, int, int], ...],
) -> NflMissingPolicyEvaluation:
    folds = tuple(
        _evaluate_fold(
            examples,
            fold_number=fold_number,
            training_final_season=training_final_season,
            validation_season=validation_season,
            policy=policy,
            regularization_c=regularization_c,
        )
        for fold_number, training_final_season, validation_season
        in fold_definitions
    )
    predictions = tuple(
        prediction
        for fold in folds
        for prediction in fold.predictions
    )
    selection_folds = folds[:2]
    selection_predictions = tuple(
        prediction
        for fold in selection_folds
        for prediction in fold.predictions
    )
    selection_targets = [
        item.actual_home_win for item in selection_predictions
    ]
    selection_model_probabilities = [
        item.model_home_win_probability for item in selection_predictions
    ]
    selection_baseline_probabilities = [
        item.home_baseline_probability for item in selection_predictions
    ]
    model_probabilities = [
        item.model_home_win_probability for item in predictions
    ]
    baseline_probabilities = [
        item.home_baseline_probability for item in predictions
    ]
    shuffled_probabilities = [
        item.shuffled_label_probability for item in predictions
    ]
    targets = [item.actual_home_win for item in predictions]
    calibration = _calibration_bins(predictions)
    return NflMissingPolicyEvaluation(
        policy=policy,
        folds=folds,
        selection_model_metrics=_metrics(
            selection_targets, selection_model_probabilities,
        ),
        selection_home_baseline_metrics=_metrics(
            selection_targets, selection_baseline_probabilities,
            include_auc=False,
        ),
        selection_fold_log_loss_standard_deviation=pstdev(
            fold.model_metrics.log_loss for fold in selection_folds
        ),
        selection_training_rows_retained=sum(
            fold.training_rows_retained for fold in selection_folds
        ),
        selection_training_rows_excluded=sum(
            fold.training_rows_excluded for fold in selection_folds
        ),
        selection_validation_rows_evaluated=len(selection_predictions),
        selection_validation_rows_excluded=sum(
            fold.validation_rows_excluded for fold in selection_folds
        ),
        aggregate_model_metrics=_metrics(targets, model_probabilities),
        aggregate_home_baseline_metrics=_metrics(
            targets, baseline_probabilities, include_auc=False,
        ),
        aggregate_shuffled_label_metrics=_metrics(
            targets, shuffled_probabilities,
        ),
        calibration_bins=calibration,
        expected_calibration_error=sum(
            (item.prediction_count / len(predictions))
            * item.absolute_calibration_error
            for item in calibration
        ),
        fold_log_loss_standard_deviation=pstdev(
            fold.model_metrics.log_loss for fold in folds
        ),
        total_training_rows_retained=sum(
            fold.training_rows_retained for fold in folds
        ),
        total_training_rows_excluded=sum(
            fold.training_rows_excluded for fold in folds
        ),
        total_validation_rows_evaluated=len(predictions),
        total_validation_rows_excluded=sum(
            fold.validation_rows_excluded for fold in folds
        ),
    )


def _evaluate_fold(
    examples: tuple[NflMoneylineModelingExample, ...],
    *,
    fold_number: int,
    training_final_season: int,
    validation_season: int,
    policy: NflMissingValuePolicy,
    regularization_c: float,
) -> NflBaselineFoldEvaluation:
    available_training = tuple(
        item for item in examples
        if NFL_DEVELOPMENT_FIRST_SEASON <= item.season <= training_final_season
    )
    available_validation = tuple(
        item for item in examples if item.season == validation_season
    )
    training = _apply_policy(available_training, policy)
    validation = _apply_policy(available_validation, policy)
    if not training or not validation:
        raise ValueError(
            f"policy {policy.value} leaves fold {fold_number} empty"
        )
    if training[-1].kickoff >= validation[0].kickoff:
        raise ValueError(f"fold {fold_number} is not chronologically isolated")
    targets = [item.home_win for item in training]
    if len(set(targets)) != 2:
        raise ValueError(f"fold {fold_number} training data needs both classes")

    training_matrix = _matrix(training)
    validation_matrix = _matrix(validation)
    if any(
        all(math.isnan(row[index]) for row in training_matrix)
        for index in range(len(NFL_BASELINE_FEATURE_NAMES))
    ):
        raise ValueError(f"fold {fold_number} has an all-missing predetermined feature")

    pipeline = _pipeline(regularization_c)
    pipeline.fit(training_matrix, targets)
    probabilities = [
        float(value)
        for value in pipeline.predict_proba(validation_matrix)[:, 1]
    ]
    shuffled_targets = list(targets)
    Random(NFL_LABEL_SHUFFLE_SEED + fold_number).shuffle(shuffled_targets)
    shuffled_pipeline = _pipeline(regularization_c)
    shuffled_pipeline.fit(training_matrix, shuffled_targets)
    shuffled_probabilities = [
        float(value)
        for value in shuffled_pipeline.predict_proba(validation_matrix)[:, 1]
    ]
    training_home_rate = sum(targets) / len(targets)
    baseline_probabilities = [training_home_rate] * len(validation)
    predictions = tuple(
        NflFoldPrediction(
            game_id=item.game_id,
            kickoff=item.kickoff,
            season=item.season,
            season_type=item.season_type,
            actual_home_win=item.home_win,
            model_home_win_probability=probability,
            home_baseline_probability=training_home_rate,
            shuffled_label_probability=shuffled_probability,
        )
        for item, probability, shuffled_probability in zip(
            validation, probabilities, shuffled_probabilities, strict=True,
        )
    )
    imputer: SimpleImputer = pipeline.named_steps["imputer"]
    scaler: StandardScaler = pipeline.named_steps["scaler"]
    classifier: LogisticRegression = pipeline.named_steps["classifier"]
    coefficients = tuple(
        NflFeatureCoefficient(name, float(value))
        for name, value in zip(
            NFL_BASELINE_FEATURE_NAMES,
            classifier.coef_[0],
            strict=True,
        )
    )
    return NflBaselineFoldEvaluation(
        fold_number=fold_number,
        training_seasons=tuple(range(
            NFL_DEVELOPMENT_FIRST_SEASON, training_final_season + 1,
        )),
        validation_season=validation_season,
        training_rows_available=len(available_training),
        training_rows_retained=len(training),
        training_rows_excluded=len(available_training) - len(training),
        validation_rows_available=len(available_validation),
        validation_rows_evaluated=len(validation),
        validation_rows_excluded=len(available_validation) - len(validation),
        training_game_ids=tuple(item.game_id for item in training),
        validation_game_ids=tuple(item.game_id for item in validation),
        training_end_time=training[-1].kickoff,
        validation_start_time=validation[0].kickoff,
        training_home_win_rate=training_home_rate,
        model_metrics=_metrics(
            [item.home_win for item in validation], probabilities,
        ),
        home_baseline_metrics=_metrics(
            [item.home_win for item in validation], baseline_probabilities,
            include_auc=False,
        ),
        shuffled_label_metrics=_metrics(
            [item.home_win for item in validation], shuffled_probabilities,
        ),
        imputer_statistics=tuple(float(value) for value in imputer.statistics_),
        scaler_means=tuple(float(value) for value in scaler.mean_),
        scaler_scales=tuple(float(value) for value in scaler.scale_),
        intercept=float(classifier.intercept_[0]),
        coefficients=coefficients,
        predictions=predictions,
    )


def _apply_policy(
    examples: tuple[NflMoneylineModelingExample, ...],
    policy: NflMissingValuePolicy,
) -> tuple[NflMoneylineModelingExample, ...]:
    minimum = policy.minimum_history
    if minimum is None:
        return examples
    return tuple(
        item for item in examples
        if item.home_prior_games >= minimum
        and item.away_prior_games >= minimum
    )


def _pipeline(regularization_c: float) -> Pipeline:
    return Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median", add_indicator=False)),
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(
            C=regularization_c,
            solver=NFL_BASELINE_SOLVER,
            max_iter=NFL_BASELINE_MAX_ITERATIONS,
            random_state=NFL_BASELINE_RANDOM_STATE,
        )),
    ])


def _matrix(
    examples: tuple[NflMoneylineModelingExample, ...],
) -> list[list[float]]:
    return [
        [math.nan if value is None else value for value in item.feature_values]
        for item in examples
    ]


def _metrics(
    targets: list[bool], probabilities: list[float],
    *,
    include_auc: bool = True,
) -> NflProbabilityMetrics:
    predicted = [value >= 0.5 for value in probabilities]
    auc = None
    if include_auc:
        try:
            auc = float(roc_auc_score(targets, probabilities))
        except ValueError:
            auc = None
    return NflProbabilityMetrics(
        accuracy=float(accuracy_score(targets, predicted)),
        log_loss=float(log_loss(targets, probabilities, labels=[False, True])),
        brier_score=float(brier_score_loss(targets, probabilities)),
        roc_auc=auc,
        mean_predicted_probability=fmean(probabilities),
        actual_home_win_rate=fmean(float(value) for value in targets),
    )


def _calibration_bins(
    predictions: tuple[NflFoldPrediction, ...],
) -> tuple[NflCalibrationBin, ...]:
    bin_count = round(1 / NFL_CALIBRATION_BIN_WIDTH)
    grouped: list[list[NflFoldPrediction]] = [[] for _ in range(bin_count)]
    for item in predictions:
        index = min(
            int(item.model_home_win_probability / NFL_CALIBRATION_BIN_WIDTH),
            bin_count - 1,
        )
        grouped[index].append(item)
    bins = []
    for index, items in enumerate(grouped):
        if not items:
            continue
        predicted = fmean(item.model_home_win_probability for item in items)
        actual = fmean(float(item.actual_home_win) for item in items)
        bins.append(NflCalibrationBin(
            lower_bound=index * NFL_CALIBRATION_BIN_WIDTH,
            upper_bound=min((index + 1) * NFL_CALIBRATION_BIN_WIDTH, 1.0),
            prediction_count=len(items),
            mean_predicted_probability=predicted,
            actual_home_win_rate=actual,
            absolute_calibration_error=abs(predicted - actual),
        ))
    return tuple(bins)


def _bootstrap_intervals(
    predictions: tuple[NflFoldPrediction, ...],
    *,
    seed: int,
) -> tuple[NflMetricConfidenceIntervals, NflMetricConfidenceIntervals]:
    if not predictions:
        raise ValueError("bootstrap predictions cannot be empty")
    random = Random(seed)
    model_samples: list[tuple[float, float, float, float | None]] = []
    difference_samples: list[tuple[float, float, float]] = []
    indexes = tuple(range(len(predictions)))
    for _ in range(NFL_BOOTSTRAP_ITERATIONS):
        sample = tuple(
            predictions[random.choice(indexes)]
            for _ in indexes
        )
        targets = [item.actual_home_win for item in sample]
        model_probabilities = [
            item.model_home_win_probability for item in sample
        ]
        baseline_probabilities = [
            item.home_baseline_probability for item in sample
        ]
        model = _raw_metric_values(targets, model_probabilities)
        baseline = _raw_metric_values(targets, baseline_probabilities)
        model_samples.append(model)
        difference_samples.append((
            model[0] - baseline[0],
            model[1] - baseline[1],
            model[2] - baseline[2],
        ))

    auc_values = [
        sample[3] for sample in model_samples if sample[3] is not None
    ]
    model_intervals = NflMetricConfidenceIntervals(
        accuracy=_interval([sample[0] for sample in model_samples]),
        log_loss=_interval([sample[1] for sample in model_samples]),
        brier_score=_interval([sample[2] for sample in model_samples]),
        roc_auc=_interval(auc_values) if auc_values else None,
    )
    difference_intervals = NflMetricConfidenceIntervals(
        accuracy=_interval([sample[0] for sample in difference_samples]),
        log_loss=_interval([sample[1] for sample in difference_samples]),
        brier_score=_interval([sample[2] for sample in difference_samples]),
        roc_auc=None,
    )
    return model_intervals, difference_intervals


def _raw_metric_values(
    targets: list[bool], probabilities: list[float],
) -> tuple[float, float, float, float | None]:
    count = len(targets)
    accuracy = sum(
        (probability >= 0.5) is target
        for target, probability in zip(targets, probabilities, strict=True)
    ) / count
    epsilon = 1e-15
    log_loss_value = -sum(
        math.log(min(max(probability, epsilon), 1 - epsilon))
        if target
        else math.log(min(max(1 - probability, epsilon), 1 - epsilon))
        for target, probability in zip(targets, probabilities, strict=True)
    ) / count
    brier = sum(
        (probability - float(target)) ** 2
        for target, probability in zip(targets, probabilities, strict=True)
    ) / count
    return accuracy, log_loss_value, brier, _roc_auc(targets, probabilities)


def _roc_auc(
    targets: list[bool], probabilities: list[float],
) -> float | None:
    positive_count = sum(targets)
    negative_count = len(targets) - positive_count
    if positive_count == 0 or negative_count == 0:
        return None
    ordered = sorted(
        zip(probabilities, targets, strict=True),
        key=lambda item: item[0],
    )
    positive_rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = ((index + 1) + end) / 2
        positive_rank_sum += average_rank * sum(
            target for _, target in ordered[index:end]
        )
        index = end
    return (
        positive_rank_sum - positive_count * (positive_count + 1) / 2
    ) / (positive_count * negative_count)


def _interval(values: list[float]) -> NflConfidenceInterval:
    ordered = sorted(values)
    return NflConfidenceInterval(
        lower=_percentile(ordered, 0.025),
        upper=_percentile(ordered, 0.975),
    )


def _percentile(ordered: list[float], quantile: float) -> float:
    position = quantile * (len(ordered) - 1)
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    weight = position - lower_index
    return (
        ordered[lower_index] * (1 - weight)
        + ordered[upper_index] * weight
    )


def _segment_evaluations(
    predictions: tuple[NflFoldPrediction, ...],
) -> tuple[NflSegmentEvaluation, ...]:
    regular = tuple(
        item for item in predictions
        if item.season_type is NflSeasonType.REGULAR
    )
    postseason = tuple(
        item for item in predictions
        if item.season_type is NflSeasonType.POSTSEASON
    )
    return (
        _segment("regular_season", regular, minimum_rows=1),
        _segment(
            "postseason", postseason,
            minimum_rows=NFL_POSTSEASON_MINIMUM_REPORT_ROWS,
        ),
    )


def _segment(
    name: str,
    predictions: tuple[NflFoldPrediction, ...],
    *,
    minimum_rows: int,
) -> NflSegmentEvaluation:
    targets = [item.actual_home_win for item in predictions]
    metrics = None
    if len(predictions) >= minimum_rows and len(set(targets)) == 2:
        metrics = _metrics(
            targets,
            [item.model_home_win_probability for item in predictions],
        )
    return NflSegmentEvaluation(
        name=name,
        row_count=len(predictions),
        metrics=metrics,
    )


def _select_policy(
    evaluations: tuple[NflMissingPolicyEvaluation, ...],
) -> tuple[NflMissingPolicyEvaluation, str]:
    coverage_eligible = tuple(
        item for item in evaluations
        if item.selection_training_retention_rate >= NFL_BASELINE_MINIMUM_RETENTION
        and item.selection_validation_retention_rate >= NFL_BASELINE_MINIMUM_RETENTION
    )
    if not coverage_eligible:
        raise ValueError("no missing-value policy meets the minimum retention contract")
    rank_scores = _policy_selection_rank_scores(coverage_eligible)
    selected = min(coverage_eligible, key=lambda item: (
        rank_scores[item.policy],
        item.selection_model_metrics.log_loss,
        item.selection_model_metrics.brier_score,
        -(
            item.selection_model_metrics.roc_auc
            if item.selection_model_metrics.roc_auc is not None
            else -math.inf
        ),
        -item.selection_model_metrics.accuracy,
        item.selection_fold_log_loss_standard_deviation,
        -item.selection_validation_rows_evaluated,
        tuple(NflMissingValuePolicy).index(item.policy),
    ))
    return selected, (
        "Used only folds 1-2 (2022-2023 validation), required at least 80% "
        "retention in both training and validation, and selected the qualifying "
        "policy with the best equal-weight ordinal rank across pooled log loss, "
        "Brier score, ROC-AUC, accuracy, two-fold log-loss stability, and "
        "retention. Log loss, Brier score, ROC-AUC, accuracy, stability, "
        "retained rows, and predefined simplicity order are deterministic "
        "tie-breakers. Fold 3 (2024) was not evaluated for unselected policies "
        "and was used only to confirm the already-fixed policy."
    )


def _policy_selection_rank_scores(
    evaluations: tuple[NflMissingPolicyEvaluation, ...],
) -> dict[NflMissingValuePolicy, int]:
    def dense_ranks(
        values: dict[NflMissingValuePolicy, float],
        *,
        higher_is_better: bool,
    ) -> dict[NflMissingValuePolicy, int]:
        ordered = sorted(set(values.values()), reverse=higher_is_better)
        rank_by_value = {value: rank for rank, value in enumerate(ordered)}
        return {
            policy: rank_by_value[value]
            for policy, value in values.items()
        }

    criteria = (
        dense_ranks({
            item.policy: item.selection_model_metrics.log_loss
            for item in evaluations
        }, higher_is_better=False),
        dense_ranks({
            item.policy: item.selection_model_metrics.brier_score
            for item in evaluations
        }, higher_is_better=False),
        dense_ranks({
            item.policy: (
                item.selection_model_metrics.roc_auc
                if item.selection_model_metrics.roc_auc is not None
                else -math.inf
            )
            for item in evaluations
        }, higher_is_better=True),
        dense_ranks({
            item.policy: item.selection_model_metrics.accuracy
            for item in evaluations
        }, higher_is_better=True),
        dense_ranks({
            item.policy: item.selection_fold_log_loss_standard_deviation
            for item in evaluations
        }, higher_is_better=False),
        dense_ranks({
            item.policy: min(
                item.selection_training_retention_rate,
                item.selection_validation_retention_rate,
            )
            for item in evaluations
        }, higher_is_better=True),
    )
    return {
        item.policy: sum(ranks[item.policy] for ranks in criteria)
        for item in evaluations
    }


def _validate_examples(
    examples: tuple[NflMoneylineModelingExample, ...],
) -> None:
    if not examples:
        raise ValueError("NFL development examples cannot be empty")
    if any(item.season >= NFL_FINAL_HOLDOUT_SEASON for item in examples):
        raise ValueError("2025 holdout examples cannot enter Phase 2D evaluation")
    if any(
        item.season < NFL_DEVELOPMENT_FIRST_SEASON
        or item.season > NFL_DEVELOPMENT_FINAL_SEASON
        for item in examples
    ):
        raise ValueError("NFL development examples must be from 2018-2024")
    if tuple(sorted(
        examples, key=lambda item: (item.kickoff, item.game_id),
    )) != examples:
        raise ValueError("NFL development examples must be chronologically ordered")
    if len({item.game_id for item in examples}) != len(examples):
        raise ValueError("NFL development examples must have unique game IDs")
    if any(len(item.feature_values) != len(NFL_BASELINE_FEATURE_NAMES) for item in examples):
        raise ValueError("NFL development feature value count differs from schema")
    present_seasons = {item.season for item in examples}
    required_seasons = set(range(
        NFL_DEVELOPMENT_FIRST_SEASON, NFL_DEVELOPMENT_FINAL_SEASON + 1,
    ))
    if not required_seasons.issubset(present_seasons):
        raise ValueError("NFL development examples must cover every season 2018-2024")


def _reject_holdout_games(games: tuple[NflGame, ...]) -> None:
    if any(game.season >= NFL_FINAL_HOLDOUT_SEASON for game in games):
        raise ValueError("2025 holdout games cannot be loaded into Phase 2D modeling")


def _required_int(row: dict[str, object], name: str) -> int:
    value = row.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"NFL modeling field {name} must be a nonnegative integer")
    return value


def _optional_number(
    row: dict[str, object], name: str,
) -> float | None:
    value = row.get(name)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"NFL modeling field {name} must be numeric or None")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"NFL modeling field {name} must be finite")
    return numeric


def _development_report_payload(
    policies: tuple[NflMissingPolicyEvaluation, ...],
    *,
    selected_policy: NflMissingValuePolicy,
    selection_reason: str,
    regularization_c: float,
    aggregate_intervals: NflMetricConfidenceIntervals,
    aggregate_difference_intervals: NflMetricConfidenceIntervals,
    confirmation_intervals: NflMetricConfidenceIntervals,
    confirmation_difference_intervals: NflMetricConfidenceIntervals,
    segments: tuple[NflSegmentEvaluation, ...],
) -> dict[str, Any]:
    selected = next(item for item in policies if item.policy is selected_policy)
    return {
        "source_feature_schema_version": NFL_MONEYLINE_FEATURE_SCHEMA_VERSION,
        "representation_version": NFL_BASELINE_REPRESENTATION_VERSION,
        "feature_names": list(NFL_BASELINE_FEATURE_NAMES),
        "feature_count": len(NFL_BASELINE_FEATURE_NAMES),
        "selected_policy": selected_policy.value,
        "selection_reason": selection_reason,
        "model_settings": {
            "classifier": "sklearn.linear_model.LogisticRegression",
            "regularization_c": regularization_c,
            "solver": NFL_BASELINE_SOLVER,
            "max_iterations": NFL_BASELINE_MAX_ITERATIONS,
            "random_state": NFL_BASELINE_RANDOM_STATE,
            "imputer": "training-fold median",
            "scaler": "training-fold standardization",
            "bootstrap_iterations": NFL_BOOTSTRAP_ITERATIONS,
            "bootstrap_seed": NFL_BOOTSTRAP_SEED,
            "label_shuffle_seed": NFL_LABEL_SHUFFLE_SEED,
        },
        "development_folds": [
            {
                "fold_number": fold,
                "train_seasons": [NFL_DEVELOPMENT_FIRST_SEASON, train_end],
                "validation_season": validation,
            }
            for fold, train_end, validation in NFL_DEVELOPMENT_FOLDS
        ],
        "holdout": {
            "season": NFL_FINAL_HOLDOUT_SEASON,
            "loaded": False,
            "evaluated": False,
        },
        "policy_selection_stage": {
            "validation_seasons": [2022, 2023],
            "folds_used": [1, 2],
            "fold_3_used": False,
        },
        "confirmation_stage": {
            "validation_season": 2024,
            "fold_number": 3,
            "selected_policy_fixed_before_evaluation": True,
            "metrics": _metrics_to_dict(
                selected.confirmation_fold.model_metrics
            ),
            "confidence_intervals": _intervals_to_dict(
                confirmation_intervals
            ),
            "paired_differences_vs_home_baseline": _intervals_to_dict(
                confirmation_difference_intervals
            ),
        },
        "post_selection_descriptive_aggregate": {
            "metrics": _metrics_to_dict(selected.aggregate_model_metrics),
            "confidence_intervals": _intervals_to_dict(aggregate_intervals),
            "paired_differences_vs_home_baseline": _intervals_to_dict(
                aggregate_difference_intervals
            ),
        },
        "coverage_scope": _coverage_scope(selected_policy),
        "segments": [_segment_to_dict(item) for item in segments],
        "policies": [_policy_to_dict(item) for item in policies],
    }


def _policy_to_dict(item: NflMissingPolicyEvaluation) -> dict[str, Any]:
    return {
        "policy": item.policy.value,
        "minimum_history": item.policy.minimum_history,
        "selection_training_rows_retained": item.selection_training_rows_retained,
        "selection_training_rows_excluded": item.selection_training_rows_excluded,
        "selection_training_retention_rate": item.selection_training_retention_rate,
        "selection_validation_rows_evaluated": item.selection_validation_rows_evaluated,
        "selection_validation_rows_excluded": item.selection_validation_rows_excluded,
        "selection_validation_retention_rate": item.selection_validation_retention_rate,
        "selection_model_metrics": _metrics_to_dict(item.selection_model_metrics),
        "selection_home_baseline_metrics": _metrics_to_dict(
            item.selection_home_baseline_metrics
        ),
        "selection_fold_log_loss_standard_deviation": (
            item.selection_fold_log_loss_standard_deviation
        ),
        "total_training_rows_retained": item.total_training_rows_retained,
        "total_training_rows_excluded": item.total_training_rows_excluded,
        "training_retention_rate": item.training_retention_rate,
        "total_validation_rows_evaluated": item.total_validation_rows_evaluated,
        "total_validation_rows_excluded": item.total_validation_rows_excluded,
        "validation_retention_rate": item.validation_retention_rate,
        "post_selection_descriptive_aggregate_model_metrics": _metrics_to_dict(
            item.aggregate_model_metrics
        ),
        "aggregate_home_baseline_metrics": _metrics_to_dict(
            item.aggregate_home_baseline_metrics
        ),
        "aggregate_shuffled_label_metrics": _metrics_to_dict(
            item.aggregate_shuffled_label_metrics
        ),
        "fold_log_loss_standard_deviation": item.fold_log_loss_standard_deviation,
        "expected_calibration_error": item.expected_calibration_error,
        "calibration_bins": [
            {
                "lower_bound": value.lower_bound,
                "upper_bound": value.upper_bound,
                "prediction_count": value.prediction_count,
                "mean_predicted_probability": value.mean_predicted_probability,
                "actual_home_win_rate": value.actual_home_win_rate,
                "absolute_calibration_error": value.absolute_calibration_error,
            }
            for value in item.calibration_bins
        ],
        "folds": [_fold_to_dict(value) for value in item.folds],
    }


def _fold_to_dict(item: NflBaselineFoldEvaluation) -> dict[str, Any]:
    return {
        "fold_number": item.fold_number,
        "training_seasons": list(item.training_seasons),
        "validation_season": item.validation_season,
        "training_rows_available": item.training_rows_available,
        "training_rows_retained": item.training_rows_retained,
        "training_rows_excluded": item.training_rows_excluded,
        "validation_rows_available": item.validation_rows_available,
        "validation_rows_evaluated": item.validation_rows_evaluated,
        "validation_rows_excluded": item.validation_rows_excluded,
        "training_end_time": item.training_end_time.astimezone(timezone.utc).isoformat(),
        "validation_start_time": item.validation_start_time.astimezone(timezone.utc).isoformat(),
        "training_home_win_rate": item.training_home_win_rate,
        "model_metrics": _metrics_to_dict(item.model_metrics),
        "home_baseline_metrics": _metrics_to_dict(item.home_baseline_metrics),
        "shuffled_label_metrics": _metrics_to_dict(item.shuffled_label_metrics),
        "imputer_statistics": list(item.imputer_statistics),
        "scaler_means": list(item.scaler_means),
        "scaler_scales": list(item.scaler_scales),
        "intercept": item.intercept,
        "coefficients": [
            {"feature_name": value.feature_name, "coefficient": value.coefficient}
            for value in item.coefficients
        ],
        "validation_game_ids": list(item.validation_game_ids),
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
    return {
        "accuracy": _interval_to_dict(item.accuracy),
        "log_loss": _interval_to_dict(item.log_loss),
        "brier_score": _interval_to_dict(item.brier_score),
        "roc_auc": (
            None if item.roc_auc is None else _interval_to_dict(item.roc_auc)
        ),
    }


def _interval_to_dict(item: NflConfidenceInterval) -> dict[str, float]:
    return {"lower": item.lower, "upper": item.upper}


def _segment_to_dict(item: NflSegmentEvaluation) -> dict[str, Any]:
    return {
        "name": item.name,
        "row_count": item.row_count,
        "metrics": None if item.metrics is None else _metrics_to_dict(item.metrics),
    }


def _coverage_scope(policy: NflMissingValuePolicy) -> dict[str, Any]:
    minimum = policy.minimum_history
    if minimum is None:
        return {
            "full_season_model": True,
            "minimum_prior_games_per_team": None,
            "statement": "Training-fold median imputation covers zero-history games.",
        }
    return {
        "full_season_model": False,
        "minimum_prior_games_per_team": minimum,
        "statement": (
            "This baseline does not cover early-season games. It may be used only "
            f"after both teams have at least {minimum} same-season prior eligible "
            "games; earlier weeks require a future explicit strategy and must not "
            "be silently imputed or predicted by this model."
        ),
    }
