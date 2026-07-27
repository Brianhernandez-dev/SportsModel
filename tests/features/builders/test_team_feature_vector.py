from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.database.team_statistics_repository import (
    TeamStatisticsRepository,
)
from sportsmodel.features.builders.team_feature_vector import (
    TeamFeatureVectorBuilder,
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
        games_by_team: dict[
            int,
            tuple[HistoricalTeamGame, ...],
        ],
    ) -> None:
        self.games_by_team = games_by_team
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

        return self.games_by_team.get(
            team_id,
            (),
        )[:limit]


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
    team_id: int,
    opponent_team_id: int,
    runs: int = 4,
    hits: int = 8,
    home_runs: int = 1,
    walks: int = 3,
    strikeouts: int = 8,
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
        runs=runs,
        hits=hits,
        errors=0,
        at_bats=32,
        plate_appearances=37,
        doubles=2,
        triples=0,
        home_runs=home_runs,
        walks=walks,
        intentional_walks=0,
        strikeouts=strikeouts,
        hit_by_pitch=1,
        sacrifice_flies=1,
        stolen_bases=0,
        caught_stealing=0,
        pitching_outs=27,
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
    games_by_team: dict[
        int,
        tuple[HistoricalTeamGame, ...],
    ],
) -> tuple[
    FeatureDataProvider,
    FakeTeamStatisticsRepository,
]:
    repository = FakeTeamStatisticsRepository(
        games_by_team=games_by_team,
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
        TeamFeatureVectorBuilder(
            team_id=0,
        )


def test_builder_rejects_team_not_in_context() -> None:
    context = build_context()

    provider, _ = build_provider(
        context=context,
        games_by_team={},
    )

    builder = TeamFeatureVectorBuilder(
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
        games_by_team={},
    )

    builder = TeamFeatureVectorBuilder(
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


def test_builder_returns_empty_vector_without_history() -> None:
    context = build_context()

    provider, repository = build_provider(
        context=context,
        games_by_team={},
    )

    builder = TeamFeatureVectorBuilder(
        team_id=context.home_team_id,
    )

    vector = builder.build(
        context,
        provider,
    )

    assert vector.team_id == context.home_team_id

    assert vector.batting.games_played == 0
    assert vector.batting.runs_per_game_season is None

    assert vector.pitching.games_played == 0
    assert (
        vector.pitching.runs_allowed_per_game_season
        is None
    )

    assert vector.bullpen.relief_appearances_season == 0
    assert (
        vector.bullpen.bullpen_earned_run_average_season
        is None
    )
    assert vector.bullpen.games_in_last_10_window == 0

    assert vector.schedule.days_since_previous_game is None
    assert vector.schedule.played_previous_day is False
    assert vector.schedule.games_in_previous_3_days == 0
    assert vector.schedule.games_in_previous_7_days == 0
    assert vector.schedule.doubleheader_game is False

    assert len(repository.calls) == 1


def test_builder_combines_batting_and_pitching_features() -> None:
    context = build_context()

    games = (
        build_historical_game(
            game_id=101,
            game_number=1,
            team_id=context.home_team_id,
            opponent_team_id=context.away_team_id,
            runs=6,
            hits=10,
            home_runs=2,
            walks=4,
            strikeouts=7,
            runs_allowed=2,
            earned_runs_allowed=2,
            hits_allowed=6,
            walks_allowed=1,
            strikeouts_recorded=10,
        ),
        build_historical_game(
            game_id=102,
            game_number=2,
            team_id=context.home_team_id,
            opponent_team_id=context.away_team_id,
            runs=4,
            hits=8,
            home_runs=1,
            walks=2,
            strikeouts=9,
            runs_allowed=4,
            earned_runs_allowed=3,
            hits_allowed=8,
            walks_allowed=3,
            strikeouts_recorded=8,
        ),
    )

    provider, repository = build_provider(
        context=context,
        games_by_team={
            context.home_team_id: games,
        },
    )

    builder = TeamFeatureVectorBuilder(
        team_id=context.home_team_id,
    )

    vector = builder.build(
        context,
        provider,
    )

    assert vector.team_id == context.home_team_id

    assert vector.batting.games_played == 2
    assert (
        vector.batting.runs_per_game_season
        == pytest.approx(5.0)
    )
    assert (
        vector.batting.hits_per_game_last_10
        == pytest.approx(9.0)
    )

    assert vector.pitching.games_played == 2
    assert (
        vector.pitching.runs_allowed_per_game_season
        == pytest.approx(3.0)
    )
    assert (
        vector.pitching.strikeouts_per_game_last_10
        == pytest.approx(9.0)
    )

    assert len(repository.calls) == 1
    assert provider.cache_size == 1


def test_builder_builds_vector_for_away_team() -> None:
    context = build_context()

    away_game = build_historical_game(
        game_id=201,
        game_number=1,
        team_id=context.away_team_id,
        opponent_team_id=context.home_team_id,
        runs=5,
        runs_allowed=2,
        earned_runs_allowed=2,
    )

    provider, repository = build_provider(
        context=context,
        games_by_team={
            context.away_team_id: (
                away_game,
            ),
        },
    )

    builder = TeamFeatureVectorBuilder(
        team_id=context.away_team_id,
    )

    vector = builder.build(
        context,
        provider,
    )

    assert vector.team_id == context.away_team_id
    assert vector.batting.games_played == 1
    assert vector.pitching.games_played == 1

    assert repository.calls[0][0] == context.away_team_id


def test_home_and_away_vectors_use_separate_cache_entries() -> None:
    context = build_context()

    home_game = build_historical_game(
        game_id=301,
        game_number=1,
        team_id=context.home_team_id,
        opponent_team_id=context.away_team_id,
    )

    away_game = build_historical_game(
        game_id=302,
        game_number=1,
        team_id=context.away_team_id,
        opponent_team_id=context.home_team_id,
    )

    provider, repository = build_provider(
        context=context,
        games_by_team={
            context.home_team_id: (
                home_game,
            ),
            context.away_team_id: (
                away_game,
            ),
        },
    )

    home_vector = TeamFeatureVectorBuilder(
        team_id=context.home_team_id,
    ).build(
        context,
        provider,
    )

    away_vector = TeamFeatureVectorBuilder(
        team_id=context.away_team_id,
    ).build(
        context,
        provider,
    )

    assert home_vector.team_id == context.home_team_id
    assert away_vector.team_id == context.away_team_id

    assert len(repository.calls) == 2
    assert provider.cache_size == 2


def test_repeated_vector_build_reuses_provider_cache() -> None:
    context = build_context()

    game = build_historical_game(
        game_id=401,
        game_number=1,
        team_id=context.home_team_id,
        opponent_team_id=context.away_team_id,
    )

    provider, repository = build_provider(
        context=context,
        games_by_team={
            context.home_team_id: (
                game,
            ),
        },
    )

    builder = TeamFeatureVectorBuilder(
        team_id=context.home_team_id,
    )

    first_vector = builder.build(
        context,
        provider,
    )

    second_vector = builder.build(
        context,
        provider,
    )

    assert first_vector == second_vector
    assert len(repository.calls) == 1
    assert provider.cache_size == 1