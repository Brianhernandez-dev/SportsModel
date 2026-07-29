from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.features.builders.bullpen import (
    BullpenFeatureBuilder,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.models.historical_bullpen_appearance import (
    HistoricalBullpenAppearance,
)
from sportsmodel.models.player_game_pitching_statistics import (
    PlayerGamePitchingStatistics,
)


@dataclass(frozen=True)
class HistoricalGameStub:
    game_id: int


class FakeFeatureDataProvider:
    def __init__(
        self,
        *,
        context: FeatureGenerationContext,
        appearances: tuple[
            HistoricalBullpenAppearance,
            ...,
        ] = (),
        game_ids: tuple[int, ...] = (),
    ) -> None:
        self.context = context
        self.appearances = appearances
        self.games = tuple(
            HistoricalGameStub(game_id=game_id)
            for game_id in game_ids
        )

    def get_completed_relief_appearances(
        self,
        *,
        team_id: int,
    ) -> tuple[HistoricalBullpenAppearance, ...]:
        return self.appearances

    def get_completed_team_games(
        self,
        *,
        team_id: int,
        limit: int,
    ) -> tuple[HistoricalGameStub, ...]:
        return self.games[:limit]


def build_context() -> FeatureGenerationContext:
    game_start_time = datetime(
        2026,
        7,
        27,
        1,
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
    )


def build_appearance(
    *,
    game_id: int,
    game_start_time: datetime,
    player_id: int,
    pitching_outs: int,
    hits_allowed: int,
    walks_allowed: int,
    earned_runs_allowed: int,
) -> HistoricalBullpenAppearance:
    statistics = PlayerGamePitchingStatistics(
        game_id=game_id,
        team_id=10,
        baseball_player_id=player_id,
        appearance_order=2,
        is_starter=False,
        pitching_outs=pitching_outs,
        batters_faced=None,
        hits_allowed=hits_allowed,
        runs_allowed=earned_runs_allowed,
        earned_runs_allowed=earned_runs_allowed,
        home_runs_allowed=0,
        walks_allowed=walks_allowed,
        intentional_walks_allowed=0,
        strikeouts=1,
        hit_batters=0,
        pitches_thrown=None,
        strikes_thrown=None,
        decision=None,
        save_recorded=False,
        hold_recorded=False,
        blown_save_recorded=False,
        source_name="mlb_stats_api",
    )

    return HistoricalBullpenAppearance(
        game_id=game_id,
        game_start_time=game_start_time,
        team_id=10,
        opponent_team_id=20,
        is_home=True,
        statistics=statistics,
    )


def test_builder_rejects_invalid_team_id() -> None:
    with pytest.raises(
        ValueError,
        match="must be greater than zero",
    ):
        BullpenFeatureBuilder(
            team_id=0,
        )


def test_builder_returns_empty_features_without_history() -> None:
    context = build_context()

    provider = FakeFeatureDataProvider(
        context=context,
    )

    features = BullpenFeatureBuilder(
        team_id=context.home_team_id,
    ).build(
        context,
        provider,
    )

    assert features.relief_appearances_season == 0
    assert features.bullpen_earned_run_average_season is None
    assert features.bullpen_whip_season is None
    assert features.relief_innings_last_1_day == 0.0
    assert features.relief_innings_last_3_days == 0.0
    assert features.relief_innings_last_7_days == 0.0
    assert features.relievers_used_previous_game is None
    assert features.back_to_back_usage_count is None
    assert features.games_in_last_10_window == 0


def test_builder_calculates_performance_and_workload() -> None:
    context = build_context()
    cutoff_time = context.cutoff_time

    appearances = (
        build_appearance(
            game_id=103,
            game_start_time=(
                cutoff_time - timedelta(hours=12)
            ),
            player_id=1,
            pitching_outs=3,
            hits_allowed=1,
            walks_allowed=1,
            earned_runs_allowed=1,
        ),
        build_appearance(
            game_id=103,
            game_start_time=(
                cutoff_time - timedelta(hours=12)
            ),
            player_id=2,
            pitching_outs=6,
            hits_allowed=1,
            walks_allowed=0,
            earned_runs_allowed=0,
        ),
        build_appearance(
            game_id=102,
            game_start_time=(
                cutoff_time - timedelta(hours=36)
            ),
            player_id=1,
            pitching_outs=3,
            hits_allowed=0,
            walks_allowed=1,
            earned_runs_allowed=0,
        ),
        build_appearance(
            game_id=102,
            game_start_time=(
                cutoff_time - timedelta(hours=36)
            ),
            player_id=3,
            pitching_outs=3,
            hits_allowed=2,
            walks_allowed=0,
            earned_runs_allowed=1,
        ),
        build_appearance(
            game_id=101,
            game_start_time=(
                cutoff_time - timedelta(days=4)
            ),
            player_id=4,
            pitching_outs=9,
            hits_allowed=1,
            walks_allowed=0,
            earned_runs_allowed=0,
        ),
    )

    provider = FakeFeatureDataProvider(
        context=context,
        appearances=appearances,
        game_ids=(
            103,
            102,
            101,
        ),
    )

    features = BullpenFeatureBuilder(
        team_id=context.home_team_id,
    ).build(
        context,
        provider,
    )

    assert features.relief_appearances_season == 5

    assert (
        features.bullpen_earned_run_average_season
        == pytest.approx(2.25)
    )
    assert (
        features.bullpen_earned_run_average_last_10
        == pytest.approx(2.25)
    )

    assert (
        features.bullpen_whip_season
        == pytest.approx(0.875)
    )
    assert (
        features.bullpen_whip_last_10
        == pytest.approx(0.875)
    )

    assert (
        features.relief_innings_last_1_day
        == pytest.approx(3.0)
    )
    assert (
        features.relief_innings_last_3_days
        == pytest.approx(5.0)
    )
    assert (
        features.relief_innings_last_7_days
        == pytest.approx(8.0)
    )

    assert features.relievers_used_previous_game == 2
    assert features.back_to_back_usage_count == 1
    assert features.games_in_last_10_window == 3


def test_builder_rejects_team_not_in_context() -> None:
    context = build_context()

    provider = FakeFeatureDataProvider(
        context=context,
    )

    with pytest.raises(
        ValueError,
        match="must match the home or away team",
    ):
        BullpenFeatureBuilder(
            team_id=999,
        ).build(
            context,
            provider,
        )
