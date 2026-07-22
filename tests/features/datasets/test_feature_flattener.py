from datetime import datetime, timezone

import pytest

from sportsmodel.features.datasets.feature_flattener import (
    flatten_game_feature_vector,
)
from sportsmodel.models.bullpen_features import (
    BullpenFeatures,
)
from sportsmodel.models.game_feature_vector import (
    GameFeatureVector,
)
from sportsmodel.models.starting_pitcher_features import (
    StartingPitcherFeatures,
)
from sportsmodel.models.team_batting_features import (
    TeamBattingFeatures,
)
from sportsmodel.models.team_feature_vector import (
    TeamFeatureVector,
)
from sportsmodel.models.team_pitching_features import (
    TeamPitchingFeatures,
)
from sportsmodel.models.team_schedule_features import (
    TeamScheduleFeatures,
)


def test_flatten_game_feature_vector_creates_stable_names() -> None:
    vector = _build_game_feature_vector()

    flattened = flatten_game_feature_vector(vector)

    assert (
        flattened["home_batting_runs_per_game_season"]
        == 4.8
    )
    assert (
        flattened["away_pitching_whip_last_10"]
        == 1.31
    )
    assert (
        flattened[
            "home_bullpen_relief_innings_last_3_days"
        ]
        == 7.2
    )
    assert (
        flattened[
            "away_schedule_days_since_previous_game"
        ]
        == 1
    )
    assert (
        flattened[
            "home_starting_pitcher_"
            "earned_run_average_season"
        ]
        == 3.45
    )


def test_flatten_game_feature_vector_excludes_metadata() -> None:
    vector = _build_game_feature_vector()

    flattened = flatten_game_feature_vector(vector)

    assert "game_id" not in flattened
    assert "game_start_time" not in flattened
    assert "feature_time" not in flattened
    assert "feature_schema_version" not in flattened

    assert "home_team_id" not in flattened
    assert "away_team_id" not in flattened

    assert (
        "home_starting_pitcher_player_id"
        not in flattened
    )
    assert (
        "away_starting_pitcher_player_id"
        not in flattened
    )


def test_flatten_game_feature_vector_preserves_nulls() -> None:
    vector = _build_game_feature_vector()

    flattened = flatten_game_feature_vector(vector)

    assert (
        flattened[
            "away_starting_pitcher_"
            "earned_run_average_last_5"
        ]
        is None
    )


def test_flatten_game_feature_vector_preserves_booleans() -> None:
    vector = _build_game_feature_vector()

    flattened = flatten_game_feature_vector(vector)

    assert (
        flattened[
            "home_starting_pitcher_starter_available"
        ]
        is True
    )
    assert (
        flattened["away_schedule_played_previous_day"]
        is True
    )


def test_flatten_game_feature_vector_rejects_wrong_type() -> None:
    with pytest.raises(
        TypeError,
        match="Vector must be a GameFeatureVector",
    ):
        flatten_game_feature_vector(object())  # type: ignore[arg-type]


def _build_game_feature_vector() -> GameFeatureVector:
    game_start_time = datetime(
        2026,
        7,
        21,
        19,
        10,
        tzinfo=timezone.utc,
    )

    return GameFeatureVector(
        game_id=5001,
        game_start_time=game_start_time,
        feature_time=game_start_time,
        feature_schema_version="1.0",
        home_team=_build_team_feature_vector(
            team_id=10,
            home=True,
        ),
        away_team=_build_team_feature_vector(
            team_id=20,
            home=False,
        ),
        home_starting_pitcher=_build_starting_pitcher(
            player_id=101,
            home=True,
        ),
        away_starting_pitcher=_build_starting_pitcher(
            player_id=202,
            home=False,
        ),
    )


def _build_team_feature_vector(
    *,
    team_id: int,
    home: bool,
) -> TeamFeatureVector:
    return TeamFeatureVector(
        team_id=team_id,
        batting=TeamBattingFeatures(
            games_played=90,
            runs_per_game_season=4.8 if home else 4.3,
            runs_per_game_last_5=5.1 if home else 4.0,
            runs_per_game_last_10=4.9 if home else 4.2,
            hits_per_game_last_10=8.7,
            home_runs_per_game_last_10=1.3,
            walks_per_game_last_10=3.4,
            strikeouts_per_game_last_10=8.1,
            on_base_percentage_last_10=0.332,
            slugging_percentage_last_10=0.429,
            games_in_last_5_window=5,
            games_in_last_10_window=10,
        ),
        pitching=TeamPitchingFeatures(
            games_played=90,
            runs_allowed_per_game_season=4.1,
            runs_allowed_per_game_last_5=3.8,
            runs_allowed_per_game_last_10=4.0,
            earned_runs_allowed_per_game_last_10=3.7,
            hits_allowed_per_game_last_10=8.0,
            walks_allowed_per_game_last_10=2.9,
            strikeouts_per_game_last_10=9.0,
            home_runs_allowed_per_game_last_10=1.1,
            whip_last_10=1.22 if home else 1.31,
            games_in_last_5_window=5,
            games_in_last_10_window=10,
        ),
        bullpen=BullpenFeatures(
            relief_appearances_season=180,
            bullpen_earned_run_average_season=3.72,
            bullpen_earned_run_average_last_10=3.55,
            bullpen_whip_season=1.25,
            bullpen_whip_last_10=1.21,
            relief_innings_last_1_day=2.1,
            relief_innings_last_3_days=7.2,
            relief_innings_last_7_days=18.4,
            relievers_used_previous_game=4,
            back_to_back_usage_count=2,
            games_in_last_10_window=10,
        ),
        schedule=TeamScheduleFeatures(
            days_since_previous_game=2 if home else 1,
            played_previous_day=not home,
            games_in_previous_3_days=2,
            games_in_previous_7_days=6,
            doubleheader_game=False,
            current_home_stand_length=3 if home else 0,
            current_road_trip_length=0 if home else 4,
        ),
    )


def _build_starting_pitcher(
    *,
    player_id: int,
    home: bool,
) -> StartingPitcherFeatures:
    return StartingPitcherFeatures(
        player_id=player_id,
        starter_available=True,
        starts_season=18,
        starts_last_5=5,
        innings_per_start_season=5.8,
        earned_run_average_season=3.45 if home else 4.02,
        earned_run_average_last_5=3.12 if home else None,
        whip_season=1.18,
        whip_last_5=1.10,
        strikeouts_per_nine_season=9.2,
        walks_per_nine_season=2.5,
        home_runs_per_nine_season=1.0,
        days_rest=5,
    )
