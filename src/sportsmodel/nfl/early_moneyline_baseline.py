from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from random import Random
from statistics import fmean
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

from sportsmodel.nfl.early_dataset_audit import early_dataset_fingerprint
from sportsmodel.nfl.early_features import (
    NFL_EARLY_MONEYLINE_FEATURE_NAMES,
    NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION,
)
from sportsmodel.nfl.moneyline_baseline import (
    NflCalibrationBin,
    NflConfidenceInterval,
    NflFeatureCoefficient,
    NflMetricConfidenceIntervals,
    NflProbabilityMetrics,
)


NFL_EARLY_BASELINE_SPECIFICATION_VERSION = "nfl_moneyline_early_baseline_0.1.0"
NFL_EARLY_DATASET_FINGERPRINT = (
    "a88db604039fb277d63813152912ccfcc89b31b3938b12fdcdb38553d2f83b98"
)
NFL_EARLY_BASELINE_C = 1.0
NFL_EARLY_BASELINE_SOLVER = "lbfgs"
NFL_EARLY_BASELINE_MAX_ITERATIONS = 5000
NFL_EARLY_BASELINE_RANDOM_STATE = 42
NFL_EARLY_LABEL_SHUFFLE_SEED = 20260819
NFL_EARLY_BOOTSTRAP_SEED = 20260820
NFL_EARLY_BOOTSTRAP_ITERATIONS = 1000
NFL_EARLY_CALIBRATION_BIN_COUNT = 5
NFL_EARLY_DEVELOPMENT_FOLDS = (
    (1, (2019, 2020), 2021),
    (2, (2019, 2020, 2021), 2022),
    (3, (2019, 2020, 2021, 2022), 2023),
)
NFL_EARLY_CONFIRMATION_TRAINING_SEASONS = (2019, 2020, 2021, 2022, 2023)
NFL_EARLY_CONFIRMATION_SEASON = 2024
NFL_EARLY_ALLOWED_SEASONS = frozenset(range(2019, 2025))
NFL_EARLY_PRIOR_ONLY_FEATURE_NAMES = (
    "prior_season_games_played_difference",
    "prior_season_win_percentage_difference",
    "prior_season_average_point_differential_difference",
    "prior_season_average_turnover_differential_difference",
    "neutral_site",
)
_PRIOR_ONLY_INDEXES = tuple(
    NFL_EARLY_MONEYLINE_FEATURE_NAMES.index(name)
    for name in NFL_EARLY_PRIOR_ONLY_FEATURE_NAMES
)


@dataclass(frozen=True)
class NFLEarlyMoneylineModelingExample:
    game_id: int
    kickoff: datetime
    season: int
    home_win: bool
    minimum_current_prior_games: int
    neutral_site: bool
    feature_values: tuple[float | None, ...]


@dataclass(frozen=True)
class NFLEarlyFoldPrediction:
    game_id: int
    kickoff: datetime
    season: int
    minimum_current_prior_games: int
    actual_home_win: bool
    model_home_win_probability: float
    home_baseline_probability: float
    prior_only_probability: float
    shuffled_label_probability: float | None


@dataclass(frozen=True)
class NFLEarlyFoldEvaluation:
    fold_number: int
    training_seasons: tuple[int, ...]
    validation_season: int
    training_rows: int
    validation_rows: int
    training_game_ids: tuple[int, ...]
    validation_game_ids: tuple[int, ...]
    training_end_time: datetime
    validation_start_time: datetime
    training_home_win_rate: float
    model_metrics: NflProbabilityMetrics
    home_baseline_metrics: NflProbabilityMetrics
    prior_only_metrics: NflProbabilityMetrics
    shuffled_label_metrics: NflProbabilityMetrics | None
    imputer_statistics: tuple[float, ...]
    scaler_means: tuple[float, ...]
    scaler_scales: tuple[float, ...]
    intercept: float
    coefficients: tuple[NflFeatureCoefficient, ...]
    predictions: tuple[NFLEarlyFoldPrediction, ...]


@dataclass(frozen=True)
class NFLEarlyHistoryStateEvaluation:
    minimum_current_prior_games: int
    row_count: int
    metrics: NflProbabilityMetrics


@dataclass(frozen=True)
class NFLEarlySensitivityFold:
    fold_number: int
    training_rows_without_2020: int
    validation_rows: int
    metrics: NflProbabilityMetrics


@dataclass(frozen=True)
class NFLEarlySensitivityEvaluation:
    folds: tuple[NFLEarlySensitivityFold, ...]
    pooled_metrics: NflProbabilityMetrics


@dataclass(frozen=True)
class NFLEarlyBaselineEvaluation:
    specification_version: str
    dataset_fingerprint: str
    source_feature_schema_version: str
    feature_names: tuple[str, ...]
    development_folds: tuple[NFLEarlyFoldEvaluation, ...]
    development_model_metrics: NflProbabilityMetrics
    development_home_baseline_metrics: NflProbabilityMetrics
    development_prior_only_metrics: NflProbabilityMetrics
    development_shuffled_label_metrics: NflProbabilityMetrics
    development_confidence_intervals: NflMetricConfidenceIntervals
    development_paired_difference_intervals: NflMetricConfidenceIntervals
    development_calibration_bins: tuple[NflCalibrationBin, ...]
    development_expected_calibration_error: float
    development_history_states: tuple[NFLEarlyHistoryStateEvaluation, ...]
    confirmation: NFLEarlyFoldEvaluation
    confirmation_confidence_intervals: NflMetricConfidenceIntervals
    confirmation_paired_difference_intervals: NflMetricConfidenceIntervals
    confirmation_calibration_bins: tuple[NflCalibrationBin, ...]
    confirmation_expected_calibration_error: float
    confirmation_history_states: tuple[NFLEarlyHistoryStateEvaluation, ...]
    sensitivity_without_2020: NFLEarlySensitivityEvaluation
    development_neutral_site_rows: int
    confirmation_neutral_site_rows: int
    report_fingerprint: str


def assert_nfl_early_production_dataset_contract(
    rows: Iterable[dict[str, object]],
    dataset_fingerprint: str,
) -> None:
    materialized = tuple(rows)
    computed = early_dataset_fingerprint(materialized)
    if dataset_fingerprint != computed:
        raise ValueError("reported early dataset fingerprint differs from its rows")
    if dataset_fingerprint != NFL_EARLY_DATASET_FINGERPRINT:
        raise ValueError("early dataset fingerprint differs from the locked Phase 3A1 input")
    if len(materialized) != 285:
        raise ValueError("locked Phase 3A1 early dataset must contain 285 rows")


def build_nfl_early_modeling_examples(
    rows: Iterable[dict[str, object]],
) -> tuple[NFLEarlyMoneylineModelingExample, ...]:
    materialized = tuple(rows)
    examples: list[NFLEarlyMoneylineModelingExample] = []
    seen_ids: set[int] = set()
    forbidden_model_fields = {
        "home_win",
        "target_tie",
        "target_game_id",
        "target_kickoff",
        "feature_cutoff",
        "home_team_id",
        "away_team_id",
    }
    if forbidden_model_fields.intersection(NFL_EARLY_MONEYLINE_FEATURE_NAMES):
        raise RuntimeError("target or identity metadata is present in the model schema")

    for row in materialized:
        game_id = _required_int(row, "target_game_id")
        if game_id in seen_ids:
            raise ValueError(f"duplicate early modeling target game ID: {game_id}")
        seen_ids.add(game_id)
        season = _required_int(row, "target_season")
        if season not in NFL_EARLY_ALLOWED_SEASONS:
            raise ValueError("early modeling rows must be limited to seasons 2019-2024")
        if row.get("feature_schema_version") != (
            NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION
        ):
            raise ValueError(f"early modeling row {game_id} has the wrong schema")
        if row.get("route") != "early":
            raise ValueError(f"early modeling row {game_id} is not early-route")
        if tuple(row.get("feature_names", ())) != (
            NFL_EARLY_MONEYLINE_FEATURE_NAMES
        ):
            raise ValueError(f"early modeling row {game_id} feature order differs")
        raw_values = row.get("feature_values")
        if not isinstance(raw_values, (tuple, list)):
            raise ValueError(f"early modeling row {game_id} needs an ordered vector")
        if len(raw_values) != len(NFL_EARLY_MONEYLINE_FEATURE_NAMES):
            raise ValueError(f"early modeling row {game_id} feature count differs")
        values = tuple(_optional_number(value, game_id) for value in raw_values)
        for name, value in zip(
            NFL_EARLY_MONEYLINE_FEATURE_NAMES,
            values,
            strict=True,
        ):
            if not _same_number(row.get(name), value):
                raise ValueError(
                    f"early modeling row {game_id} named feature {name} differs"
                )
        kickoff = row.get("target_kickoff")
        if not isinstance(kickoff, datetime):
            raise ValueError(f"early modeling row {game_id} kickoff must be datetime")
        if kickoff.tzinfo is None or kickoff.utcoffset() is None:
            raise ValueError(f"early modeling row {game_id} kickoff must be aware")
        home_win = row.get("home_win")
        if not isinstance(home_win, bool):
            raise ValueError(f"early modeling row {game_id} home_win must be boolean")
        minimum = _required_int(row, "minimum_current_prior_games")
        if minimum not in {0, 1, 2}:
            raise ValueError(f"early modeling row {game_id} has invalid history state")
        neutral_value = values[-1]
        if neutral_value not in {0.0, 1.0}:
            raise ValueError(f"early modeling row {game_id} neutral_site is invalid")
        examples.append(NFLEarlyMoneylineModelingExample(
            game_id=game_id,
            kickoff=kickoff,
            season=season,
            home_win=home_win,
            minimum_current_prior_games=minimum,
            neutral_site=bool(neutral_value),
            feature_values=values,
        ))

    ordered = tuple(sorted(
        examples,
        key=lambda item: (item.kickoff, item.game_id),
    ))
    if tuple(examples) != ordered:
        raise ValueError("early modeling rows must be chronologically ordered")
    return ordered


def evaluate_nfl_early_moneyline_baseline(
    examples: Iterable[NFLEarlyMoneylineModelingExample],
    *,
    dataset_fingerprint: str,
) -> NFLEarlyBaselineEvaluation:
    ordered = tuple(examples)
    _validate_examples(ordered)
    development_folds = tuple(
        _evaluate_fold(
            ordered,
            fold_number=fold_number,
            training_seasons=training_seasons,
            validation_season=validation_season,
            shuffle_training_labels=True,
        )
        for fold_number, training_seasons, validation_season
        in NFL_EARLY_DEVELOPMENT_FOLDS
    )
    development_predictions = tuple(
        prediction
        for fold in development_folds
        for prediction in fold.predictions
    )
    development_model = _prediction_metrics(
        development_predictions,
        "model_home_win_probability",
    )
    development_home = _prediction_metrics(
        development_predictions,
        "home_baseline_probability",
        include_auc=False,
    )
    development_prior = _prediction_metrics(
        development_predictions,
        "prior_only_probability",
    )
    development_shuffled = _prediction_metrics(
        development_predictions,
        "shuffled_label_probability",
    )
    development_intervals, development_differences = _bootstrap_intervals(
        development_predictions,
        seed=NFL_EARLY_BOOTSTRAP_SEED,
    )
    development_bins = _calibration_bins(development_predictions)

    confirmation = _evaluate_fold(
        ordered,
        fold_number=4,
        training_seasons=NFL_EARLY_CONFIRMATION_TRAINING_SEASONS,
        validation_season=NFL_EARLY_CONFIRMATION_SEASON,
        shuffle_training_labels=False,
    )
    confirmation_intervals, confirmation_differences = _bootstrap_intervals(
        confirmation.predictions,
        seed=NFL_EARLY_BOOTSTRAP_SEED + 1,
    )
    confirmation_bins = _calibration_bins(confirmation.predictions)
    sensitivity = _evaluate_without_2020(ordered)

    report_without_fingerprint = _report_payload(
        dataset_fingerprint=dataset_fingerprint,
        development_folds=development_folds,
        development_model=development_model,
        development_home=development_home,
        development_prior=development_prior,
        development_shuffled=development_shuffled,
        development_intervals=development_intervals,
        development_differences=development_differences,
        development_bins=development_bins,
        development_history_states=_history_states(development_predictions),
        confirmation=confirmation,
        confirmation_intervals=confirmation_intervals,
        confirmation_differences=confirmation_differences,
        confirmation_bins=confirmation_bins,
        confirmation_history_states=_history_states(confirmation.predictions),
        sensitivity=sensitivity,
        development_neutral_site_rows=sum(
            item.neutral_site
            for item in ordered
            if item.season in {2021, 2022, 2023}
        ),
        confirmation_neutral_site_rows=sum(
            item.neutral_site for item in ordered if item.season == 2024
        ),
    )
    fingerprint = sha256(json.dumps(
        report_without_fingerprint,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return NFLEarlyBaselineEvaluation(
        specification_version=NFL_EARLY_BASELINE_SPECIFICATION_VERSION,
        dataset_fingerprint=dataset_fingerprint,
        source_feature_schema_version=(
            NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION
        ),
        feature_names=NFL_EARLY_MONEYLINE_FEATURE_NAMES,
        development_folds=development_folds,
        development_model_metrics=development_model,
        development_home_baseline_metrics=development_home,
        development_prior_only_metrics=development_prior,
        development_shuffled_label_metrics=development_shuffled,
        development_confidence_intervals=development_intervals,
        development_paired_difference_intervals=development_differences,
        development_calibration_bins=development_bins,
        development_expected_calibration_error=_ece(
            development_bins,
            len(development_predictions),
        ),
        development_history_states=_history_states(development_predictions),
        confirmation=confirmation,
        confirmation_confidence_intervals=confirmation_intervals,
        confirmation_paired_difference_intervals=confirmation_differences,
        confirmation_calibration_bins=confirmation_bins,
        confirmation_expected_calibration_error=_ece(
            confirmation_bins,
            len(confirmation.predictions),
        ),
        confirmation_history_states=_history_states(confirmation.predictions),
        sensitivity_without_2020=sensitivity,
        development_neutral_site_rows=sum(
            item.neutral_site
            for item in ordered
            if item.season in {2021, 2022, 2023}
        ),
        confirmation_neutral_site_rows=sum(
            item.neutral_site for item in ordered if item.season == 2024
        ),
        report_fingerprint=fingerprint,
    )


def nfl_early_baseline_evaluation_to_dict(
    evaluation: NFLEarlyBaselineEvaluation,
) -> dict[str, Any]:
    payload = _canonical(asdict(evaluation))
    return payload


def _evaluate_fold(
    examples,
    *,
    fold_number,
    training_seasons,
    validation_season,
    shuffle_training_labels,
) -> NFLEarlyFoldEvaluation:
    training = tuple(item for item in examples if item.season in training_seasons)
    validation = tuple(item for item in examples if item.season == validation_season)
    if not training or not validation:
        raise ValueError(f"early fold {fold_number} has an empty population")
    if training[-1].kickoff >= validation[0].kickoff:
        raise ValueError(f"early fold {fold_number} is not chronological")
    targets = [item.home_win for item in training]
    if len(set(targets)) != 2:
        raise ValueError(f"early fold {fold_number} training needs both classes")
    training_matrix = _matrix(training)
    validation_matrix = _matrix(validation)
    _assert_no_all_missing_feature(training_matrix, fold_number)

    pipeline = _pipeline()
    pipeline.fit(training_matrix, targets)
    _assert_pipeline_dimensions(pipeline)
    model_probabilities = _probabilities(pipeline, validation_matrix)
    home_probability = fmean(float(value) for value in targets)
    home_probabilities = [home_probability] * len(validation)

    prior_pipeline = _pipeline()
    prior_pipeline.fit(
        _matrix(training, indexes=_PRIOR_ONLY_INDEXES),
        targets,
    )
    prior_probabilities = _probabilities(
        prior_pipeline,
        _matrix(validation, indexes=_PRIOR_ONLY_INDEXES),
    )

    shuffled_probabilities: list[float] | None = None
    shuffled_metrics: NflProbabilityMetrics | None = None
    if shuffle_training_labels:
        shuffled_targets = list(targets)
        Random(NFL_EARLY_LABEL_SHUFFLE_SEED + fold_number).shuffle(
            shuffled_targets
        )
        shuffled_pipeline = _pipeline()
        shuffled_pipeline.fit(training_matrix, shuffled_targets)
        shuffled_probabilities = _probabilities(
            shuffled_pipeline,
            validation_matrix,
        )
        shuffled_metrics = _metrics(
            [item.home_win for item in validation],
            shuffled_probabilities,
        )

    predictions = tuple(
        NFLEarlyFoldPrediction(
            game_id=item.game_id,
            kickoff=item.kickoff,
            season=item.season,
            minimum_current_prior_games=item.minimum_current_prior_games,
            actual_home_win=item.home_win,
            model_home_win_probability=model_probability,
            home_baseline_probability=home_baseline_probability,
            prior_only_probability=prior_probability,
            shuffled_label_probability=(
                None
                if shuffled_probabilities is None
                else shuffled_probabilities[index]
            ),
        )
        for index, (
            item,
            model_probability,
            home_baseline_probability,
            prior_probability,
        ) in enumerate(zip(
            validation,
            model_probabilities,
            home_probabilities,
            prior_probabilities,
            strict=True,
        ))
    )
    imputer: SimpleImputer = pipeline.named_steps["imputer"]
    scaler: StandardScaler = pipeline.named_steps["scaler"]
    classifier: LogisticRegression = pipeline.named_steps["classifier"]
    return NFLEarlyFoldEvaluation(
        fold_number=fold_number,
        training_seasons=tuple(training_seasons),
        validation_season=validation_season,
        training_rows=len(training),
        validation_rows=len(validation),
        training_game_ids=tuple(item.game_id for item in training),
        validation_game_ids=tuple(item.game_id for item in validation),
        training_end_time=training[-1].kickoff,
        validation_start_time=validation[0].kickoff,
        training_home_win_rate=home_probability,
        model_metrics=_metrics(
            [item.home_win for item in validation],
            model_probabilities,
        ),
        home_baseline_metrics=_metrics(
            [item.home_win for item in validation],
            home_probabilities,
            include_auc=False,
        ),
        prior_only_metrics=_metrics(
            [item.home_win for item in validation],
            prior_probabilities,
        ),
        shuffled_label_metrics=shuffled_metrics,
        imputer_statistics=tuple(float(value) for value in imputer.statistics_),
        scaler_means=tuple(float(value) for value in scaler.mean_),
        scaler_scales=tuple(float(value) for value in scaler.scale_),
        intercept=float(classifier.intercept_[0]),
        coefficients=tuple(
            NflFeatureCoefficient(name, float(value))
            for name, value in zip(
                NFL_EARLY_MONEYLINE_FEATURE_NAMES,
                classifier.coef_[0],
                strict=True,
            )
        ),
        predictions=predictions,
    )


def _evaluate_without_2020(examples) -> NFLEarlySensitivityEvaluation:
    folds: list[NFLEarlySensitivityFold] = []
    all_targets: list[bool] = []
    all_probabilities: list[float] = []
    for fold_number, training_seasons, validation_season in (
        NFL_EARLY_DEVELOPMENT_FOLDS
    ):
        sensitivity_seasons = tuple(
            season for season in training_seasons if season != 2020
        )
        training = tuple(
            item for item in examples if item.season in sensitivity_seasons
        )
        validation = tuple(
            item for item in examples if item.season == validation_season
        )
        pipeline = _pipeline()
        pipeline.fit(_matrix(training), [item.home_win for item in training])
        probabilities = _probabilities(pipeline, _matrix(validation))
        targets = [item.home_win for item in validation]
        folds.append(NFLEarlySensitivityFold(
            fold_number=fold_number,
            training_rows_without_2020=len(training),
            validation_rows=len(validation),
            metrics=_metrics(targets, probabilities),
        ))
        all_targets.extend(targets)
        all_probabilities.extend(probabilities)
    return NFLEarlySensitivityEvaluation(
        folds=tuple(folds),
        pooled_metrics=_metrics(all_targets, all_probabilities),
    )


def _pipeline() -> Pipeline:
    return Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median", add_indicator=False)),
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(
            C=NFL_EARLY_BASELINE_C,
            solver=NFL_EARLY_BASELINE_SOLVER,
            max_iter=NFL_EARLY_BASELINE_MAX_ITERATIONS,
            random_state=NFL_EARLY_BASELINE_RANDOM_STATE,
        )),
    ])


def _matrix(examples, *, indexes=None) -> list[list[float]]:
    selected = tuple(range(len(NFL_EARLY_MONEYLINE_FEATURE_NAMES))) if (
        indexes is None
    ) else tuple(indexes)
    return [
        [
            math.nan if item.feature_values[index] is None
            else item.feature_values[index]
            for index in selected
        ]
        for item in examples
    ]


def _probabilities(pipeline, matrix) -> list[float]:
    return [float(value) for value in pipeline.predict_proba(matrix)[:, 1]]


def _metrics(targets, probabilities, *, include_auc=True) -> NflProbabilityMetrics:
    probabilities = list(probabilities)
    targets = list(targets)
    predicted = [value >= 0.5 for value in probabilities]
    auc = None
    if include_auc and len(set(targets)) == 2:
        auc = float(roc_auc_score(targets, probabilities))
    return NflProbabilityMetrics(
        accuracy=float(accuracy_score(targets, predicted)),
        log_loss=float(log_loss(targets, probabilities, labels=[False, True])),
        brier_score=float(brier_score_loss(targets, probabilities)),
        roc_auc=auc,
        mean_predicted_probability=fmean(probabilities),
        actual_home_win_rate=fmean(float(value) for value in targets),
    )


def _prediction_metrics(predictions, field, *, include_auc=True):
    probabilities = [getattr(item, field) for item in predictions]
    if any(value is None for value in probabilities):
        raise ValueError(f"prediction field {field} is unavailable")
    return _metrics(
        [item.actual_home_win for item in predictions],
        probabilities,
        include_auc=include_auc,
    )


def _calibration_bins(predictions) -> tuple[NflCalibrationBin, ...]:
    grouped = [[] for _ in range(NFL_EARLY_CALIBRATION_BIN_COUNT)]
    for item in predictions:
        index = min(
            int(item.model_home_win_probability * NFL_EARLY_CALIBRATION_BIN_COUNT),
            NFL_EARLY_CALIBRATION_BIN_COUNT - 1,
        )
        grouped[index].append(item)
    result = []
    width = 1 / NFL_EARLY_CALIBRATION_BIN_COUNT
    for index, items in enumerate(grouped):
        if not items:
            continue
        predicted = fmean(item.model_home_win_probability for item in items)
        actual = fmean(float(item.actual_home_win) for item in items)
        result.append(NflCalibrationBin(
            lower_bound=index * width,
            upper_bound=(index + 1) * width,
            prediction_count=len(items),
            mean_predicted_probability=predicted,
            actual_home_win_rate=actual,
            absolute_calibration_error=abs(predicted - actual),
        ))
    return tuple(result)


def _ece(bins, count):
    return sum(
        item.prediction_count / count * item.absolute_calibration_error
        for item in bins
    )


def _bootstrap_intervals(predictions, *, seed):
    random = Random(seed)
    indexes = tuple(range(len(predictions)))
    model_samples = []
    difference_samples = []
    for _ in range(NFL_EARLY_BOOTSTRAP_ITERATIONS):
        sample = tuple(predictions[random.choice(indexes)] for _ in indexes)
        targets = [item.actual_home_win for item in sample]
        model = _raw_metrics(
            targets,
            [item.model_home_win_probability for item in sample],
        )
        baseline = _raw_metrics(
            targets,
            [item.home_baseline_probability for item in sample],
        )
        model_samples.append(model)
        difference_samples.append((
            model[0] - baseline[0],
            model[1] - baseline[1],
            model[2] - baseline[2],
        ))
    auc_values = [item[3] for item in model_samples if item[3] is not None]
    return (
        NflMetricConfidenceIntervals(
            accuracy=_interval([item[0] for item in model_samples]),
            log_loss=_interval([item[1] for item in model_samples]),
            brier_score=_interval([item[2] for item in model_samples]),
            roc_auc=_interval(auc_values) if auc_values else None,
        ),
        NflMetricConfidenceIntervals(
            accuracy=_interval([item[0] for item in difference_samples]),
            log_loss=_interval([item[1] for item in difference_samples]),
            brier_score=_interval([item[2] for item in difference_samples]),
            roc_auc=None,
        ),
    )


def _raw_metrics(targets, probabilities):
    count = len(targets)
    accuracy = sum(
        (probability >= 0.5) is target
        for target, probability in zip(targets, probabilities, strict=True)
    ) / count
    epsilon = 1e-15
    loss = -sum(
        math.log(min(max(probability, epsilon), 1 - epsilon))
        if target
        else math.log(min(max(1 - probability, epsilon), 1 - epsilon))
        for target, probability in zip(targets, probabilities, strict=True)
    ) / count
    brier = sum(
        (probability - float(target)) ** 2
        for target, probability in zip(targets, probabilities, strict=True)
    ) / count
    auc = None
    if len(set(targets)) == 2:
        auc = float(roc_auc_score(targets, probabilities))
    return accuracy, loss, brier, auc


def _interval(values) -> NflConfidenceInterval:
    ordered = sorted(values)
    return NflConfidenceInterval(
        lower=_percentile(ordered, 0.025),
        upper=_percentile(ordered, 0.975),
    )


def _percentile(ordered, quantile):
    position = quantile * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _history_states(predictions):
    return tuple(
        NFLEarlyHistoryStateEvaluation(
            minimum_current_prior_games=state,
            row_count=len(items),
            metrics=_prediction_metrics(items, "model_home_win_probability"),
        )
        for state in (0, 1, 2)
        if (items := tuple(
            item
            for item in predictions
            if item.minimum_current_prior_games == state
        ))
    )


def _validate_examples(examples):
    if not examples:
        raise ValueError("early modeling examples cannot be empty")
    if tuple(examples) != tuple(sorted(
        examples,
        key=lambda item: (item.kickoff, item.game_id),
    )):
        raise ValueError("early modeling examples must be chronological")
    if len({item.game_id for item in examples}) != len(examples):
        raise ValueError("early modeling game IDs must be unique")
    seasons = {item.season for item in examples}
    if not seasons.issubset(NFL_EARLY_ALLOWED_SEASONS):
        raise ValueError("early modeling examples cannot include 2025 or later")
    required = set(range(2019, 2025))
    if seasons != required:
        raise ValueError("early baseline evaluation requires seasons 2019-2024")
    if any(
        len(item.feature_values) != len(NFL_EARLY_MONEYLINE_FEATURE_NAMES)
        for item in examples
    ):
        raise ValueError("early modeling feature dimensionality differs")


def _assert_no_all_missing_feature(matrix, fold_number):
    for index in range(len(NFL_EARLY_MONEYLINE_FEATURE_NAMES)):
        if all(math.isnan(row[index]) for row in matrix):
            raise ValueError(
                f"early fold {fold_number} has an all-missing predefined feature"
            )


def _assert_pipeline_dimensions(pipeline):
    imputer: SimpleImputer = pipeline.named_steps["imputer"]
    classifier: LogisticRegression = pipeline.named_steps["classifier"]
    if len(imputer.statistics_) != len(NFL_EARLY_MONEYLINE_FEATURE_NAMES):
        raise RuntimeError("early imputer changed feature dimensionality")
    if classifier.n_features_in_ != len(NFL_EARLY_MONEYLINE_FEATURE_NAMES):
        raise RuntimeError("early classifier received the wrong feature count")


def _report_payload(**values):
    return _canonical({
        "specification_version": NFL_EARLY_BASELINE_SPECIFICATION_VERSION,
        "source_feature_schema_version": (
            NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION
        ),
        "feature_names": NFL_EARLY_MONEYLINE_FEATURE_NAMES,
        "preprocessing": {
            "imputer": "SimpleImputer(strategy='median', add_indicator=False)",
            "scaler": "StandardScaler()",
            "fit_scope": "training rows only",
        },
        "model": {
            "classifier": "LogisticRegression",
            "C": NFL_EARLY_BASELINE_C,
            "solver": NFL_EARLY_BASELINE_SOLVER,
            "max_iter": NFL_EARLY_BASELINE_MAX_ITERATIONS,
            "random_state": NFL_EARLY_BASELINE_RANDOM_STATE,
        },
        "development_fold_contract": NFL_EARLY_DEVELOPMENT_FOLDS,
        "confirmation_contract": {
            "training_seasons": NFL_EARLY_CONFIRMATION_TRAINING_SEASONS,
            "confirmation_season": NFL_EARLY_CONFIRMATION_SEASON,
            "used_for_development_choice": False,
        },
        "bootstrap": {
            "iterations": NFL_EARLY_BOOTSTRAP_ITERATIONS,
            "seed": NFL_EARLY_BOOTSTRAP_SEED,
        },
        "calibration_bin_count": NFL_EARLY_CALIBRATION_BIN_COUNT,
        "prior_only_diagnostic_features": NFL_EARLY_PRIOR_ONLY_FEATURE_NAMES,
        "values": values,
    })


def _canonical(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _canonical(asdict(value))
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("early baseline report cannot contain nonfinite values")
    return value


def _required_int(row, name):
    value = row.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"early modeling field {name} must be an integer")
    return value


def _optional_number(value, game_id):
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"early modeling row {game_id} has a nonnumeric feature")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"early modeling row {game_id} has a nonfinite feature")
    return numeric


def _same_number(left, right):
    if left is None or right is None:
        return left is right
    if not isinstance(left, (int, float)) or isinstance(left, bool):
        return False
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)
