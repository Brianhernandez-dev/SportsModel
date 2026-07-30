from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.training.moneyline_baseline import (
    MoneylineTrainingDataset,
    MoneylineTrainingExample,
    fit_moneyline_baseline,
)


def build_dataset(
    targets: tuple[bool, ...] = (
        False,
        False,
        True,
        False,
        True,
        True,
    ),
) -> MoneylineTrainingDataset:
    start_time = datetime(
        2026,
        4,
        1,
        17,
        0,
        tzinfo=timezone.utc,
    )

    examples = tuple(
        MoneylineTrainingExample(
            game_id=index + 1,
            game_start_time=(
                start_time
                + timedelta(days=index)
            ),
            home_team_won=target,
            feature_values=(
                float(index),
                float(index % 3),
                1.0,
            ),
        )
        for index, target in enumerate(targets)
    )

    return MoneylineTrainingDataset(
        feature_schema_version="1.2.0",
        feature_names=(
            "matchup_feature_one",
            "matchup_feature_two",
            "constant_feature",
        ),
        examples=examples,
    )


def test_fit_moneyline_baseline_uses_all_examples() -> None:
    dataset = build_dataset()

    artifact = fit_moneyline_baseline(
        dataset,
        regularization_c=0.001,
    )

    assert artifact.feature_schema_version == "1.2.0"
    assert artifact.regularization_c == 0.001
    assert artifact.training_rows == 6
    assert (
        artifact.training_end_time
        == dataset.examples[-1].game_start_time
    )
    assert artifact.active_feature_names == (
        "matchup_feature_one",
        "matchup_feature_two",
    )
    assert artifact.dropped_constant_features == (
        "constant_feature",
    )

    probability = (
        artifact.predict_home_win_probability(
            {
                "matchup_feature_one": 3.0,
                "matchup_feature_two": 1.0,
            }
        )
    )

    assert 0.0 <= probability <= 1.0


def test_fit_moneyline_baseline_rejects_invalid_c() -> None:
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        fit_moneyline_baseline(
            build_dataset(),
            regularization_c=0.0,
        )


def test_fit_moneyline_baseline_requires_both_classes() -> None:
    with pytest.raises(
        ValueError,
        match="both target classes",
    ):
        fit_moneyline_baseline(
            build_dataset(
                targets=(
                    True,
                    True,
                    True,
                    True,
                )
            )
        )
