from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.features import (
    FeatureGenerationContext,
    FeatureValidationError,
    validate_feature_generation_context,
    validate_source_event_times,
)


def build_valid_context() -> FeatureGenerationContext:
    game_start_time = datetime(
        2026,
        7,
        18,
        19,
        10,
        tzinfo=timezone.utc,
    )

    return FeatureGenerationContext(
        game_id=100,
        game_start_time=game_start_time,
        cutoff_time=game_start_time - timedelta(hours=1),
        home_team_id=10,
        away_team_id=20,
        home_starting_pitcher_id=30,
        away_starting_pitcher_id=40,
    )


def test_valid_feature_generation_context_passes() -> None:
    validate_feature_generation_context(
        build_valid_context()
    )


def test_cutoff_may_equal_game_start_time() -> None:
    context = build_valid_context()

    equal_cutoff_context = FeatureGenerationContext(
        game_id=context.game_id,
        game_start_time=context.game_start_time,
        cutoff_time=context.game_start_time,
        home_team_id=context.home_team_id,
        away_team_id=context.away_team_id,
    )

    validate_feature_generation_context(
        equal_cutoff_context
    )


def test_context_rejects_cutoff_after_game_start() -> None:
    context = build_valid_context()

    invalid_context = FeatureGenerationContext(
        game_id=context.game_id,
        game_start_time=context.game_start_time,
        cutoff_time=(
            context.game_start_time
            + timedelta(minutes=1)
        ),
        home_team_id=context.home_team_id,
        away_team_id=context.away_team_id,
    )

    with pytest.raises(
        FeatureValidationError,
        match="cannot occur after game start",
    ):
        validate_feature_generation_context(
            invalid_context
        )


def test_context_rejects_same_home_and_away_team() -> None:
    context = build_valid_context()

    invalid_context = FeatureGenerationContext(
        game_id=context.game_id,
        game_start_time=context.game_start_time,
        cutoff_time=context.cutoff_time,
        home_team_id=10,
        away_team_id=10,
    )

    with pytest.raises(
        FeatureValidationError,
        match="must be different",
    ):
        validate_feature_generation_context(
            invalid_context
        )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("game_id", 0),
        ("home_team_id", 0),
        ("away_team_id", -1),
        ("home_starting_pitcher_id", 0),
        ("away_starting_pitcher_id", -1),
    ],
)
def test_context_rejects_invalid_identifiers(
    field_name: str,
    field_value: int,
) -> None:
    context_values = {
        "game_id": 100,
        "game_start_time": datetime(
            2026,
            7,
            18,
            19,
            10,
            tzinfo=timezone.utc,
        ),
        "cutoff_time": datetime(
            2026,
            7,
            18,
            18,
            10,
            tzinfo=timezone.utc,
        ),
        "home_team_id": 10,
        "away_team_id": 20,
        "home_starting_pitcher_id": 30,
        "away_starting_pitcher_id": 40,
    }

    context_values[field_name] = field_value

    context = FeatureGenerationContext(
        **context_values,
    )

    with pytest.raises(FeatureValidationError):
        validate_feature_generation_context(context)


def test_context_rejects_naive_game_start_time() -> None:
    context = build_valid_context()

    invalid_context = FeatureGenerationContext(
        game_id=context.game_id,
        game_start_time=datetime(
            2026,
            7,
            18,
            19,
            10,
        ),
        cutoff_time=context.cutoff_time,
        home_team_id=context.home_team_id,
        away_team_id=context.away_team_id,
    )

    with pytest.raises(
        FeatureValidationError,
        match="Game start time must be timezone-aware",
    ):
        validate_feature_generation_context(
            invalid_context
        )


def test_source_event_times_must_precede_cutoff() -> None:
    cutoff_time = datetime(
        2026,
        7,
        18,
        18,
        10,
        tzinfo=timezone.utc,
    )

    source_event_times = (
        cutoff_time - timedelta(days=2),
        cutoff_time - timedelta(days=1),
        cutoff_time - timedelta(seconds=1),
    )

    validate_source_event_times(
        source_event_times=source_event_times,
        cutoff_time=cutoff_time,
    )


@pytest.mark.parametrize(
    "source_time_offset",
    [
        timedelta(0),
        timedelta(seconds=1),
        timedelta(days=1),
    ],
)
def test_source_event_times_reject_cutoff_or_future(
    source_time_offset: timedelta,
) -> None:
    cutoff_time = datetime(
        2026,
        7,
        18,
        18,
        10,
        tzinfo=timezone.utc,
    )

    with pytest.raises(
        FeatureValidationError,
        match="must occur before",
    ):
        validate_source_event_times(
            source_event_times=(
                cutoff_time + source_time_offset,
            ),
            cutoff_time=cutoff_time,
        )
