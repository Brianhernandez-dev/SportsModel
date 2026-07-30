import pytest

from sportsmodel.auditing.moneyline_live_pipeline import (
    _build_audit,
    audit_moneyline_live_pipeline,
)


def test_reports_awaiting_results() -> None:
    audit = _audit_from_row(
        _row(
            predictions=10,
            evaluations=10,
            evaluated_predictions=10,
            paper_candidates=5,
            settlements=0,
        )
    )

    assert audit.pipeline_state == "awaiting_results"
    assert audit.pending_candidates == 5
    assert audit.integrity_issues == ()


def test_reports_complete_pipeline() -> None:
    audit = _audit_from_row(
        _row(
            predictions=10,
            evaluations=10,
            evaluated_predictions=10,
            paper_candidates=5,
            settlements=5,
        )
    )

    assert audit.pipeline_state == "complete"
    assert audit.pending_candidates == 0


def test_reports_awaiting_evaluations() -> None:
    audit = _audit_from_row(
        _row(
            predictions=10,
            evaluations=7,
            evaluated_predictions=7,
            paper_candidates=3,
            settlements=0,
        )
    )

    assert (
        audit.pipeline_state
        == "awaiting_evaluations"
    )


def test_reports_invalid_integrity_state() -> None:
    audit = _audit_from_row(
        _row(
            predictions=10,
            evaluations=11,
            evaluated_predictions=10,
            paper_candidates=5,
            settlements=6,
            duplicate_evaluations=1,
        )
    )

    assert audit.pipeline_state == "invalid"

    assert (
        "duplicate_evaluations"
        in audit.integrity_issues
    )

    assert (
        "settlement_count_exceeds_candidates"
        in audit.integrity_issues
    )


def test_service_executes_query_and_closes_connection() -> None:
    connection = FakeConnection(
        row=_row(
            predictions=10,
            evaluations=10,
            evaluated_predictions=10,
            paper_candidates=5,
            settlements=0,
        )
    )

    audit = audit_moneyline_live_pipeline(
        prediction_run_id=1,
        odds_ingestion_run_id=181,
        connection_factory=lambda: connection,
    )

    assert audit.predictions == 10
    assert connection.cursor_instance.executed is True
    assert connection.closed is True


def test_rejects_invalid_arguments() -> None:
    with pytest.raises(
        ValueError,
        match="Prediction run ID",
    ):
        audit_moneyline_live_pipeline(
            prediction_run_id=0,
            odds_ingestion_run_id=181,
        )

    with pytest.raises(
        ValueError,
        match="Policy version",
    ):
        audit_moneyline_live_pipeline(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            policy_version=" ",
        )


class FakeCursor:
    def __init__(self, row) -> None:
        self.row = row
        self.executed = False

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
        query,
        parameters,
    ) -> None:
        self.executed = True
        self.query = query
        self.parameters = parameters

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, *, row) -> None:
        self.cursor_instance = FakeCursor(row)
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def _audit_from_row(row):
    return _build_audit(
        prediction_run_id=1,
        odds_ingestion_run_id=181,
        policy_version="1.0.0",
        row=row,
    )


def _row(
    *,
    predictions: int,
    evaluations: int,
    evaluated_predictions: int,
    paper_candidates: int,
    settlements: int,
    prediction_status: str | None = "completed",
    odds_status: str | None = "completed",
    prediction_games: int | None = None,
    odds_snapshots: int = 196,
    odds_games: int = 10,
    duplicate_prediction_games: int = 0,
    duplicate_evaluations: int = 0,
    duplicate_settlements: int = 0,
):
    return (
        prediction_status,
        odds_status,
        predictions,
        (
            predictions
            if prediction_games is None
            else prediction_games
        ),
        odds_snapshots,
        odds_games,
        evaluations,
        evaluated_predictions,
        paper_candidates,
        settlements,
        duplicate_prediction_games,
        duplicate_evaluations,
        duplicate_settlements,
    )
