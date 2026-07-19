from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.features import (
    FeatureDataProvider,
    FeatureGenerationContext,
    FeatureValidationError,
)


def build_context() -> FeatureGenerationContext:
    game_start_time = datetime(
        2026,
        7,
        19,
        1,
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


def test_provider_stores_feature_context() -> None:
    context = build_context()

    provider = FeatureDataProvider(context)

    assert provider.context is context


def test_provider_validates_feature_context() -> None:
    context = build_context()

    invalid_context = FeatureGenerationContext(
        game_id=context.game_id,
        game_start_time=context.game_start_time,
        cutoff_time=(
            context.game_start_time + timedelta(minutes=1)
        ),
        home_team_id=context.home_team_id,
        away_team_id=context.away_team_id,
    )

    with pytest.raises(
        FeatureValidationError,
        match="cannot occur after game start",
    ):
        FeatureDataProvider(invalid_context)


def test_get_or_create_loads_value_once() -> None:
    provider = FeatureDataProvider(build_context())
    loader_call_count = 0

    def load_value() -> tuple[int, ...]:
        nonlocal loader_call_count

        loader_call_count += 1

        return (
            1,
            2,
            3,
        )

    first_value = provider.get_or_create(
        namespace="team_games",
        key=(10, 10),
        loader=load_value,
    )

    second_value = provider.get_or_create(
        namespace="team_games",
        key=(10, 10),
        loader=load_value,
    )

    assert first_value == (
        1,
        2,
        3,
    )
    assert second_value is first_value
    assert loader_call_count == 1
    assert provider.cache_size == 1


def test_cache_namespaces_do_not_collide() -> None:
    provider = FeatureDataProvider(build_context())

    first_value = provider.get_or_create(
        namespace="team_games",
        key=10,
        loader=lambda: "games",
    )

    second_value = provider.get_or_create(
        namespace="pitcher_games",
        key=10,
        loader=lambda: "pitching",
    )

    assert first_value == "games"
    assert second_value == "pitching"
    assert provider.cache_size == 2


def test_clear_cache_removes_cached_values() -> None:
    provider = FeatureDataProvider(build_context())

    provider.get_or_create(
        namespace="team_games",
        key=10,
        loader=lambda: (
            1,
            2,
        ),
    )

    assert provider.cache_size == 1

    provider.clear_cache()

    assert provider.cache_size == 0


@pytest.mark.parametrize(
    "namespace",
    [
        "",
        " ",
        " team_games",
        "team_games ",
    ],
)
def test_get_or_create_rejects_invalid_namespace(
    namespace: str,
) -> None:
    provider = FeatureDataProvider(build_context())

    with pytest.raises(ValueError):
        provider.get_or_create(
            namespace=namespace,
            key=10,
            loader=lambda: (),
        )