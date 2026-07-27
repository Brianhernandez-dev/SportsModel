from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.training.matchup_features import (
    MatchupFeatureTransformer,
    transform_to_matchup_difference_dataset,
)
from sportsmodel.training.moneyline_baseline import (
    MoneylineTrainingDataset,
    MoneylineTrainingExample,
)


def test_transformer_pairs_home_and_away_features() -> None:
    transformer = MatchupFeatureTransformer.from_feature_names(
        (
            "home_batting_runs",
            "away_batting_runs",
            "home_pitching_whip",
            "away_pitching_whip",
        )
    )

    assert transformer.output_feature_names == (
        "matchup_batting_runs_difference",
        "matchup_pitching_whip_difference",
    )
    assert transformer.paired_feature_count == 2
    assert transformer.passthrough_feature_count == 0

    assert transformer.transform_values(
        (
            5.0,
            4.0,
            1.20,
            1.35,
        )
    ) == pytest.approx(
        (
            1.0,
            -0.15,
        )
    )


def test_transformer_preserves_unpaired_features() -> None:
    transformer = MatchupFeatureTransformer.from_feature_names(
        (
            "home_batting_runs",
            "away_batting_runs",
            "neutral_weather_feature",
            "home_unpaired_feature",
        )
    )

    assert transformer.output_feature_names == (
        "matchup_batting_runs_difference",
        "neutral_weather_feature",
        "home_unpaired_feature",
    )

    assert transformer.transform_values(
        (
            5.0,
            3.0,
            72.0,
            1.0,
        )
    ) == pytest.approx(
        (
            2.0,
            72.0,
            1.0,
        )
    )


def test_transformer_preserves_missing_matchup_values() -> None:
    transformer = MatchupFeatureTransformer.from_feature_names(
        (
            "home_starter_era",
            "away_starter_era",
        )
    )

    assert transformer.transform_values(
        (
            None,
            3.50,
        )
    ) == (
        None,
    )

    assert transformer.transform_values(
        (
            2.75,
            None,
        )
    ) == (
        None,
    )


def test_dataset_transformation_preserves_order_and_targets() -> None:
    start_time = datetime(
        2026,
        6,
        1,
        tzinfo=timezone.utc,
    )

    dataset = MoneylineTrainingDataset(
        feature_schema_version="1.1.0",
        feature_names=(
            "home_runs",
            "away_runs",
        ),
        examples=(
            MoneylineTrainingExample(
                game_id=1,
                game_start_time=start_time,
                home_team_won=True,
                feature_values=(
                    5.0,
                    3.0,
                ),
            ),
            MoneylineTrainingExample(
                game_id=2,
                game_start_time=(
                    start_time + timedelta(days=1)
                ),
                home_team_won=False,
                feature_values=(
                    2.0,
                    4.0,
                ),
            ),
        ),
    )

    transformed, transformer = (
        transform_to_matchup_difference_dataset(
            dataset
        )
    )

    assert transformed.feature_schema_version == "1.1.0"
    assert transformed.feature_names == (
        "matchup_runs_difference",
    )

    assert transformed.examples[0].game_id == 1
    assert transformed.examples[0].home_team_won is True
    assert transformed.examples[0].feature_values == (
        2.0,
    )

    assert transformed.examples[1].game_id == 2
    assert transformed.examples[1].home_team_won is False
    assert transformed.examples[1].feature_values == (
        -2.0,
    )

    assert transformer.paired_feature_count == 1


def test_transformer_rejects_mismatched_value_count() -> None:
    transformer = MatchupFeatureTransformer.from_feature_names(
        (
            "home_runs",
            "away_runs",
        )
    )

    with pytest.raises(
        ValueError,
        match="value count does not match",
    ):
        transformer.transform_values(
            (
                5.0,
            )
        )


def test_transformer_rejects_duplicate_feature_names() -> None:
    with pytest.raises(
        ValueError,
        match="must be unique",
    ):
        MatchupFeatureTransformer.from_feature_names(
            (
                "home_runs",
                "home_runs",
            )
        )
