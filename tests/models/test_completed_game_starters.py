from datetime import datetime, timezone

import pytest

from sportsmodel.models.baseball_game import BaseballGame
from sportsmodel.models.completed_game import CompletedGame


def build_game() -> BaseballGame:
    return BaseballGame(
        game_id=100,
        game_start_time=datetime(
            2026,
            7,
            20,
            tzinfo=timezone.utc,
        ),
        home_team_id=10,
        away_team_id=20,
    )


@pytest.mark.parametrize(
    (
        "home_starting_pitcher_id",
        "away_starting_pitcher_id",
    ),
    [
        (0, 40),
        (-1, 40),
        (30, 0),
        (30, -1),
    ],
)
def test_completed_game_rejects_invalid_starter_ids(
    home_starting_pitcher_id: int,
    away_starting_pitcher_id: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="must be greater than zero",
    ):
        CompletedGame(
            game=build_game(),
            home_score=5,
            away_score=3,
            home_starting_pitcher_id=(
                home_starting_pitcher_id
            ),
            away_starting_pitcher_id=(
                away_starting_pitcher_id
            ),
        )


def test_completed_game_rejects_same_starter_for_both_teams() -> None:
    with pytest.raises(
        ValueError,
        match="must be different",
    ):
        CompletedGame(
            game=build_game(),
            home_score=5,
            away_score=3,
            home_starting_pitcher_id=30,
            away_starting_pitcher_id=30,
        )
