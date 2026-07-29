from datetime import datetime, timedelta, timezone

from sportsmodel.training.moneyline_baseline import (
    MoneylineTrainingDataset,
    MoneylineTrainingExample,
)
from sportsmodel.training.moneyline_walk_forward_experiment import (
    compare_raw_and_matchup_walk_forward,
)


def test_comparison_predicts_identical_games() -> None:
    comparison = compare_raw_and_matchup_walk_forward(
        _build_dataset(),
        initial_training_rows=60,
        test_block_size=20,
        regularization_candidates=(
            0.001,
            0.01,
        ),
        validation_splits=3,
    )

    raw_game_ids = tuple(
        prediction.game_id
        for prediction
        in comparison.raw.evaluation.predictions
    )

    matchup_game_ids = tuple(
        prediction.game_id
        for prediction
        in comparison.matchup.evaluation.predictions
    )

    assert raw_game_ids == matchup_game_ids
    assert len(raw_game_ids) == 60


def test_comparison_reduces_matchup_feature_count() -> None:
    comparison = compare_raw_and_matchup_walk_forward(
        _build_dataset(),
        initial_training_rows=60,
        test_block_size=20,
        regularization_candidates=(
            0.001,
            0.01,
        ),
        validation_splits=3,
    )

    assert (
        comparison.matchup.input_feature_count
        < comparison.raw.input_feature_count
    )

    assert (
        comparison.matchup_transformer
        .paired_feature_count
        == 2
    )


def _build_dataset() -> MoneylineTrainingDataset:
    start_time = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    examples = []

    for index in range(120):
        home_team_won = index % 2 == 0

        examples.append(
            MoneylineTrainingExample(
                game_id=index + 1,
                game_start_time=(
                    start_time
                    + timedelta(hours=index)
                ),
                home_team_won=home_team_won,
                feature_values=(
                    5.0 if home_team_won else 2.0,
                    2.0 if home_team_won else 5.0,
                    float(index % 5),
                    float((index + 2) % 5),
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
