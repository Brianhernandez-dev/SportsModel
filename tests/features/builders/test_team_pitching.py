from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.database.team_statistics_repository import (
    TeamStatisticsRepository,
)
from sportsmodel.features.builders.team_pitching import (
    SEASON_GAME_LIMIT,
    TeamPitchingFeatureBuilder,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.provider import (
    FeatureDataProvider,
)
from sportsmodel.models.historical_team_game import (
    HistoricalTeamGame,
)
from sportsmodel.models.team_game_statistics import (
    TeamGameStatistics,
)


class FakeTeamStatisticsRepository(
    TeamStatisticsRepository,
):
    def __init__(
        self,
        games: tuple[HistoricalTeamGame, ...],
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

        return self.games[:limit]


def build_context(
    *,
    game_id: int = 500,
    home_team_id: int = 10,
    away_team_id: int = 20,
) -> FeatureGenerationContext:
    game_start_time = datetime(
        2026,
        7,
        20,
        2,
        10,
        tzinfo=timezone.utc,
    )

    return FeatureGenerationContext(
        game_id=game_id,
        game_start_time=game_start_time,
        cutoff_time=(
            game_start_time
            - timedelta(hours=1)
        ),
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_starting_pitcher_id=30,
        away_starting_pitcher_id=40,
    )


def build_historical_game(
    *,
    game_id: int,
    game_number: int,
    team_id: int = 10,
    opponent_team_id: int = 20,
    pitching_outs: int = 27,
    runs_allowed: int = 3,
    earned_runs_allowed: int = 3,
    hits_allowed: int = 7,
    home_runs_allowed: int = 1,
    walks_allowed: int = 2,
    strikeouts_recorded: int = 9,
) -> HistoricalTeamGame:
    game_start_time = datetime(
        2026,
        7,
        19,
        23,
        10,
        tzinfo=timezone.utc,
    ) - timedelta(days=game_number)

    statistics = TeamGameStatistics(
        game_id=game_id,
        team_id=team_id,
        is_home=True,
        runs=4,
        hits=8,
        errors=0,
        at_bats=32,
        plate_appearances=37,
        doubles=2,
        triples=0,
        home_runs=1,
        walks=3,
        intentional_walks=0,
        strikeouts=8,
        hit_by_pitch=1,
        sacrifice_flies=1,
        stolen_bases=0,
        caught_stealing=0,
        pitching_outs=pitching_outs,
        runs_allowed=runs_allowed,
        earned_runs_allowed=earned_runs_allowed,
        hits_allowed=hits_allowed,
        home_runs_allowed=home_runs_allowed,
        walks_allowed=walks_allowed,
        strikeouts_recorded=strikeouts_recorded,
        left_on_base=6,
        double_plays=1,
        source_name="mlb_stats_api",
    )

    return HistoricalTeamGame(
        game_id=game_id,
        game_start_time=game_start_time,
        team_id=team_id,
        opponent_team_id=opponent_team_id,
        is_home=True,
        statistics=statistics,
    )


def build_provider(
    *,
    context: FeatureGenerationContext,
    games: tuple[HistoricalTeamGame, ...],
) -> tuple[
    FeatureDataProvider,
    FakeTeamStatisticsRepository,
]:
    repository = FakeTeamStatisticsRepository(
        games=games,
    )

    provider = FeatureDataProvider(
        context,
        team_statistics_repository=repository,
    )

    return provider, repository


def test_builder_rejects_invalid_team_id() -> None:
    with pytest.raises(
        ValueError,
        match="must be greater than zero",
    ):
        TeamPitchingFeatureBuilder(
            team_id=0,
        )


def test_builder_rejects_team_not_in_context() -> None:
    context = build_context()

    provider, _ = build_provider(
        context=context,
        games=(),
    )

    builder = TeamPitchingFeatureBuilder(
        team_id=999,
    )

    with pytest.raises(
        ValueError,
        match="must match the home or away team",
    ):
        builder.build(
            context,
            provider,
        )


def test_builder_rejects_mismatched_provider_context() -> None:
    context = build_context()

    different_context = build_context(
        game_id=501,
    )

    provider, _ = build_provider(
        context=different_context,
        games=(),
    )

    builder = TeamPitchingFeatureBuilder(
        team_id=context.home_team_id,
    )

    with pytest.raises(
        ValueError,
        match="provider context must match",
    ):
        builder.build(
            context,
            provider,
        )


def test_builder_returns_empty_features_without_history() -> None:
    context = build_context()

    provider, repository = build_provider(
        context=context,
        games=(),
    )

    builder = TeamPitchingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    assert features.games_played == 0
    assert features.runs_allowed_per_game_season is None
    assert features.runs_allowed_per_game_last_5 is None
    assert features.runs_allowed_per_game_last_10 is None
    assert (
        features.earned_runs_allowed_per_game_last_10
        is None
    )
    assert features.hits_allowed_per_game_last_10 is None
    assert features.walks_allowed_per_game_last_10 is None
    assert features.strikeouts_per_game_last_10 is None
    assert (
        features.home_runs_allowed_per_game_last_10
        is None
    )
    assert features.whip_last_10 is None
    assert features.games_in_last_5_window == 0
    assert features.games_in_last_10_window == 0

    assert repository.calls == [
        (
            context.home_team_id,
            context.cutoff_time,
            SEASON_GAME_LIMIT,
        ),
    ]


def test_builder_calculates_partial_window_features() -> None:
    context = build_context()

    games = (
        build_historical_game(
            game_id=101,
            game_number=1,
            runs_allowed=2,
            earned_runs_allowed=2,
            hits_allowed=6,
            walks_allowed=1,
            strikeouts_recorded=10,
            home_runs_allowed=0,
        ),
        build_historical_game(
            game_id=102,
            game_number=2,
            runs_allowed=4,
            earned_runs_allowed=3,
            hits_allowed=8,
            walks_allowed=3,
            strikeouts_recorded=8,
            home_runs_allowed=1,
        ),
        build_historical_game(
            game_id=103,
            game_number=3,
            runs_allowed=6,
            earned_runs_allowed=5,
            hits_allowed=10,
            walks_allowed=2,
            strikeouts_recorded=6,
            home_runs_allowed=2,
        ),
    )

    provider, _ = build_provider(
        context=context,
        games=games,
    )

    builder = TeamPitchingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    assert features.games_played == 3
    assert features.games_in_last_5_window == 3
    assert features.games_in_last_10_window == 3

    assert (
        features.runs_allowed_per_game_season
        == pytest.approx(4.0)
    )

    assert (
        features.runs_allowed_per_game_last_5
        == pytest.approx(4.0)
    )

    assert (
        features.runs_allowed_per_game_last_10
        == pytest.approx(4.0)
    )

    assert (
        features.earned_runs_allowed_per_game_last_10
        == pytest.approx(10 / 3)
    )

    assert (
        features.hits_allowed_per_game_last_10
        == pytest.approx(8.0)
    )

    assert (
        features.walks_allowed_per_game_last_10
        == pytest.approx(2.0)
    )

    assert (
        features.strikeouts_per_game_last_10
        == pytest.approx(8.0)
    )

    assert (
        features.home_runs_allowed_per_game_last_10
        == pytest.approx(1.0)
    )


def test_builder_uses_newest_five_and_ten_games() -> None:
    context = build_context()

    games = tuple(
        build_historical_game(
            game_id=200 + index,
            game_number=index,
            runs_allowed=index,
            earned_runs_allowed=index,
            )
        for index in range(1, 13)
    )

    provider, _ = build_provider(
        context=context,
        games=games,
    )

    builder = TeamPitchingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    assert features.games_played == 12

    assert (
        features.runs_allowed_per_game_season
        == pytest.approx(6.5)
    )

    assert (
        features.runs_allowed_per_game_last_5
        == pytest.approx(3.0)
    )

    assert (
        features.runs_allowed_per_game_last_10
        == pytest.approx(5.5)
    )

    assert features.games_in_last_5_window == 5
    assert features.games_in_last_10_window == 10


def test_builder_calculates_aggregate_whip() -> None:
    context = build_context()

    games = (
        build_historical_game(
            game_id=301,
            game_number=1,
            pitching_outs=27,
            hits_allowed=6,
            walks_allowed=2,
        ),
        build_historical_game(
            game_id=302,
            game_number=2,
            pitching_outs=18,
            hits_allowed=4,
            walks_allowed=3,
        ),
    )

    provider, _ = build_provider(
        context=context,
        games=games,
    )

    builder = TeamPitchingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    expected_whip = (
        6 + 2 + 4 + 3
    ) / (
        (27 + 18) / 3
    )

    assert features.whip_last_10 == pytest.approx(
        expected_whip
    )


def test_builder_returns_none_for_zero_pitching_outs() -> None:
    context = build_context()

    games = (
        build_historical_game(
            game_id=401,
            game_number=1,
            pitching_outs=0,
            hits_allowed=0,
            walks_allowed=0,
        ),
    )

    provider, _ = build_provider(
        context=context,
        games=games,
    )

    builder = TeamPitchingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    assert features.whip_last_10 is None


def test_builder_reuses_provider_cache() -> None:
    context = build_context()

    games = (
        build_historical_game(
            game_id=501,
            game_number=1,
        ),
    )

    provider, repository = build_provider(
        context=context,
        games=games,
    )

    first_builder = TeamPitchingFeatureBuilder(
        team_id=context.home_team_id,
    )

    second_builder = TeamPitchingFeatureBuilder(
        team_id=context.home_team_id,
    )

    first_features = first_builder.build(
        context,
        provider,
    )

    second_features = second_builder.build(
        context,
        provider,
    )

    assert first_features == second_features
    assert len(repository.calls) == 1
    assert provider.cache_size == 1