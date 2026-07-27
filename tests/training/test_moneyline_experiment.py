from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.training import (
    MoneylineTrainingDataset,
    MoneylineTrainingExample,
    compare_raw_and_matchup_moneyline_models,
    load_trained_matchup_moneyline_model,
    save_trained_matchup_moneyline_model,
)


def test_comparison_uses_identical_outer_test_window() -> None:
    comparison = compare_raw_and_matchup_moneyline_models(
        _build_dataset(),
        test_fraction=0.20,
        regularization_candidates=(
            0.01,
            0.10,
            1.00,
        ),
        validation_splits=3,
    )

    raw = comparison.raw.evaluation
    matchup = comparison.matchup.evaluation

    assert raw.training_rows == matchup.training_rows
    assert raw.test_rows == matchup.test_rows
    assert raw.training_start_time == (
        matchup.training_start_time
    )
    assert raw.training_end_time == (
        matchup.training_end_time
    )
    assert raw.test_start_time == (
        matchup.test_start_time
    )
    assert raw.test_end_time == (
        matchup.test_end_time
    )

    assert (
        comparison.matchup.input_feature_count
        < comparison.raw.input_feature_count
    )


def test_matchup_model_round_trip_accepts_raw_features(
    tmp_path,
) -> None:
    dataset = _build_dataset()

    comparison = compare_raw_and_matchup_moneyline_models(
        dataset,
        test_fraction=0.20,
        regularization_candidates=(
            0.01,
            0.10,
        ),
        validation_splits=3,
    )

    path = tmp_path / "matchup.joblib"

    raw_mapping = dict(
        zip(
            dataset.feature_names,
            dataset.examples[-1].feature_values,
            strict=True,
        )
    )

    expected_probability = (
        comparison.matchup_model
        .predict_home_win_probability(
            raw_mapping
        )
    )

    save_trained_matchup_moneyline_model(
        comparison.matchup_model,
        path,
    )

    loaded_model = (
        load_trained_matchup_moneyline_model(
            path
        )
    )

    actual_probability = (
        loaded_model.predict_home_win_probability(
            raw_mapping
        )
    )

    assert actual_probability == pytest.approx(
        expected_probability
    )


def _build_dataset() -> MoneylineTrainingDataset:
    start_time = datetime(
        2026,
        6,
        1,
        tzinfo=timezone.utc,
    )

    examples = []

    for index in range(80):
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
                    float(index % 7),
                    float((index + 2) % 7),
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
