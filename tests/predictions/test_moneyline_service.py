from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from sportsmodel.models.baseball_game import (
    BaseballGame,
)
from sportsmodel.predictions import (
    moneyline_service as service,
)


PREDICTION_TIME = datetime(
    2026,
    7,
    29,
    10,
    0,
    tzinfo=timezone.utc,
)


class FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False


class FakeFeatureService:
    def __init__(
        self,
        *,
        fail: bool = False,
    ) -> None:
        self.fail = fail

    def generate_for_game_record(
        self,
        *,
        game,
        cutoff_time,
        home_starting_pitcher_id=None,
        away_starting_pitcher_id=None,
    ):
        if self.fail:
            raise RuntimeError(
                "feature failure"
            )

        return SimpleNamespace(
            feature_schema_version="1.2.0",
            home_starting_pitcher=(
                SimpleNamespace(
                    starter_available=(
                        home_starting_pitcher_id
                        is not None
                    )
                )
            ),
            away_starting_pitcher=(
                SimpleNamespace(
                    starter_available=(
                        away_starting_pitcher_id
                        is not None
                    )
                )
            ),
        )


class FakeModel:
    def __init__(self) -> None:
        self.transformer = SimpleNamespace(
            source_feature_names=(
                "feature",
            )
        )
        self.model = SimpleNamespace(
            feature_schema_version="1.2.0"
        )

    def predict_home_win_probability(
        self,
        features,
    ) -> float:
        return 0.60


def test_daily_prediction_run_persists_future_game(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    inserted_predictions = []
    completed_calls = []

    _patch_common_dependencies(
        monkeypatch,
        connection=connection,
        schedule_payload=_schedule_payload(
            game_time="2026-07-30T17:40:00Z",
        ),
    )

    monkeypatch.setattr(
        service,
        "insert_moneyline_game_prediction",
        lambda cursor, prediction: (
            inserted_predictions.append(
                prediction
            )
            or 91
        ),
    )

    monkeypatch.setattr(
        service,
        "mark_moneyline_prediction_run_completed",
        lambda cursor, **kwargs: (
            completed_calls.append(kwargs)
        ),
    )

    result = service.run_moneyline_predictions(
        target_date=date(
            2026,
            7,
            30,
        ),
        prediction_time=PREDICTION_TIME,
        connection_factory=lambda: connection,
        feature_generation_service=(
            FakeFeatureService()
        ),
    )

    assert result.moneyline_prediction_run_id == 41
    assert result.games_received == 1
    assert result.predictions_created == 1
    assert result.games_skipped == 0
    assert len(inserted_predictions) == 1

    prediction = inserted_predictions[0]

    assert prediction.starter_coverage == "both"
    assert prediction.home_win_probability == 0.60
    assert prediction.away_win_probability == 0.40
    assert prediction.predicted_team_id == 10

    assert completed_calls[0][
        "predictions_created"
    ] == 1

    assert connection.commits == 1
    assert connection.closed is True


def test_started_game_is_skipped(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    completed_calls = []

    payload = {
        "dates": [
            {
                "games": [
                    _schedule_game(
                        game_pk=1001,
                        game_time=(
                            "2026-07-29T09:00:00Z"
                        ),
                    ),
                    _schedule_game(
                        game_pk=1002,
                        game_time=(
                            "2026-07-30T17:40:00Z"
                        ),
                    ),
                ]
            }
        ]
    }

    _patch_common_dependencies(
        monkeypatch,
        connection=connection,
        schedule_payload=payload,
    )

    monkeypatch.setattr(
        service,
        "insert_moneyline_game_prediction",
        lambda cursor, prediction: 1,
    )

    monkeypatch.setattr(
        service,
        "mark_moneyline_prediction_run_completed",
        lambda cursor, **kwargs: (
            completed_calls.append(kwargs)
        ),
    )

    result = service.run_moneyline_predictions(
        target_date=date(
            2026,
            7,
            30,
        ),
        prediction_time=PREDICTION_TIME,
        connection_factory=lambda: connection,
        feature_generation_service=(
            FakeFeatureService()
        ),
    )

    assert result.games_received == 2
    assert result.predictions_created == 1
    assert result.games_skipped == 1

    assert completed_calls[0][
        "games_skipped"
    ] == 1


def test_prediction_failure_rolls_back_and_marks_run_failed(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    failed_calls = []

    _patch_common_dependencies(
        monkeypatch,
        connection=connection,
        schedule_payload=_schedule_payload(
            game_time="2026-07-30T17:40:00Z",
        ),
    )

    monkeypatch.setattr(
        service,
        "mark_moneyline_prediction_run_failed",
        lambda connection, **kwargs: (
            failed_calls.append(kwargs)
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="feature failure",
    ):
        service.run_moneyline_predictions(
            target_date=date(
                2026,
                7,
                30,
            ),
            prediction_time=PREDICTION_TIME,
            connection_factory=lambda: connection,
            feature_generation_service=(
                FakeFeatureService(
                    fail=True
                )
            ),
        )

    assert connection.rollbacks == 1
    assert connection.closed is True
    assert failed_calls[0][
        "moneyline_prediction_run_id"
    ] == 41
    assert failed_calls[0][
        "predictions_created"
    ] == 0


def test_model_package_rejects_hash_mismatch(
    tmp_path: Path,
) -> None:
    model_path = (
        tmp_path / "model.joblib"
    )
    manifest_path = (
        tmp_path / "manifest.json"
    )

    model_path.write_bytes(
        b"not-the-frozen-model"
    )

    manifest_path.write_text(
        """
        {
          "model_version": "mlb_moneyline_v1",
          "feature_schema_version": "1.2.0",
          "artifacts": {
            "model": {
              "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }
          },
          "training": {
            "end_time": "2026-07-28T01:45:00+00:00"
          }
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="checksum",
    ):
        service.load_moneyline_model_package(
            tmp_path
        )


def _patch_common_dependencies(
    monkeypatch,
    *,
    connection: FakeConnection,
    schedule_payload: dict,
) -> None:
    monkeypatch.setattr(
        service,
        "load_moneyline_model_package",
        lambda model_directory: (
            service.LoadedMoneylineModelPackage(
                model=FakeModel(),
                model_version=(
                    "mlb_moneyline_v1"
                ),
                feature_schema_version=(
                    "1.2.0"
                ),
                model_artifact_sha256=(
                    "a" * 64
                ),
                model_training_cutoff=datetime(
                    2026,
                    7,
                    28,
                    1,
                    45,
                    tzinfo=timezone.utc,
                ),
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "fetch_hydrated_schedule_for_date",
        lambda target_date: (
            schedule_payload
        ),
    )

    monkeypatch.setattr(
        service,
        "sync_mlb_schedule",
        lambda **kwargs: (
            SimpleNamespace(
                dates_failed=0
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "create_moneyline_prediction_run",
        lambda connection, **kwargs: 41,
    )

    monkeypatch.setattr(
        service,
        "get_player_ids_by_source",
        lambda source_name, player_ids: {
            player_id: player_id + 1000
            for player_id in player_ids
        },
    )

    monkeypatch.setattr(
        service,
        "sync_mlb_players",
        lambda player_ids: None,
    )

    monkeypatch.setattr(
        service,
        "_get_canonical_game",
        lambda connection, mlb_game_id: (
            BaseballGame(
                game_id=mlb_game_id,
                game_start_time=datetime(
                    2026,
                    7,
                    30,
                    17,
                    40,
                    tzinfo=timezone.utc,
                ),
                home_team_id=10,
                away_team_id=20,
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "flatten_game_feature_vector",
        lambda vector: {
            "feature": 1.0,
        },
    )



def _schedule_payload(
    *,
    game_time: str,
) -> dict:
    return {
        "dates": [
            {
                "games": [
                    _schedule_game(
                        game_pk=1001,
                        game_time=game_time,
                    )
                ]
            }
        ]
    }


def _schedule_game(
    *,
    game_pk: int,
    game_time: str,
) -> dict:
    return {
        "gamePk": game_pk,
        "gameType": "R",
        "gameDate": game_time,
        "teams": {
            "away": {
                "team": {
                    "name": "Away Team",
                },
                "probablePitcher": {
                    "id": 101,
                    "fullName": (
                        "Away Pitcher"
                    ),
                },
            },
            "home": {
                "team": {
                    "name": "Home Team",
                },
                "probablePitcher": {
                    "id": 202,
                    "fullName": (
                        "Home Pitcher"
                    ),
                },
            },
        },
    }



