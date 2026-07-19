from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.database.team_statistics_repository import (
    TeamStatisticsRepository,
)
from sportsmodel.features import (
    FeatureDataProvider,
    FeatureGenerationContext,
    FeatureValidationError,
)
from sportsmodel.models.historical_team_game import (
    HistoricalTeamGame,
)


class FakeTeamStatisticsRepository(
    TeamStatisticsRepository,
):
    def __init__(
        self,
        games: tuple[HistoricalTeamGame, ...] = (),
    ) -> None:
        self.games = games
        self.calls: list[
            tuple[int, datetime, int]
        ] = []

    def get_completed_games_before(
        self,
        *,
        team_id: int,
        cutoff_time: datetime,
        limit: int,
    ) -> tuple[HistoricalTeamGame, ...]:
        self.calls.append(
            (
                team_id,
                cutoff_time,
                limit,
            )
        )

        return self.games


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

    provider = FeatureDataProvider(
        context,
        team_statistics_repository=(
            FakeTeamStatisticsRepository()
        ),
    )

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
        FeatureDataProvider(
            invalid_context,
            team_statistics_repository=(
                FakeTeamStatisticsRepository()
            ),
        )


def test_get_or_create_loads_value_once() -> None:
    provider = FeatureDataProvider(
        build_context(),
        team_statistics_repository=(
            FakeTeamStatisticsRepository()
        ),
    )

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
    provider = FeatureDataProvider(
        build_context(),
        team_statistics_repository=(
            FakeTeamStatisticsRepository()
        ),
    )

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
    provider = FeatureDataProvider(
        build_context(),
        team_statistics_repository=(
            FakeTeamStatisticsRepository()
        ),
    )

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
    provider = FeatureDataProvider(
        build_context(),
        team_statistics_repository=(
            FakeTeamStatisticsRepository()
        ),
    )

    with pytest.raises(ValueError):
        provider.get_or_create(
            namespace=namespace,
            key=10,
            loader=lambda: (),
        )


def test_get_completed_team_games_uses_context_cutoff() -> None:
    context = build_context()
    repository = FakeTeamStatisticsRepository()

    provider = FeatureDataProvider(
        context,
        team_statistics_repository=repository,
    )

    games = provider.get_completed_team_games(
        team_id=context.home_team_id,
        limit=10,
    )

    assert games == ()
    assert repository.calls == [
        (
            context.home_team_id,
            context.cutoff_time,
            10,
        ),
    ]


def test_get_completed_team_games_is_cached() -> None:
    context = build_context()
    repository = FakeTeamStatisticsRepository()

    provider = FeatureDataProvider(
        context,
        team_statistics_repository=repository,
    )

    first_result = provider.get_completed_team_games(
        team_id=context.home_team_id,
        limit=10,
    )

    second_result = provider.get_completed_team_games(
        team_id=context.home_team_id,
        limit=10,
    )

    assert first_result is second_result
    assert len(repository.calls) == 1
    assert provider.cache_size == 1


def test_completed_team_game_cache_separates_limits() -> None:
    context = build_context()
    repository = FakeTeamStatisticsRepository()

    provider = FeatureDataProvider(
        context,
        team_statistics_repository=repository,
    )

    provider.get_completed_team_games(
        team_id=context.home_team_id,
        limit=5,
    )

    provider.get_completed_team_games(
        team_id=context.home_team_id,
        limit=10,
    )

    assert repository.calls == [
        (
            context.home_team_id,
            context.cutoff_time,
            5,
        ),
        (
            context.home_team_id,
            context.cutoff_time,
            10,
        ),
    ]
    assert provider.cache_size == 2


def test_completed_team_game_cache_separates_teams() -> None:
    context = build_context()
    repository = FakeTeamStatisticsRepository()

    provider = FeatureDataProvider(
        context,
        team_statistics_repository=repository,
    )

    provider.get_completed_team_games(
        team_id=context.home_team_id,
        limit=10,
    )

    provider.get_completed_team_games(
        team_id=context.away_team_id,
        limit=10,
    )

    assert repository.calls == [
        (
            context.home_team_id,
            context.cutoff_time,
            10,
        ),
        (
            context.away_team_id,
            context.cutoff_time,
            10,
        ),
    ]
    assert provider.cache_size == 2