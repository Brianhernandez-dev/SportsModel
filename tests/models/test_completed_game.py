from datetime import datetime, timezone

import pytest

from sportsmodel.models.baseball_game import BaseballGame
from sportsmodel.models.completed_game import CompletedGame


def _build_game() -> BaseballGame:
    return BaseballGame(
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


def test_completed_game_reports_home_win() -> None:
    completed_game = CompletedGame(
        game=_build_game(),
        home_score=5,
        away_score=3,
    )

    assert completed_game.home_team_won is True


def test_completed_game_reports_home_loss() -> None:
    completed_game = CompletedGame(
        game=_build_game(),
        home_score=2,
        away_score=6,
    )

    assert completed_game.home_team_won is False


@pytest.mark.parametrize(
    ("home_score", "away_score"),
    [
        (-1, 3),
        (3, -1),
    ],
)
def test_completed_game_rejects_negative_scores(
    home_score: int,
    away_score: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="score cannot be negative",
    ):
        CompletedGame(
            game=_build_game(),
            home_score=home_score,
            away_score=away_score,
        )


def test_completed_game_rejects_tied_moneyline_target() -> None:
    completed_game = CompletedGame(
        game=_build_game(),
        home_score=4,
        away_score=4,
    )

    with pytest.raises(
        ValueError,
        match="tied game cannot produce a Moneyline target",
    ):
        _ = completed_game.home_team_won
