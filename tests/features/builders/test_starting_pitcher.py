from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.database.pitcher_statistics_repository import (
    PitcherStatisticsRepository,
)
from sportsmodel.database.team_statistics_repository import (
    TeamStatisticsRepository,
)
from sportsmodel.features.builders.starting_pitcher import (
    SEASON_START_LIMIT,
    StartingPitcherFeatureBuilder,
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
from sportsmodel.models.player_game_pitching_statistics import (
    PlayerGamePitchingStatistics,
)


class FakeTeamStatisticsRepository(
    TeamStatisticsRepository,
):
    def get_completed_games_before(
        self,
        *,
        team_id: int,
        cutoff_time: datetime,
        limit: int,
    ) -> tuple[HistoricalTeamGame, ...]:
        return ()


class FakePitcherStatisticsRepository(
    PitcherStatisticsRepository,
):
    def __init__(
        self,
        starts: tuple[HistoricalPitcherStart, ...] = (),
    ) -> None:
        self.starts = starts
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

        return self.starts[:limit]


def build_context(
    *,
    game_id: int = 500,
    game_start_time: datetime | None = None,
    cutoff_time: datetime | None = None,
) -> FeatureGenerationContext:
    resolved_game_start_time = (
        game_start_time
        or datetime(
            2026,
            7,
            26,
            20,
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
        home_team_id=10,
        away_team_id=20,
        home_starting_pitcher_id=30,
        away_starting_pitcher_id=40,
    )


def build_start(
    *,
    game_id: int,
    game_start_time: datetime,
    player_id: int = 30,
    team_id: int = 10,
    opponent_team_id: int = 20,
    pitching_outs: int = 18,
    hits_allowed: int = 5,
    runs_allowed: int = 2,
    earned_runs_allowed: int = 2,
    home_runs_allowed: int = 1,
    walks_allowed: int = 1,
    strikeouts: int = 6,
) -> HistoricalPitcherStart:
    statistics = PlayerGamePitchingStatistics(
        game_id=game_id,
        team_id=team_id,
        baseball_player_id=player_id,
        appearance_order=1,
        is_starter=True,
        pitching_outs=pitching_outs,
        batters_faced=None,
        hits_allowed=hits_allowed,
        runs_allowed=runs_allowed,
        earned_runs_allowed=earned_runs_allowed,
        home_runs_allowed=home_runs_allowed,
        walks_allowed=walks_allowed,
        intentional_walks_allowed=0,
        strikeouts=strikeouts,
        hit_batters=0,
        pitches_thrown=None,
        strikes_thrown=None,
        decision=None,
        save_recorded=False,
        hold_recorded=False,
        blown_save_recorded=False,
        source_name="mlb_stats_api",
    )

    return HistoricalPitcherStart(
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
    starts: tuple[HistoricalPitcherStart, ...] = (),
) -> tuple[
    FeatureDataProvider,
    FakePitcherStatisticsRepository,
]:
    pitcher_repository = FakePitcherStatisticsRepository(
        starts=starts,
    )

    provider = FeatureDataProvider(
        context,
        team_statistics_repository=(
            FakeTeamStatisticsRepository()
        ),
        pitcher_statistics_repository=pitcher_repository,
    )

    return provider, pitcher_repository


def test_builder_rejects_invalid_player_id() -> None:
    with pytest.raises(
        ValueError,
        match="must be greater than zero",
    ):
        StartingPitcherFeatureBuilder(
            player_id=0,
        )


def test_missing_expected_starter_returns_unavailable_features() -> None:
    context = build_context()
    provider, repository = build_provider(
        context=context,
    )

    features = StartingPitcherFeatureBuilder(
        player_id=None,
    ).build(
        context,
        provider,
    )

    assert features.player_id is None
    assert features.starter_available is False
    assert features.starts_season == 0
    assert features.starts_last_5 == 0
    assert features.earned_run_average_season is None
    assert features.whip_season is None
    assert features.days_rest is None
    assert repository.calls == []


def test_known_starter_without_history_remains_available() -> None:
    context = build_context()
    provider, repository = build_provider(
        context=context,
    )

    features = StartingPitcherFeatureBuilder(
        player_id=30,
    ).build(
        context,
        provider,
    )

    assert features.player_id == 30
    assert features.starter_available is True
    assert features.starts_season == 0
    assert features.starts_last_5 == 0
    assert features.innings_per_start_season is None
    assert features.earned_run_average_season is None
    assert features.earned_run_average_last_5 is None
    assert features.whip_season is None
    assert features.whip_last_5 is None
    assert features.strikeouts_per_nine_season is None
    assert features.walks_per_nine_season is None
    assert features.home_runs_per_nine_season is None
    assert features.days_rest is None

    assert repository.calls == [
        (
            30,
            context.cutoff_time,
            SEASON_START_LIMIT,
        ),
    ]


def test_builder_calculates_season_and_last_5_statistics() -> None:
    context = build_context()

    starts = (
        build_start(
            game_id=101,
            game_start_time=datetime(
                2026,
                7,
                20,
                20,
                10,
                tzinfo=timezone.utc,
            ),
            pitching_outs=18,
            hits_allowed=5,
            runs_allowed=2,
            earned_runs_allowed=2,
            home_runs_allowed=1,
            walks_allowed=1,
            strikeouts=6,
        ),
        build_start(
            game_id=102,
            game_start_time=datetime(
                2026,
                7,
                14,
                20,
                10,
                tzinfo=timezone.utc,
            ),
            pitching_outs=15,
            hits_allowed=7,
            runs_allowed=3,
            earned_runs_allowed=3,
            home_runs_allowed=1,
            walks_allowed=2,
            strikeouts=4,
        ),
        build_start(
            game_id=103,
            game_start_time=datetime(
                2026,
                7,
                8,
                20,
                10,
                tzinfo=timezone.utc,
            ),
            pitching_outs=21,
            hits_allowed=4,
            runs_allowed=1,
            earned_runs_allowed=1,
            home_runs_allowed=0,
            walks_allowed=0,
            strikeouts=8,
        ),
        build_start(
            game_id=104,
            game_start_time=datetime(
                2026,
                7,
                2,
                20,
                10,
                tzinfo=timezone.utc,
            ),
            pitching_outs=18,
            hits_allowed=3,
            runs_allowed=0,
            earned_runs_allowed=0,
            home_runs_allowed=0,
            walks_allowed=1,
            strikeouts=7,
        ),
        build_start(
            game_id=105,
            game_start_time=datetime(
                2026,
                6,
                26,
                20,
                10,
                tzinfo=timezone.utc,
            ),
            pitching_outs=12,
            hits_allowed=8,
            runs_allowed=4,
            earned_runs_allowed=4,
            home_runs_allowed=2,
            walks_allowed=3,
            strikeouts=3,
        ),
    )

    provider, repository = build_provider(
        context=context,
        starts=starts,
    )

    features = StartingPitcherFeatureBuilder(
        player_id=30,
    ).build(
        context,
        provider,
    )

    assert features.starts_season == 5
    assert features.starts_last_5 == 5

    assert features.innings_per_start_season == pytest.approx(
        5.6
    )
    assert features.earned_run_average_season == pytest.approx(
        10 * 27 / 84
    )
    assert features.earned_run_average_last_5 == pytest.approx(
        10 * 27 / 84
    )
    assert features.whip_season == pytest.approx(
        34 * 3 / 84
    )
    assert features.whip_last_5 == pytest.approx(
        34 * 3 / 84
    )
    assert features.strikeouts_per_nine_season == pytest.approx(
        28 * 27 / 84
    )
    assert features.walks_per_nine_season == pytest.approx(
        7 * 27 / 84
    )
    assert features.home_runs_per_nine_season == pytest.approx(
        4 * 27 / 84
    )
    assert features.days_rest == 5

    assert repository.calls == [
        (
            30,
            context.cutoff_time,
            SEASON_START_LIMIT,
        ),
    ]


def test_last_5_window_can_include_previous_season() -> None:
    context = build_context()

    starts = (
        build_start(
            game_id=201,
            game_start_time=datetime(
                2026,
                7,
                20,
                tzinfo=timezone.utc,
            ),
            earned_runs_allowed=2,
            runs_allowed=2,
        ),
        build_start(
            game_id=202,
            game_start_time=datetime(
                2026,
                7,
                14,
                tzinfo=timezone.utc,
            ),
            earned_runs_allowed=4,
            runs_allowed=4,
        ),
        build_start(
            game_id=203,
            game_start_time=datetime(
                2025,
                10,
                1,
                tzinfo=timezone.utc,
            ),
            earned_runs_allowed=0,
            runs_allowed=0,
        ),
        build_start(
            game_id=204,
            game_start_time=datetime(
                2025,
                9,
                25,
                tzinfo=timezone.utc,
            ),
            earned_runs_allowed=0,
            runs_allowed=0,
        ),
        build_start(
            game_id=205,
            game_start_time=datetime(
                2025,
                9,
                19,
                tzinfo=timezone.utc,
            ),
            earned_runs_allowed=0,
            runs_allowed=0,
        ),
    )

    provider, _ = build_provider(
        context=context,
        starts=starts,
    )

    features = StartingPitcherFeatureBuilder(
        player_id=30,
    ).build(
        context,
        provider,
    )

    assert features.starts_season == 2
    assert features.starts_last_5 == 5
    assert features.innings_per_start_season == pytest.approx(
        6.0
    )
    assert features.earned_run_average_season == pytest.approx(
        4.5
    )
    assert features.earned_run_average_last_5 == pytest.approx(
        1.8
    )


def test_zero_out_start_does_not_divide_by_zero() -> None:
    context = build_context()

    starts = (
        build_start(
            game_id=301,
            game_start_time=datetime(
                2026,
                7,
                20,
                tzinfo=timezone.utc,
            ),
            pitching_outs=0,
            hits_allowed=2,
            runs_allowed=1,
            earned_runs_allowed=1,
            home_runs_allowed=1,
            walks_allowed=1,
            strikeouts=0,
        ),
    )

    provider, _ = build_provider(
        context=context,
        starts=starts,
    )

    features = StartingPitcherFeatureBuilder(
        player_id=30,
    ).build(
        context,
        provider,
    )

    assert features.starts_season == 1
    assert features.starts_last_5 == 1
    assert features.innings_per_start_season == pytest.approx(
        0.0
    )
    assert features.earned_run_average_season is None
    assert features.earned_run_average_last_5 is None
    assert features.whip_season is None
    assert features.whip_last_5 is None
    assert features.strikeouts_per_nine_season is None
    assert features.walks_per_nine_season is None
    assert features.home_runs_per_nine_season is None


def test_builder_rejects_mismatched_provider_context() -> None:
    context = build_context()

    other_context = build_context(
        game_id=501,
    )

    provider, _ = build_provider(
        context=other_context,
    )

    with pytest.raises(
        ValueError,
        match="provider context must match",
    ):
        StartingPitcherFeatureBuilder(
            player_id=30,
        ).build(
            context,
            provider,
        )
