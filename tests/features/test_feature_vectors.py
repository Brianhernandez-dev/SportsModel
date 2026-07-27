from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

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


def build_team_feature_vector(
    team_id: int,
) -> TeamFeatureVector:
    return TeamFeatureVector(
        team_id=team_id,
        batting=TeamBattingFeatures(
            games_played=20,
            runs_per_game_season=4.5,
            runs_per_game_last_5=4.8,
            runs_per_game_last_10=4.6,
            hits_per_game_last_10=8.4,
            home_runs_per_game_last_10=1.2,
            walks_per_game_last_10=3.1,
            strikeouts_per_game_last_10=8.0,
            on_base_percentage_last_10=0.325,
            slugging_percentage_last_10=0.410,
            games_in_last_5_window=5,
            games_in_last_10_window=10,
        ),
        pitching=TeamPitchingFeatures(
            games_played=20,
            runs_allowed_per_game_season=4.1,
            runs_allowed_per_game_last_5=3.8,
            runs_allowed_per_game_last_10=4.0,
            earned_runs_allowed_per_game_last_10=3.7,
            hits_allowed_per_game_last_10=7.9,
            walks_allowed_per_game_last_10=2.8,
            strikeouts_per_game_last_10=8.7,
            home_runs_allowed_per_game_last_10=1.0,
            whip_last_10=1.21,
            games_in_last_5_window=5,
            games_in_last_10_window=10,
        ),
        bullpen=BullpenFeatures(
            relief_appearances_season=60,
            bullpen_earned_run_average_season=3.75,
            bullpen_earned_run_average_last_10=3.50,
            bullpen_whip_season=1.24,
            bullpen_whip_last_10=1.18,
            relief_innings_last_1_day=3.0,
            relief_innings_last_3_days=8.2,
            relief_innings_last_7_days=17.1,
            relievers_used_previous_game=4,
            back_to_back_usage_count=1,
            games_in_last_10_window=10,
        ),
        schedule=TeamScheduleFeatures(
            days_since_previous_game=1,
            played_previous_day=True,
            games_in_previous_3_days=3,
            games_in_previous_7_days=6,
            doubleheader_game=False,
            current_home_stand_length=3,
            current_road_trip_length=0,
        ),
    )


def build_starting_pitcher(
    player_id: int,
) -> StartingPitcherFeatures:
    return StartingPitcherFeatures(
        player_id=player_id,
        starter_available=True,
        starts_season=18,
        starts_last_5=5,
        innings_per_start_season=5.8,
        earned_run_average_season=3.42,
        earned_run_average_last_5=3.10,
        whip_season=1.17,
        whip_last_5=1.12,
        strikeouts_per_nine_season=9.4,
        walks_per_nine_season=2.3,
        home_runs_per_nine_season=0.9,
        days_rest=5,
    )


def test_team_feature_vector_is_immutable() -> None:
    vector = build_team_feature_vector(team_id=10)

    with pytest.raises(FrozenInstanceError):
        vector.team_id = 20


def test_team_feature_vector_rejects_invalid_team_id() -> None:
    with pytest.raises(
        ValueError,
        match="must be greater than zero",
    ):
        build_team_feature_vector(team_id=0)


def test_starting_pitcher_allows_unavailable_starter() -> None:
    features = StartingPitcherFeatures(
        player_id=None,
        starter_available=False,
        starts_season=0,
        starts_last_5=0,
        innings_per_start_season=None,
        earned_run_average_season=None,
        earned_run_average_last_5=None,
        whip_season=None,
        whip_last_5=None,
        strikeouts_per_nine_season=None,
        walks_per_nine_season=None,
        home_runs_per_nine_season=None,
        days_rest=None,
    )

    assert features.player_id is None
    assert features.starter_available is False


def test_starting_pitcher_rejects_inconsistent_availability() -> None:
    with pytest.raises(
        ValueError,
        match="must have a player ID",
    ):
        StartingPitcherFeatures(
            player_id=None,
            starter_available=True,
            starts_season=0,
            starts_last_5=0,
            innings_per_start_season=None,
            earned_run_average_season=None,
            earned_run_average_last_5=None,
            whip_season=None,
            whip_last_5=None,
            strikeouts_per_nine_season=None,
            walks_per_nine_season=None,
            home_runs_per_nine_season=None,
            days_rest=None,
        )


def test_schedule_rejects_conflicting_trip_state() -> None:
    with pytest.raises(
        ValueError,
        match="simultaneously",
    ):
        TeamScheduleFeatures(
            days_since_previous_game=1,
            played_previous_day=True,
            games_in_previous_3_days=2,
            games_in_previous_7_days=5,
            doubleheader_game=False,
            current_home_stand_length=2,
            current_road_trip_length=3,
        )


def test_game_feature_vector_stores_complete_features() -> None:
    game_start_time = datetime(
        2026,
        7,
        19,
        1,
        10,
        tzinfo=timezone.utc,
    )

    feature_time = game_start_time - timedelta(hours=1)

    vector = GameFeatureVector(
        game_id=100,
        game_start_time=game_start_time,
        feature_time=feature_time,
        feature_schema_version="mlb_game_features_v1",
        home_team=build_team_feature_vector(team_id=10),
        away_team=build_team_feature_vector(team_id=20),
        home_starting_pitcher=build_starting_pitcher(
            player_id=30,
        ),
        away_starting_pitcher=build_starting_pitcher(
            player_id=40,
        ),
    )

    assert vector.game_id == 100
    assert vector.feature_time == feature_time
    assert vector.home_team.team_id == 10
    assert vector.away_team.team_id == 20
    assert vector.feature_schema_version == (
        "mlb_game_features_v1"
    )


def test_game_feature_vector_rejects_same_team() -> None:
    game_start_time = datetime(
        2026,
        7,
        19,
        1,
        10,
        tzinfo=timezone.utc,
    )

    with pytest.raises(
        ValueError,
        match="different teams",
    ):
        GameFeatureVector(
            game_id=100,
            game_start_time=game_start_time,
            feature_time=game_start_time,
            feature_schema_version="mlb_game_features_v1",
            home_team=build_team_feature_vector(team_id=10),
            away_team=build_team_feature_vector(team_id=10),
            home_starting_pitcher=build_starting_pitcher(
                player_id=30,
            ),
            away_starting_pitcher=build_starting_pitcher(
                player_id=40,
            ),
        )


def test_game_feature_vector_rejects_future_feature_time() -> None:
    game_start_time = datetime(
        2026,
        7,
        19,
        1,
        10,
        tzinfo=timezone.utc,
    )

    with pytest.raises(
        ValueError,
        match="cannot occur after",
    ):
        GameFeatureVector(
            game_id=100,
            game_start_time=game_start_time,
            feature_time=(
                game_start_time + timedelta(seconds=1)
            ),
            feature_schema_version="mlb_game_features_v1",
            home_team=build_team_feature_vector(team_id=10),
            away_team=build_team_feature_vector(team_id=20),
            home_starting_pitcher=build_starting_pitcher(
                player_id=30,
            ),
            away_starting_pitcher=build_starting_pitcher(
                player_id=40,
            ),
        )


@pytest.mark.parametrize(
    "schema_version",
    [
        "",
        " ",
    ],
)
def test_game_feature_vector_rejects_empty_schema_version(
    schema_version: str,
) -> None:
    game_start_time = datetime(
        2026,
        7,
        19,
        1,
        10,
        tzinfo=timezone.utc,
    )

    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):
        GameFeatureVector(
            game_id=100,
            game_start_time=game_start_time,
            feature_time=game_start_time,
            feature_schema_version=schema_version,
            home_team=build_team_feature_vector(team_id=10),
            away_team=build_team_feature_vector(team_id=20),
            home_starting_pitcher=build_starting_pitcher(
                player_id=30,
            ),
            away_starting_pitcher=build_starting_pitcher(
                player_id=40,
            ),
        )
