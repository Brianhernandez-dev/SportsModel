from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.generation_service import (
    FeatureGenerationService,
)
from sportsmodel.models.baseball_game import (
    BaseballGame,
)
from sportsmodel.models.game_feature_vector import (
    GameFeatureVector,
)


def _build_game() -> BaseballGame:
    return BaseballGame(
        game_id=42,
        game_start_time=datetime(
            2026,
            7,
            20,
            2,
            10,
            tzinfo=timezone.utc,
        ),
        home_team_id=10,
        away_team_id=20,
    )


def test_generate_builds_provider_and_returns_vector() -> None:
    context = FeatureGenerationContext(
        game_id=42,
        game_start_time=datetime(
            2026,
            7,
            20,
            2,
            10,
            tzinfo=timezone.utc,
        ),
        cutoff_time=datetime(
            2026,
            7,
            20,
            1,
            10,
            tzinfo=timezone.utc,
        ),
        home_team_id=10,
        away_team_id=20,
    )

    expected_vector = Mock(spec=GameFeatureVector)
    builder = Mock()
    builder.build.return_value = expected_vector

    bullpen_repository = Mock()
    bullpen_repository.get_completed_relief_appearances_before.return_value = ()

    service = FeatureGenerationService(
        game_repository=Mock(),
        team_statistics_repository=Mock(),
        bullpen_statistics_repository=bullpen_repository,
        game_feature_vector_builder=builder,
    )

    result = service.generate(context)

    assert result is expected_vector

    builder.build.assert_called_once()

    actual_context, provider = builder.build.call_args.args

    assert actual_context == context
    assert provider.context == context

    appearances = provider.get_completed_relief_appearances(
        team_id=context.home_team_id,
    )

    assert appearances == ()

    bullpen_repository.get_completed_relief_appearances_before.assert_called_once_with(
        team_id=context.home_team_id,
        cutoff_time=context.cutoff_time,
    )


def test_generate_for_game_loads_game_and_builds_context() -> None:
    game = _build_game()
    cutoff_time = datetime(
        2026,
        7,
        20,
        1,
        10,
        tzinfo=timezone.utc,
    )

    game_repository = Mock()
    game_repository.get_by_id.return_value = game

    expected_vector = Mock(spec=GameFeatureVector)
    builder = Mock()
    builder.build.return_value = expected_vector

    service = FeatureGenerationService(
        game_repository=game_repository,
        team_statistics_repository=Mock(),
        game_feature_vector_builder=builder,
    )

    result = service.generate_for_game(
        game_id=42,
        cutoff_time=cutoff_time,
        home_starting_pitcher_id=100,
        away_starting_pitcher_id=200,
    )

    assert result is expected_vector

    game_repository.get_by_id.assert_called_once_with(
        game_id=42,
    )

    context, provider = builder.build.call_args.args

    assert context == FeatureGenerationContext(
        game_id=42,
        game_start_time=game.game_start_time,
        cutoff_time=cutoff_time,
        home_team_id=10,
        away_team_id=20,
        home_starting_pitcher_id=100,
        away_starting_pitcher_id=200,
    )
    assert provider.context == context


def test_generate_for_game_record_does_not_query_repository() -> None:
    game_repository = Mock()
    builder = Mock()
    builder.build.return_value = Mock(
        spec=GameFeatureVector,
    )

    service = FeatureGenerationService(
        game_repository=game_repository,
        team_statistics_repository=Mock(),
        game_feature_vector_builder=builder,
    )

    service.generate_for_game_record(
        game=_build_game(),
        cutoff_time=datetime(
            2026,
            7,
            20,
            1,
            10,
            tzinfo=timezone.utc,
        ),
    )

    game_repository.get_by_id.assert_not_called()


def test_generate_for_game_rejects_nonpositive_id() -> None:
    service = FeatureGenerationService(
        game_repository=Mock(),
        team_statistics_repository=Mock(),
        game_feature_vector_builder=Mock(),
    )

    with pytest.raises(
        ValueError,
        match="Game ID must be greater than zero",
    ):
        service.generate_for_game(
            game_id=0,
            cutoff_time=datetime.now(timezone.utc),
        )


def test_generate_for_game_rejects_missing_game() -> None:
    game_repository = Mock()
    game_repository.get_by_id.return_value = None

    service = FeatureGenerationService(
        game_repository=game_repository,
        team_statistics_repository=Mock(),
        game_feature_vector_builder=Mock(),
    )

    with pytest.raises(
        LookupError,
        match="Game 999 was not found",
    ):
        service.generate_for_game(
            game_id=999,
            cutoff_time=datetime.now(timezone.utc),
        )
