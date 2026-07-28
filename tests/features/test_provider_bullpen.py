from datetime import datetime, timedelta, timezone

from sportsmodel.database.bullpen_statistics_repository import (
    BullpenStatisticsRepository,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.provider import (
    FeatureDataProvider,
)
from sportsmodel.models.historical_bullpen_appearance import (
    HistoricalBullpenAppearance,
)


class FakeBullpenStatisticsRepository(
    BullpenStatisticsRepository,
):
    def __init__(
        self,
        appearances: tuple[
            HistoricalBullpenAppearance,
            ...,
        ] = (),
    ) -> None:
        self.appearances = appearances
        self.calls: list[
            tuple[int, datetime]
        ] = []

    def get_completed_relief_appearances_before(
        self,
        *,
        team_id: int,
        cutoff_time: datetime,
    ) -> tuple[HistoricalBullpenAppearance, ...]:
        self.calls.append(
            (
                team_id,
                cutoff_time,
            )
        )

        return self.appearances


def build_context() -> FeatureGenerationContext:
    game_start_time = datetime(
        2026,
        7,
        27,
        2,
        10,
        tzinfo=timezone.utc,
    )

    return FeatureGenerationContext(
        game_id=500,
        game_start_time=game_start_time,
        cutoff_time=(
            game_start_time
            - timedelta(hours=1)
        ),
        home_team_id=10,
        away_team_id=20,
        home_starting_pitcher_id=30,
        away_starting_pitcher_id=40,
    )


def test_provider_uses_context_cutoff_for_bullpen_data() -> None:
    context = build_context()
    repository = FakeBullpenStatisticsRepository()

    provider = FeatureDataProvider(
        context,
        bullpen_statistics_repository=repository,
    )

    appearances = provider.get_completed_relief_appearances(
        team_id=context.home_team_id,
    )

    assert appearances == ()

    assert repository.calls == [
        (
            context.home_team_id,
            context.cutoff_time,
        ),
    ]


def test_provider_caches_bullpen_appearances() -> None:
    context = build_context()
    repository = FakeBullpenStatisticsRepository()

    provider = FeatureDataProvider(
        context,
        bullpen_statistics_repository=repository,
    )

    first_result = provider.get_completed_relief_appearances(
        team_id=context.home_team_id,
    )

    second_result = provider.get_completed_relief_appearances(
        team_id=context.home_team_id,
    )

    assert first_result is second_result
    assert len(repository.calls) == 1
    assert provider.cache_size == 1


def test_bullpen_cache_separates_teams() -> None:
    context = build_context()
    repository = FakeBullpenStatisticsRepository()

    provider = FeatureDataProvider(
        context,
        bullpen_statistics_repository=repository,
    )

    provider.get_completed_relief_appearances(
        team_id=context.home_team_id,
    )

    provider.get_completed_relief_appearances(
        team_id=context.away_team_id,
    )

    assert repository.calls == [
        (
            context.home_team_id,
            context.cutoff_time,
        ),
        (
            context.away_team_id,
            context.cutoff_time,
        ),
    ]

    assert provider.cache_size == 2
