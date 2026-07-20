from datetime import datetime, timezone

import pytest

from sportsmodel.models.baseball_game import BaseballGame


def test_baseball_game_accepts_valid_values() -> None:
    game = BaseballGame(
        game_id=101,
        game_start_time=datetime(
            2026,
            7,
            20,
            19,
            10,
            tzinfo=timezone.utc,
        ),
        home_team_id=10,
        away_team_id=20,
    )

    assert game.game_id == 101
    assert game.home_team_id == 10
    assert game.away_team_id == 20


def test_baseball_game_rejects_invalid_game_id() -> None:
    with pytest.raises(
        ValueError,
        match="Game ID must be greater than zero",
    ):
        BaseballGame(
            game_id=0,
            game_start_time=datetime(
                2026,
                7,
                20,
                tzinfo=timezone.utc,
            ),
            home_team_id=10,
            away_team_id=20,
        )


def test_baseball_game_rejects_naive_start_time() -> None:
    with pytest.raises(
        ValueError,
        match="Game start time must be timezone-aware",
    ):
        BaseballGame(
            game_id=101,
            game_start_time=datetime(
                2026,
                7,
                20,
            ),
            home_team_id=10,
            away_team_id=20,
        )


def test_baseball_game_rejects_matching_teams() -> None:
    with pytest.raises(
        ValueError,
        match="Home and away teams must be different",
    ):
        BaseballGame(
            game_id=101,
            game_start_time=datetime(
                2026,
                7,
                20,
                tzinfo=timezone.utc,
            ),
            home_team_id=10,
            away_team_id=10,
        )
