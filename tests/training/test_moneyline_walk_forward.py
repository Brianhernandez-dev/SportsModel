from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.training.moneyline_baseline import (
    MoneylineTrainingDataset,
    MoneylineTrainingExample,
)
from sportsmodel.training.moneyline_walk_forward import (
    evaluate_moneyline_walk_forward,
)


def test_walk_forward_predicts_each_post_training_game_once() -> None:
    dataset = _build_dataset(
        example_count=120,
    )

    evaluation = evaluate_moneyline_walk_forward(
        dataset,
        initial_training_rows=60,
        test_block_size=20,
        regularization_candidates=(
            0.01,
            0.10,
            1.00,
        ),
        validation_splits=3,
    )

    assert len(evaluation.folds) == 3
    assert evaluation.total_test_rows == 60

    assert [
        fold.training_rows
        for fold in evaluation.folds
    ] == [
        60,
        80,
        100,
    ]

    assert [
        fold.test_rows
        for fold in evaluation.folds
    ] == [
        20,
        20,
        20,
    ]

    predicted_game_ids = [
        prediction.game_id
        for prediction in evaluation.predictions
    ]

    assert predicted_game_ids == list(
        range(
            61,
            121,
        )
    )

    assert len(predicted_game_ids) == len(
        set(predicted_game_ids)
    )


def test_walk_forward_aggregates_metrics_and_calibration() -> None:
    evaluation = evaluate_moneyline_walk_forward(
        _build_dataset(
            example_count=120,
        ),
        initial_training_rows=60,
        test_block_size=20,
        regularization_candidates=(
            0.01,
            0.10,
            1.00,
        ),
        validation_splits=3,
        calibration_bin_width=0.20,
    )

    assert (
        evaluation.aggregate_model_metrics.log_loss
        < evaluation.aggregate_naive_baseline_metrics.log_loss
    )

    assert (
        evaluation.aggregate_model_metrics.brier_score
        < evaluation.aggregate_naive_baseline_metrics.brier_score
    )

    assert sum(
        calibration_bin.prediction_count
        for calibration_bin
        in evaluation.calibration_bins
    ) == evaluation.total_test_rows

    assert (
        0.0
        <= evaluation.expected_calibration_error
        <= 1.0
    )


def test_walk_forward_handles_partial_final_block() -> None:
    evaluation = evaluate_moneyline_walk_forward(
        _build_dataset(
            example_count=115,
        ),
        initial_training_rows=60,
        test_block_size=20,
        regularization_candidates=(
            0.01,
            0.10,
        ),
        validation_splits=3,
    )

    assert [
        fold.test_rows
        for fold in evaluation.folds
    ] == [
        20,
        20,
        15,
    ]

    assert evaluation.total_test_rows == 55


def test_walk_forward_rejects_training_window_covering_dataset() -> None:
    dataset = _build_dataset(
        example_count=40,
    )

    with pytest.raises(
        ValueError,
        match="must be smaller than the dataset",
    ):
        evaluate_moneyline_walk_forward(
            dataset,
            initial_training_rows=40,
            test_block_size=10,
        )


def _build_dataset(
    *,
    example_count: int,
) -> MoneylineTrainingDataset:
    start_time = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    examples = []

    for index in range(example_count):
        home_team_won = index % 2 == 0

        home_signal = (
            5.0 if home_team_won else 2.0
        )

        away_signal = (
            2.0 if home_team_won else 5.0
        )

        examples.append(
            MoneylineTrainingExample(
                game_id=index + 1,
                game_start_time=(
                    start_time
                    + timedelta(hours=index)
                ),
                home_team_won=home_team_won,
                feature_values=(
                    home_signal,
                    away_signal,
                    float(index % 5),
                    float((index + 1) % 5),
                ),
            )
        )

    return MoneylineTrainingDataset(
        feature_schema_version="1.1.0",
        feature_names=(
            "home_signal",
            "away_signal",
            "home_noise",
            "away_noise",
        ),
        examples=tuple(examples),
    )
