from datetime import date, datetime, timezone

import pytest

from sportsmodel.database.moneyline_prediction_repository import (
    create_moneyline_prediction_run,
)


class FakeCursor:
    def __init__(self) -> None:
        self.query = None
        self.parameters = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, parameters) -> None:
        self.query = query
        self.parameters = parameters

    def fetchone(self):
        return (99,)


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.commits = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


def test_creates_preview_prediction_run() -> None:
    connection = FakeConnection()

    run_id = create_moneyline_prediction_run(
        connection,
        target_date=date(2026, 8, 8),
        model_version="mlb_moneyline_v1",
        feature_schema_version="1.2.0",
        model_artifact_sha256="a" * 64,
        model_training_cutoff=datetime(
            2026,
            7,
            25,
            tzinfo=timezone.utc,
        ),
        run_type="preview",
    )

    assert run_id == 99
    assert connection.commits == 1
    assert "run_type" in connection.cursor_instance.query
    assert "preview" in connection.cursor_instance.parameters


def test_rejects_invalid_prediction_run_type() -> None:
    connection = FakeConnection()

    with pytest.raises(ValueError, match="official or preview"):
        create_moneyline_prediction_run(
            connection,
            target_date=date(2026, 8, 8),
            model_version="mlb_moneyline_v1",
            feature_schema_version="1.2.0",
            model_artifact_sha256="a" * 64,
            model_training_cutoff=None,
            run_type="settled",
        )

    assert connection.commits == 0
