from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from sportsmodel.features.datasets.moneyline_dataset import (
    MoneylineTrainingDatasetBuilder,
)
from sportsmodel.features.generation_service import (
    FeatureGenerationService,
)
from sportsmodel.models.baseball_game import BaseballGame
from sportsmodel.models.completed_game import CompletedGame
from sportsmodel.models.game_feature_vector import (
    GameFeatureVector,
)


def test_builder_generates_labeled_moneyline_rows() -> None:
    first_game = _build_completed_game(
        game_id=101,
        home_score=5,
        away_score=3,
    )
    second_game = _build_completed_game(
        game_id=102,
        home_score=2,
        away_score=6,
    )

    first_vector = _build_vector(first_game)
    second_vector = _build_vector(second_game)

    service = Mock(spec=FeatureGenerationService)
    service.generate_for_game_record.side_effect = [
        first_vector,
        second_vector,
    ]

    flattened_rows = iter(
        [
            {
                "home_batting_runs_per_game_season": 4.8,
                "away_pitching_whip_last_10": 1.31,
            },
            {
                "home_batting_runs_per_game_season": 4.2,
                "away_pitching_whip_last_10": 1.19,
            },
        ]
    )

    builder = MoneylineTrainingDatasetBuilder(
        feature_generation_service=service,
        feature_flattener=lambda vector: next(
            flattened_rows
        ),
    )

    result = builder.build(
        [first_game, second_game]
    )

    assert result.completed_games_received == 2
    assert result.rows_generated == 2
    assert result.tied_games_skipped == 0
    assert result.feature_count == 2

    first_row = result.rows[0]
    second_row = result.rows[1]

    assert first_row["game_id"] == 101
    assert first_row["home_team_won"] is True
    assert first_row["home_score"] == 5
    assert (
        first_row[
            "home_batting_runs_per_game_season"
        ]
        == 4.8
    )

    assert second_row["game_id"] == 102
    assert second_row["home_team_won"] is False

    assert service.generate_for_game_record.call_count == 2

    first_call = (
        service.generate_for_game_record.call_args_list[0]
    )
    assert first_call.kwargs["game"] == first_game.game
    assert (
        first_call.kwargs["cutoff_time"]
        == first_game.game.game_start_time
    )


def test_builder_skips_tied_games() -> None:
    tied_game = _build_completed_game(
        game_id=101,
        home_score=4,
        away_score=4,
    )

    service = Mock(spec=FeatureGenerationService)

    builder = MoneylineTrainingDatasetBuilder(
        feature_generation_service=service,
    )

    result = builder.build([tied_game])

    assert result.completed_games_received == 1
    assert result.rows_generated == 0
    assert result.tied_games_skipped == 1

    service.generate_for_game_record.assert_not_called()


def test_builder_rejects_inconsistent_feature_columns() -> None:
    first_game = _build_completed_game(
        game_id=101,
        home_score=5,
        away_score=3,
    )
    second_game = _build_completed_game(
        game_id=102,
        home_score=2,
        away_score=6,
    )

    service = Mock(spec=FeatureGenerationService)
    service.generate_for_game_record.side_effect = [
        _build_vector(first_game),
        _build_vector(second_game),
    ]

    flattened_rows = iter(
        [
            {"feature_one": 1.0},
            {"different_feature": 2.0},
        ]
    )

    builder = MoneylineTrainingDatasetBuilder(
        feature_generation_service=service,
        feature_flattener=lambda vector: next(
            flattened_rows
        ),
    )

    with pytest.raises(
        ValueError,
        match="feature columns changed",
    ):
        builder.build([first_game, second_game])


def _build_completed_game(
    *,
    game_id: int,
    home_score: int,
    away_score: int,
) -> CompletedGame:
    return CompletedGame(
        game=BaseballGame(
            game_id=game_id,
            game_start_time=datetime(
                2026,
                7,
                20,
                19,
                10,
                tzinfo=timezone.utc,
            ),
            home_team_id=10 + game_id,
            away_team_id=20 + game_id,
        ),
        home_score=home_score,
        away_score=away_score,
    )


def _build_vector(
    completed_game: CompletedGame,
) -> GameFeatureVector:
    vector = Mock(spec=GameFeatureVector)
    vector.feature_time = (
        completed_game.game.game_start_time
    )
    vector.feature_schema_version = "1.0"

    return vector
