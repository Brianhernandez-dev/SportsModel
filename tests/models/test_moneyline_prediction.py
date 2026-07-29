from datetime import datetime, timezone

import pytest

from sportsmodel.models.moneyline_prediction import (
    MoneylineGamePrediction,
)


def test_valid_moneyline_prediction() -> None:
    prediction = _prediction()

    assert prediction.starter_coverage == "both"
    assert prediction.predicted_team_id == 20


def test_prediction_rejects_probabilities_not_summing_to_one() -> None:
    with pytest.raises(
        ValueError,
        match="must sum to one",
    ):
        _prediction(
            home_win_probability=0.60,
            away_win_probability=0.50,
            predicted_probability=0.60,
        )


def test_prediction_rejects_incorrect_starter_coverage() -> None:
    with pytest.raises(
        ValueError,
        match="does not match",
    ):
        _prediction(
            starter_coverage="none",
        )


def test_prediction_rejects_postgame_prediction_time() -> None:
    with pytest.raises(
        ValueError,
        match="after game start",
    ):
        _prediction(
            prediction_time=datetime(
                2026,
                7,
                29,
                20,
                0,
                tzinfo=timezone.utc,
            ),
        )


def _prediction(
    **overrides,
) -> MoneylineGamePrediction:
    values = {
        "moneyline_prediction_run_id": 1,
        "game_id": 8049,
        "mlb_game_id": 823837,
        "game_start_time": datetime(
            2026,
            7,
            29,
            16,
            10,
            tzinfo=timezone.utc,
        ),
        "prediction_time": datetime(
            2026,
            7,
            29,
            5,
            48,
            tzinfo=timezone.utc,
        ),
        "home_team_id": 10,
        "away_team_id": 20,
        "home_starting_pitcher_id": 608,
        "away_starting_pitcher_id": 320,
        "home_starting_pitcher_mlb_id": 687473,
        "away_starting_pitcher_mlb_id": 666200,
        "home_starter_features_available": True,
        "away_starter_features_available": True,
        "starter_coverage": "both",
        "missing_raw_value_count": 2,
        "home_win_probability": 0.4047,
        "away_win_probability": 0.5953,
        "predicted_team_id": 20,
        "predicted_probability": 0.5953,
    }

    values.update(overrides)

    return MoneylineGamePrediction(
        **values
    )
