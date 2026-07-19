from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from sportsmodel.features import FeatureGenerationContext


def test_feature_generation_context_stores_game_information() -> None:
    game_start_time = datetime(
        2026,
        7,
        18,
        19,
        10,
        tzinfo=timezone.utc,
    )

    cutoff_time = datetime(
        2026,
        7,
        18,
        18,
        10,
        tzinfo=timezone.utc,
    )

    context = FeatureGenerationContext(
        game_id=100,
        game_start_time=game_start_time,
        cutoff_time=cutoff_time,
        home_team_id=10,
        away_team_id=20,
        home_starting_pitcher_id=30,
        away_starting_pitcher_id=40,
    )

    assert context.game_id == 100
    assert context.game_start_time == game_start_time
    assert context.cutoff_time == cutoff_time
    assert context.home_team_id == 10
    assert context.away_team_id == 20
    assert context.home_starting_pitcher_id == 30
    assert context.away_starting_pitcher_id == 40


def test_feature_generation_context_allows_unknown_starters() -> None:
    game_start_time = datetime(
        2026,
        7,
        18,
        19,
        10,
        tzinfo=timezone.utc,
    )

    context = FeatureGenerationContext(
        game_id=100,
        game_start_time=game_start_time,
        cutoff_time=game_start_time,
        home_team_id=10,
        away_team_id=20,
    )

    assert context.home_starting_pitcher_id is None
    assert context.away_starting_pitcher_id is None


def test_feature_generation_context_is_immutable() -> None:
    game_start_time = datetime(
        2026,
        7,
        18,
        19,
        10,
        tzinfo=timezone.utc,
    )

    context = FeatureGenerationContext(
        game_id=100,
        game_start_time=game_start_time,
        cutoff_time=game_start_time,
        home_team_id=10,
        away_team_id=20,
    )

    with pytest.raises(FrozenInstanceError):
        context.game_id = 200
