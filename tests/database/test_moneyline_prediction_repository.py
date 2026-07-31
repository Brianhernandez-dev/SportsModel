from datetime import date, datetime, timezone

from sportsmodel.database.moneyline_prediction_repository import (
    create_moneyline_prediction_run,
    insert_moneyline_game_prediction,
    mark_moneyline_prediction_run_completed,
    mark_moneyline_prediction_run_failed,
)
from sportsmodel.models.moneyline_prediction import (
    MoneylineGamePrediction,
)


class FakeCursor:
    def __init__(
        self,
        *,
        fetchone_result=None,
    ) -> None:
        self.fetchone_result = fetchone_result
        self.executions: list[
            tuple[str, tuple | None]
        ] = []

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False

    def execute(
        self,
        query: str,
        parameters=None,
    ) -> None:
        self.executions.append(
            (
                query,
                parameters,
            )
        )

    def fetchone(self):
        return self.fetchone_result


class FakeConnection:
    def __init__(
        self,
        *,
        fetchone_result=None,
    ) -> None:
        self.cursor_instance = FakeCursor(
            fetchone_result=fetchone_result,
        )
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_create_prediction_run_commits_audit_record() -> None:
    connection = FakeConnection(
        fetchone_result=(41,),
    )

    run_id = create_moneyline_prediction_run(
        connection,
        target_date=date(2026, 7, 29),
        model_version="mlb_moneyline_v1",
        feature_schema_version="1.2.0",
        model_artifact_sha256="a" * 64,
        model_training_cutoff=datetime(
            2026,
            7,
            28,
            1,
            45,
            tzinfo=timezone.utc,
        ),
    )

    assert run_id == 41
    assert connection.commits == 1

    query, parameters = (
        connection
        .cursor_instance
        .executions[0]
    )

    assert (
        "INSERT INTO moneyline_prediction_runs"
        in query
    )
    assert parameters[0] == date(
        2026,
        7,
        29,
    )


def test_insert_prediction_returns_identifier() -> None:
    cursor = FakeCursor(
        fetchone_result=(77,),
    )

    prediction_id = (
        insert_moneyline_game_prediction(
            cursor,
            _prediction(),
        )
    )

    assert prediction_id == 77

    query, parameters = cursor.executions[0]

    assert (
        "INSERT INTO moneyline_game_predictions"
        in query
    )
    assert parameters[0] == 1
    assert parameters[1] == 8049
    assert parameters[15] == 0.4047
    assert parameters[16] == 0.5953


def test_mark_prediction_run_completed() -> None:
    cursor = FakeCursor()

    mark_moneyline_prediction_run_completed(
        cursor,
        moneyline_prediction_run_id=5,
        games_received=16,
        predictions_created=16,
        games_skipped=0,
    )

    query, parameters = cursor.executions[0]

    assert "status = 'completed'" in query
    assert parameters == (
        16,
        16,
        0,
        5,
    )


def test_mark_prediction_run_failed_commits() -> None:
    connection = FakeConnection()

    mark_moneyline_prediction_run_failed(
        connection,
        moneyline_prediction_run_id=6,
        games_received=16,
        predictions_created=0,
        games_skipped=0,
        error_message="model failure",
    )

    query, parameters = (
        connection
        .cursor_instance
        .executions[0]
    )

    assert "status = 'failed'" in query
    assert parameters[-1] == 6
    assert connection.commits == 1


def _prediction() -> MoneylineGamePrediction:
    return MoneylineGamePrediction(
        moneyline_prediction_run_id=1,
        game_id=8049,
        mlb_game_id=823837,
        game_start_time=datetime(
            2026,
            7,
            29,
            16,
            10,
            tzinfo=timezone.utc,
        ),
        prediction_time=datetime(
            2026,
            7,
            29,
            5,
            48,
            tzinfo=timezone.utc,
        ),
        home_team_id=10,
        away_team_id=20,
        home_starting_pitcher_id=608,
        away_starting_pitcher_id=320,
        home_starting_pitcher_mlb_id=687473,
        away_starting_pitcher_mlb_id=666200,
        home_starter_features_available=True,
        away_starter_features_available=True,
        starter_coverage="both",
        missing_raw_value_count=2,
        home_win_probability=0.4047,
        away_win_probability=0.5953,
        predicted_team_id=20,
        predicted_probability=0.5953,
    )
