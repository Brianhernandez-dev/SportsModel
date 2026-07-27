from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.database.pitcher_statistics_repository import (
    PitcherStatisticsRepository,
)
from sportsmodel.database.team_statistics_repository import (
    TeamStatisticsRepository,
)
from sportsmodel.features.builders.game_feature_vector import (
    DEFAULT_FEATURE_SCHEMA_VERSION,
    GameFeatureVectorBuilder,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.provider import (
    FeatureDataProvider,
)
from sportsmodel.models.historical_pitcher_start import (
    HistoricalPitcherStart,
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


class FakePitcherStatisticsRepository(
    PitcherStatisticsRepository,
):
    def __init__(
        self,
        starts_by_player: dict[
            int,
            tuple[HistoricalPitcherStart, ...],
        ] | None = None,
    ) -> None:
        self.starts_by_player = starts_by_player or {}
        self.calls: list[
            tuple[int, datetime, int]
        ] = []

    def get_completed_starts_before(
        self,
        *,
        player_id: int,
        cutoff_time: datetime,
        limit: int,
    ) -> tuple[HistoricalPitcherStart, ...]:
        self.calls.append(
            (
                player_id,
                cutoff_time,
                limit,
            )
        )

        return self.starts_by_player.get(
            player_id,
            (),
        )[:limit]


def build_context(
    *,
    game_id: int = 500,
    game_start_time: datetime | None = None,
    cutoff_time: datetime | None = None,
    home_team_id: int = 10,
    away_team_id: int = 20,
    home_starting_pitcher_id: int | None = 30,
    away_starting_pitcher_id: int | None = 40,
) -> FeatureGenerationContext:
    resolved_game_start_time = (
        game_start_time
        or datetime(
            2026,
            7,
            20,
            2,
            10,
            tzinfo=timezone.utc,
        )
    )

    resolved_cutoff_time = (
        cutoff_time
        or resolved_game_start_time
        - timedelta(hours=1)
    )

    return FeatureGenerationContext(
        game_id=game_id,
        game_start_time=resolved_game_start_time,
        cutoff_time=resolved_cutoff_time,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_starting_pitcher_id=(
            home_starting_pitcher_id
        ),
        away_starting_pitcher_id=(
            away_starting_pitcher_id
        ),
    )


def build_historical_game(
    *,
    game_id: int,
    game_number: int,
    team_id: int,
    opponent_team_id: int,
    runs: int,
    runs_allowed: int,
) -> HistoricalTeamGame:
    earned_runs_allowed = min(
        runs_allowed,
        3,
    )

    statistics = TeamGameStatistics(
        game_id=game_id,
        team_id=team_id,
        is_home=True,
        runs=runs,
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
        pitching_outs=27,
        runs_allowed=runs_allowed,
        earned_runs_allowed=earned_runs_allowed,
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
        game_start_time=datetime(
            2026,
            7,
            19,
            23,
            10,
            tzinfo=timezone.utc,
        ) - timedelta(days=game_number),
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
    ] | None = None,
) -> tuple[
    FeatureDataProvider,
    FakeTeamStatisticsRepository,
]:
    repository = FakeTeamStatisticsRepository(
        games_by_team=games_by_team or {},
    )

    pitcher_repository = (
        FakePitcherStatisticsRepository()
    )

    provider = FeatureDataProvider(
        context,
        team_statistics_repository=repository,
        pitcher_statistics_repository=pitcher_repository,
    )

    return provider, repository


def test_builder_rejects_empty_schema_version() -> None:
    with pytest.raises(
        ValueError,
        match="schema version cannot be empty",
    ):
        GameFeatureVectorBuilder(
            feature_schema_version="   ",
        )

def test_builder_rejects_mismatched_provider_context() -> None:
    context = build_context()

    different_context = build_context(
        game_id=501,
    )

    provider, _ = build_provider(
        context=different_context,
    )

    with pytest.raises(
        ValueError,
        match="provider context must match",
    ):
        GameFeatureVectorBuilder().build(
            context,
            provider,
        )


def test_builder_assembles_complete_game_vector() -> None:
    context = build_context()

    home_games = (
        build_historical_game(
            game_id=101,
            game_number=1,
            team_id=context.home_team_id,
            opponent_team_id=context.away_team_id,
            runs=6,
            runs_allowed=2,
        ),
        build_historical_game(
            game_id=102,
            game_number=2,
            team_id=context.home_team_id,
            opponent_team_id=context.away_team_id,
            runs=4,
            runs_allowed=4,
        ),
    )

    away_games = (
        build_historical_game(
            game_id=201,
            game_number=1,
            team_id=context.away_team_id,
            opponent_team_id=context.home_team_id,
            runs=3,
            runs_allowed=5,
        ),
    )

    provider, repository = build_provider(
        context=context,
        games_by_team={
            context.home_team_id: home_games,
            context.away_team_id: away_games,
        },
    )

    vector = GameFeatureVectorBuilder().build(
        context,
        provider,
    )

    assert vector.game_id == context.game_id
    assert vector.game_start_time == context.game_start_time
    assert vector.feature_time == context.cutoff_time
    assert (
        vector.feature_schema_version
        == DEFAULT_FEATURE_SCHEMA_VERSION
    )

    assert vector.home_team.team_id == context.home_team_id
    assert vector.away_team.team_id == context.away_team_id

    assert vector.home_team.batting.games_played == 2
    assert vector.home_team.pitching.games_played == 2

    assert vector.away_team.batting.games_played == 1
    assert vector.away_team.pitching.games_played == 1

    assert (
        vector.home_team.batting.runs_per_game_season
        == pytest.approx(5.0)
    )
    assert (
        vector.home_team.pitching.runs_allowed_per_game_season
        == pytest.approx(3.0)
    )

    assert len(repository.calls) == 2
    assert provider.cache_size == 4


def test_builder_preserves_known_starting_pitchers() -> None:
    context = build_context(
        home_starting_pitcher_id=301,
        away_starting_pitcher_id=401,
    )

    provider, _ = build_provider(
        context=context,
    )

    vector = GameFeatureVectorBuilder().build(
        context,
        provider,
    )

    assert vector.home_starting_pitcher.player_id == 301
    assert vector.home_starting_pitcher.starter_available is True
    assert vector.home_starting_pitcher.starts_season == 0
    assert (
        vector.home_starting_pitcher.earned_run_average_season
        is None
    )

    assert vector.away_starting_pitcher.player_id == 401
    assert vector.away_starting_pitcher.starter_available is True
    assert vector.away_starting_pitcher.starts_season == 0


def test_builder_handles_unknown_starting_pitchers() -> None:
    context = build_context(
        home_starting_pitcher_id=None,
        away_starting_pitcher_id=None,
    )

    provider, _ = build_provider(
        context=context,
    )

    vector = GameFeatureVectorBuilder().build(
        context,
        provider,
    )

    assert vector.home_starting_pitcher.player_id is None
    assert (
        vector.home_starting_pitcher.starter_available
        is False
    )

    assert vector.away_starting_pitcher.player_id is None
    assert (
        vector.away_starting_pitcher.starter_available
        is False
    )


def test_builder_supports_custom_schema_version() -> None:
    context = build_context()

    provider, _ = build_provider(
        context=context,
    )

    builder = GameFeatureVectorBuilder(
        feature_schema_version="1.1.0",
    )

    vector = builder.build(
        context,
        provider,
    )

    assert vector.feature_schema_version == "1.1.0"


def test_repeated_build_reuses_team_history_cache() -> None:
    context = build_context()

    home_game = build_historical_game(
        game_id=301,
        game_number=1,
        team_id=context.home_team_id,
        opponent_team_id=context.away_team_id,
        runs=5,
        runs_allowed=3,
    )

    away_game = build_historical_game(
        game_id=302,
        game_number=1,
        team_id=context.away_team_id,
        opponent_team_id=context.home_team_id,
        runs=3,
        runs_allowed=5,
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

    builder = GameFeatureVectorBuilder()

    first_vector = builder.build(
        context,
        provider,
    )

    second_vector = builder.build(
        context,
        provider,
    )

    assert first_vector == second_vector
    assert len(repository.calls) == 2
    assert provider.cache_size == 4
