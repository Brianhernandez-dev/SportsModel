from dataclasses import dataclass
from datetime import datetime
from math import ceil
from statistics import fmean

from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from sportsmodel.training.moneyline_baseline import (
    DEFAULT_REGULARIZATION_CANDIDATES,
    DEFAULT_TOP_FEATURE_COUNT,
    DEFAULT_TUNING_SPLITS,
    ClassificationMetrics,
    MoneylineTrainingDataset,
    RegularizationTuningResult,
    train_tuned_moneyline_baseline,
)


DEFAULT_INITIAL_TRAINING_ROWS = 300
DEFAULT_TEST_BLOCK_SIZE = 50
DEFAULT_CALIBRATION_BIN_WIDTH = 0.10


@dataclass(frozen=True)
class WalkForwardPrediction:
    """
    One out-of-sample prediction from a walk-forward fold.
    """

    fold_number: int

    game_id: int

    game_start_time: datetime

    actual_home_team_won: bool

    model_home_win_probability: float

    naive_home_win_probability: float


@dataclass(frozen=True)
class ProbabilityCalibrationBin:
    """
    Observed outcomes within one predicted-probability interval.
    """

    lower_bound: float

    upper_bound: float

    prediction_count: int

    mean_predicted_probability: float

    observed_home_win_rate: float

    absolute_calibration_error: float


@dataclass(frozen=True)
class MoneylineWalkForwardFold:
    """
    Result from one expanding-window evaluation fold.
    """

    fold_number: int

    training_rows: int

    test_rows: int

    training_start_time: datetime

    training_end_time: datetime

    test_start_time: datetime

    test_end_time: datetime

    active_feature_count: int

    selected_regularization_c: float

    model_metrics: ClassificationMetrics

    naive_baseline_metrics: ClassificationMetrics

    tuning: RegularizationTuningResult

    predictions: tuple[WalkForwardPrediction, ...]


@dataclass(frozen=True)
class MoneylineWalkForwardEvaluation:
    """
    Aggregate expanding-window Moneyline evaluation.
    """

    feature_schema_version: str

    dataset_rows: int

    initial_training_rows: int

    test_block_size: int

    folds: tuple[MoneylineWalkForwardFold, ...]

    predictions: tuple[WalkForwardPrediction, ...]

    aggregate_model_metrics: ClassificationMetrics

    aggregate_naive_baseline_metrics: ClassificationMetrics

    calibration_bins: tuple[
        ProbabilityCalibrationBin,
        ...,
    ]

    expected_calibration_error: float

    folds_beating_naive_log_loss: int

    folds_beating_naive_brier_score: int

    folds_beating_naive_accuracy: int

    @property
    def total_test_rows(self) -> int:
        return len(self.predictions)


def evaluate_moneyline_walk_forward(
    dataset: MoneylineTrainingDataset,
    *,
    initial_training_rows: int = (
        DEFAULT_INITIAL_TRAINING_ROWS
    ),
    test_block_size: int = DEFAULT_TEST_BLOCK_SIZE,
    top_feature_count: int = DEFAULT_TOP_FEATURE_COUNT,
    regularization_candidates: tuple[
        float,
        ...,
    ] = DEFAULT_REGULARIZATION_CANDIDATES,
    validation_splits: int = DEFAULT_TUNING_SPLITS,
    calibration_bin_width: float = (
        DEFAULT_CALIBRATION_BIN_WIDTH
    ),
) -> MoneylineWalkForwardEvaluation:
    """
    Evaluate a model using expanding chronological training windows.

    Each fold trains on all games before its test block. Regularization
    is tuned using only that fold's training period. Every game after
    the initial training window receives exactly one out-of-sample
    prediction.
    """

    _validate_walk_forward_configuration(
        dataset=dataset,
        initial_training_rows=initial_training_rows,
        test_block_size=test_block_size,
        calibration_bin_width=calibration_bin_width,
    )

    folds: list[MoneylineWalkForwardFold] = []
    all_predictions: list[WalkForwardPrediction] = []

    training_end_index = initial_training_rows
    fold_number = 1

    while training_end_index < len(dataset.examples):
        test_end_index = min(
            training_end_index + test_block_size,
            len(dataset.examples),
        )

        fold_examples = dataset.examples[
            :test_end_index
        ]

        fold_dataset = MoneylineTrainingDataset(
            feature_schema_version=(
                dataset.feature_schema_version
            ),
            feature_names=dataset.feature_names,
            examples=fold_examples,
        )

        fold_test_count = (
            test_end_index - training_end_index
        )

        fold_test_fraction = (
            fold_test_count / len(fold_examples)
        )

        evaluation, tuning = (
            train_tuned_moneyline_baseline(
                fold_dataset,
                test_fraction=fold_test_fraction,
                top_feature_count=top_feature_count,
                regularization_candidates=(
                    regularization_candidates
                ),
                validation_splits=validation_splits,
            )
        )

        if evaluation.training_rows != training_end_index:
            raise RuntimeError(
                "Walk-forward fold produced an unexpected "
                "training row count."
            )

        if evaluation.test_rows != fold_test_count:
            raise RuntimeError(
                "Walk-forward fold produced an unexpected "
                "test row count."
            )

        test_examples = dataset.examples[
            training_end_index:test_end_index
        ]

        fold_predictions = tuple(
            _predict_fold_example(
                fold_number=fold_number,
                dataset=dataset,
                example_index=example_index,
                model=evaluation.artifact,
                naive_probability=(
                    evaluation.training_home_win_rate
                ),
            )
            for example_index in range(
                training_end_index,
                test_end_index,
            )
        )

        recalculated_model_metrics = (
            _calculate_prediction_metrics(
                actual_values=[
                    prediction.actual_home_team_won
                    for prediction in fold_predictions
                ],
                probabilities=[
                    prediction.model_home_win_probability
                    for prediction in fold_predictions
                ],
            )
        )

        recalculated_naive_metrics = (
            _calculate_prediction_metrics(
                actual_values=[
                    prediction.actual_home_team_won
                    for prediction in fold_predictions
                ],
                probabilities=[
                    prediction.naive_home_win_probability
                    for prediction in fold_predictions
                ],
            )
        )

        if len(test_examples) != len(fold_predictions):
            raise RuntimeError(
                "Walk-forward prediction count does not match "
                "the fold test block."
            )

        fold = MoneylineWalkForwardFold(
            fold_number=fold_number,
            training_rows=evaluation.training_rows,
            test_rows=evaluation.test_rows,
            training_start_time=(
                evaluation.training_start_time
            ),
            training_end_time=evaluation.training_end_time,
            test_start_time=evaluation.test_start_time,
            test_end_time=evaluation.test_end_time,
            active_feature_count=len(
                evaluation.artifact.active_feature_names
            ),
            selected_regularization_c=(
                tuning.selected_c
            ),
            model_metrics=recalculated_model_metrics,
            naive_baseline_metrics=(
                recalculated_naive_metrics
            ),
            tuning=tuning,
            predictions=fold_predictions,
        )

        folds.append(fold)
        all_predictions.extend(fold_predictions)

        training_end_index = test_end_index
        fold_number += 1

    predictions = tuple(all_predictions)

    aggregate_model_metrics = _calculate_prediction_metrics(
        actual_values=[
            prediction.actual_home_team_won
            for prediction in predictions
        ],
        probabilities=[
            prediction.model_home_win_probability
            for prediction in predictions
        ],
    )

    aggregate_naive_metrics = _calculate_prediction_metrics(
        actual_values=[
            prediction.actual_home_team_won
            for prediction in predictions
        ],
        probabilities=[
            prediction.naive_home_win_probability
            for prediction in predictions
        ],
    )

    calibration_bins = _build_calibration_bins(
        predictions=predictions,
        bin_width=calibration_bin_width,
    )

    expected_calibration_error = sum(
        (
            calibration_bin.prediction_count
            / len(predictions)
        )
        * calibration_bin.absolute_calibration_error
        for calibration_bin in calibration_bins
    )

    return MoneylineWalkForwardEvaluation(
        feature_schema_version=dataset.feature_schema_version,
        dataset_rows=len(dataset.examples),
        initial_training_rows=initial_training_rows,
        test_block_size=test_block_size,
        folds=tuple(folds),
        predictions=predictions,
        aggregate_model_metrics=aggregate_model_metrics,
        aggregate_naive_baseline_metrics=(
            aggregate_naive_metrics
        ),
        calibration_bins=calibration_bins,
        expected_calibration_error=(
            expected_calibration_error
        ),
        folds_beating_naive_log_loss=sum(
            fold.model_metrics.log_loss
            < fold.naive_baseline_metrics.log_loss
            for fold in folds
        ),
        folds_beating_naive_brier_score=sum(
            fold.model_metrics.brier_score
            < fold.naive_baseline_metrics.brier_score
            for fold in folds
        ),
        folds_beating_naive_accuracy=sum(
            fold.model_metrics.accuracy
            > fold.naive_baseline_metrics.accuracy
            for fold in folds
        ),
    )


def _predict_fold_example(
    *,
    fold_number: int,
    dataset: MoneylineTrainingDataset,
    example_index: int,
    model,
    naive_probability: float,
) -> WalkForwardPrediction:
    example = dataset.examples[example_index]

    feature_mapping = dict(
        zip(
            dataset.feature_names,
            example.feature_values,
            strict=True,
        )
    )

    probability = model.predict_home_win_probability(
        feature_mapping
    )

    return WalkForwardPrediction(
        fold_number=fold_number,
        game_id=example.game_id,
        game_start_time=example.game_start_time,
        actual_home_team_won=example.home_team_won,
        model_home_win_probability=probability,
        naive_home_win_probability=naive_probability,
    )


def _calculate_prediction_metrics(
    *,
    actual_values: list[bool],
    probabilities: list[float],
) -> ClassificationMetrics:
    predictions = [
        probability >= 0.5
        for probability in probabilities
    ]

    try:
        roc_auc = float(
            roc_auc_score(
                actual_values,
                probabilities,
            )
        )
    except ValueError:
        roc_auc = None

    return ClassificationMetrics(
        accuracy=float(
            accuracy_score(
                actual_values,
                predictions,
            )
        ),
        log_loss=float(
            log_loss(
                actual_values,
                probabilities,
                labels=[
                    False,
                    True,
                ],
            )
        ),
        brier_score=float(
            brier_score_loss(
                actual_values,
                probabilities,
            )
        ),
        roc_auc=roc_auc,
    )


def _build_calibration_bins(
    *,
    predictions: tuple[WalkForwardPrediction, ...],
    bin_width: float,
) -> tuple[ProbabilityCalibrationBin, ...]:
    bin_count = ceil(1 / bin_width)

    predictions_by_bin: list[
        list[WalkForwardPrediction]
    ] = [
        []
        for _ in range(bin_count)
    ]

    for prediction in predictions:
        bin_index = min(
            int(
                prediction.model_home_win_probability
                / bin_width
            ),
            bin_count - 1,
        )

        predictions_by_bin[bin_index].append(
            prediction
        )

    calibration_bins: list[
        ProbabilityCalibrationBin
    ] = []

    for bin_index, bin_predictions in enumerate(
        predictions_by_bin
    ):
        if not bin_predictions:
            continue

        lower_bound = bin_index * bin_width
        upper_bound = min(
            (bin_index + 1) * bin_width,
            1.0,
        )

        mean_probability = fmean(
            prediction.model_home_win_probability
            for prediction in bin_predictions
        )

        observed_win_rate = fmean(
            float(
                prediction.actual_home_team_won
            )
            for prediction in bin_predictions
        )

        calibration_bins.append(
            ProbabilityCalibrationBin(
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                prediction_count=len(bin_predictions),
                mean_predicted_probability=mean_probability,
                observed_home_win_rate=observed_win_rate,
                absolute_calibration_error=abs(
                    mean_probability
                    - observed_win_rate
                ),
            )
        )

    return tuple(calibration_bins)


def _validate_walk_forward_configuration(
    *,
    dataset: MoneylineTrainingDataset,
    initial_training_rows: int,
    test_block_size: int,
    calibration_bin_width: float,
) -> None:
    if initial_training_rows <= 0:
        raise ValueError(
            "Initial training row count must be greater than zero."
        )

    if initial_training_rows >= len(dataset.examples):
        raise ValueError(
            "Initial training row count must be smaller than "
            "the dataset."
        )

    if test_block_size <= 0:
        raise ValueError(
            "Test block size must be greater than zero."
        )

    if not 0 < calibration_bin_width <= 1:
        raise ValueError(
            "Calibration bin width must be greater than zero "
            "and no greater than one."
        )
