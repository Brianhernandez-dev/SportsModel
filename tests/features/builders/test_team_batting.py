from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.database.team_statistics_repository import (
    TeamStatisticsRepository,
)
from sportsmodel.features.builders.team_batting import (
    SEASON_GAME_LIMIT,
    TeamBattingFeatureBuilder,
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
    runs: int = 4,
    hits: int = 8,
    at_bats: int = 32,
    doubles: int = 2,
    triples: int = 0,
    home_runs: int = 1,
    walks: int = 3,
    strikeouts: int = 8,
    hit_by_pitch: int = 1,
    sacrifice_flies: int = 1,
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
        at_bats=at_bats,
        plate_appearances=(
            at_bats
            + walks
            + hit_by_pitch
            + sacrifice_flies
        ),
        doubles=doubles,
        triples=triples,
        home_runs=home_runs,
        walks=walks,
        intentional_walks=0,
        strikeouts=strikeouts,
        hit_by_pitch=hit_by_pitch,
        sacrifice_flies=sacrifice_flies,
        stolen_bases=0,
        caught_stealing=0,
        pitching_outs=27,
        runs_allowed=3,
        earned_runs_allowed=3,
        hits_allowed=7,
        home_runs_allowed=1,
        walks_allowed=2,
        strikeouts_recorded=9,
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
        TeamBattingFeatureBuilder(
            team_id=0,
        )


def test_builder_rejects_team_not_in_context() -> None:
    context = build_context()
    provider, _ = build_provider(
        context=context,
        games=(),
    )

    builder = TeamBattingFeatureBuilder(
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

    builder = TeamBattingFeatureBuilder(
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

    builder = TeamBattingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    assert features.games_played == 0
    assert features.runs_per_game_season is None
    assert features.runs_per_game_last_5 is None
    assert features.runs_per_game_last_10 is None
    assert features.hits_per_game_last_10 is None
    assert features.home_runs_per_game_last_10 is None
    assert features.walks_per_game_last_10 is None
    assert features.strikeouts_per_game_last_10 is None
    assert features.on_base_percentage_last_10 is None
    assert features.slugging_percentage_last_10 is None
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
            runs=6,
            hits=10,
            home_runs=2,
            walks=4,
            strikeouts=7,
        ),
        build_historical_game(
            game_id=102,
            game_number=2,
            runs=4,
            hits=8,
            home_runs=1,
            walks=2,
            strikeouts=9,
        ),
        build_historical_game(
            game_id=103,
            game_number=3,
            runs=2,
            hits=6,
            home_runs=0,
            walks=3,
            strikeouts=8,
        ),
    )

    provider, _ = build_provider(
        context=context,
        games=games,
    )

    builder = TeamBattingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    assert features.games_played == 3
    assert features.games_in_last_5_window == 3
    assert features.games_in_last_10_window == 3

    assert features.runs_per_game_season == pytest.approx(
        4.0
    )

    assert features.runs_per_game_last_5 == pytest.approx(
        4.0
    )

    assert features.runs_per_game_last_10 == pytest.approx(
        4.0
    )

    assert features.hits_per_game_last_10 == pytest.approx(
        8.0
    )

    assert (
        features.home_runs_per_game_last_10
        == pytest.approx(1.0)
    )

    assert features.walks_per_game_last_10 == pytest.approx(
        3.0
    )

    assert (
        features.strikeouts_per_game_last_10
        == pytest.approx(8.0)
    )


def test_builder_uses_newest_five_and_ten_games() -> None:
    context = build_context()

    games = tuple(
        build_historical_game(
            game_id=200 + index,
            game_number=index,
            runs=index,
        )
        for index in range(1, 13)
    )

    provider, _ = build_provider(
        context=context,
        games=games,
    )

    builder = TeamBattingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    assert features.games_played == 12

    assert features.runs_per_game_season == pytest.approx(
        6.5
    )

    assert features.runs_per_game_last_5 == pytest.approx(
        3.0
    )

    assert features.runs_per_game_last_10 == pytest.approx(
        5.5
    )

    assert features.games_in_last_5_window == 5
    assert features.games_in_last_10_window == 10


def test_builder_calculates_aggregate_obp() -> None:
    context = build_context()

    games = (
        build_historical_game(
            game_id=301,
            game_number=1,
            hits=8,
            at_bats=30,
            walks=4,
            hit_by_pitch=1,
            sacrifice_flies=1,
        ),
        build_historical_game(
            game_id=302,
            game_number=2,
            hits=10,
            at_bats=34,
            walks=2,
            hit_by_pitch=0,
            sacrifice_flies=2,
        ),
    )

    provider, _ = build_provider(
        context=context,
        games=games,
    )

    builder = TeamBattingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    expected_obp = (
        18 + 6 + 1
    ) / (
        64 + 6 + 1 + 3
    )

    assert (
        features.on_base_percentage_last_10
        == pytest.approx(expected_obp)
    )


def test_builder_calculates_aggregate_slugging() -> None:
    context = build_context()

    games = (
        build_historical_game(
            game_id=401,
            game_number=1,
            hits=8,
            at_bats=30,
            doubles=2,
            triples=1,
            home_runs=1,
        ),
        build_historical_game(
            game_id=402,
            game_number=2,
            hits=10,
            at_bats=34,
            doubles=3,
            triples=0,
            home_runs=2,
        ),
    )

    provider, _ = build_provider(
        context=context,
        games=games,
    )

    builder = TeamBattingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    total_hits = 18
    total_doubles = 5
    total_triples = 1
    total_home_runs = 3

    total_singles = (
        total_hits
        - total_doubles
        - total_triples
        - total_home_runs
    )

    total_bases = (
        total_singles
        + (2 * total_doubles)
        + (3 * total_triples)
        + (4 * total_home_runs)
    )

    expected_slugging = total_bases / 64

    assert (
        features.slugging_percentage_last_10
        == pytest.approx(expected_slugging)
    )


def test_builder_returns_none_for_zero_rate_denominators() -> None:
    context = build_context()

    games = (
        build_historical_game(
            game_id=501,
            game_number=1,
            runs=0,
            hits=0,
            at_bats=0,
            doubles=0,
            triples=0,
            home_runs=0,
            walks=0,
            strikeouts=0,
            hit_by_pitch=0,
            sacrifice_flies=0,
        ),
    )

    provider, _ = build_provider(
        context=context,
        games=games,
    )

    builder = TeamBattingFeatureBuilder(
        team_id=context.home_team_id,
    )

    features = builder.build(
        context,
        provider,
    )

    assert features.on_base_percentage_last_10 is None
    assert features.slugging_percentage_last_10 is None


def test_builder_reuses_provider_cache() -> None:
    context = build_context()

    games = (
        build_historical_game(
            game_id=601,
            game_number=1,
        ),
    )

    provider, repository = build_provider(
        context=context,
        games=games,
    )

    first_builder = TeamBattingFeatureBuilder(
        team_id=context.home_team_id,
    )

    second_builder = TeamBattingFeatureBuilder(
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