import csv
from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.training.moneyline_baseline import (
    MoneylineTrainingDataset,
    MoneylineTrainingExample,
    chronological_train_test_split,
    load_moneyline_training_csv,
    train_moneyline_baseline,
)


def test_loader_parses_numeric_boolean_and_missing_features(
    tmp_path,
) -> None:
    path = tmp_path / "moneyline.csv"

    field_names = [
        "game_id",
        "game_start_time",
        "feature_time",
        "feature_schema_version",
        "home_team_id",
        "away_team_id",
        "numeric_feature",
        "boolean_feature",
        "missing_feature",
        "home_score",
        "away_score",
        "home_team_won",
    ]

    with path.open(
        mode="w",
        newline="",
        encoding="utf-8",
    ) as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=field_names,
        )
        writer.writeheader()
        writer.writerow(
            {
                "game_id": 100,
                "game_start_time": (
                    "2026-07-20 20:10:00+00:00"
                ),
                "feature_time": (
                    "2026-07-20 20:10:00+00:00"
                ),
                "feature_schema_version": "1.1.0",
                "home_team_id": 10,
                "away_team_id": 20,
                "numeric_feature": "4.25",
                "boolean_feature": "True",
                "missing_feature": "",
                "home_score": 5,
                "away_score": 3,
                "home_team_won": "True",
            }
        )

    dataset = load_moneyline_training_csv(path)

    assert dataset.feature_schema_version == "1.1.0"
    assert dataset.feature_names == (
        "numeric_feature",
        "boolean_feature",
        "missing_feature",
    )
    assert len(dataset.examples) == 1
    assert dataset.examples[0].feature_values == (
        4.25,
        1.0,
        None,
    )
    assert dataset.examples[0].home_team_won is True


def test_chronological_split_uses_latest_games_for_test() -> None:
    dataset = _build_dataset(
        example_count=20,
    )

    split = chronological_train_test_split(
        dataset,
        test_fraction=0.25,
    )

    assert len(split.training_examples) == 15
    assert len(split.test_examples) == 5

    assert (
        split.training_examples[-1].game_start_time
        < split.test_examples[0].game_start_time
    )


def test_training_drops_unusable_features_and_beats_naive_baseline() -> None:
    dataset = _build_dataset(
        example_count=40,
    )

    evaluation = train_moneyline_baseline(
        dataset,
        test_fraction=0.25,
        top_feature_count=5,
    )

    assert evaluation.training_rows == 30
    assert evaluation.test_rows == 10

    assert (
        evaluation.artifact.dropped_all_missing_features
        == ("all_missing",)
    )
    assert (
        evaluation.artifact.dropped_constant_features
        == ("constant",)
    )

    assert "signal" in (
        evaluation.artifact.active_feature_names
    )
    assert "partially_missing" in (
        evaluation.artifact.active_feature_names
    )

    assert (
        evaluation.model_metrics.log_loss
        < evaluation.naive_baseline_metrics.log_loss
    )
    assert (
        evaluation.model_metrics.brier_score
        < evaluation.naive_baseline_metrics.brier_score
    )

    positive_names = {
        coefficient.feature_name
        for coefficient
        in evaluation.top_positive_coefficients
    }

    assert "signal" in positive_names


def test_artifact_requires_all_active_prediction_features() -> None:
    evaluation = train_moneyline_baseline(
        _build_dataset(
            example_count=40,
        ),
        test_fraction=0.25,
    )

    with pytest.raises(
        ValueError,
        match="missing required features",
    ):
        evaluation.artifact.predict_home_win_probability(
            {}
        )


def _build_dataset(
    *,
    example_count: int,
) -> MoneylineTrainingDataset:
    start_time = datetime(
        2026,
        6,
        1,
        tzinfo=timezone.utc,
    )

    examples = []

    for index in range(example_count):
        home_team_won = index % 2 == 0

        examples.append(
            MoneylineTrainingExample(
                game_id=index + 1,
                game_start_time=(
                    start_time
                    + timedelta(days=index)
                ),
                home_team_won=home_team_won,
                feature_values=(
                    1.0 if home_team_won else -1.0,
                    None,
                    7.0,
                    (
                        None
                        if index % 3 == 0
                        else (
                            1.0
                            if home_team_won
                            else 0.0
                        )
                    ),
                ),
            )
        )

    return MoneylineTrainingDataset(
        feature_schema_version="1.1.0",
        feature_names=(
            "signal",
            "all_missing",
            "constant",
            "partially_missing",
        ),
        examples=tuple(examples),
    )
