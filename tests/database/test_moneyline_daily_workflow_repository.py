from datetime import date, datetime, timezone

import pytest

from sportsmodel.database.moneyline_daily_workflow_repository import (
    advance_moneyline_daily_workflow_stage,
    get_or_create_moneyline_daily_workflow_run,
    mark_moneyline_daily_workflow_awaiting_results,
    mark_moneyline_daily_settlement_completed,
    mark_moneyline_daily_workflow_completed,
    mark_moneyline_daily_workflow_failed,
    record_moneyline_daily_odds_run,
    record_moneyline_daily_prediction_run,
    start_moneyline_daily_workflow_attempt,
)


TARGET_DATE = date(2026, 8, 2)
TIMESTAMP = datetime(
    2026,
    8,
    1,
    23,
    30,
    tzinfo=timezone.utc,
)


class FakeCursor:
    def __init__(
        self,
        *,
        returned_row=None,
    ) -> None:
        self.returned_row = returned_row
        self.executed_query = None
        self.executed_parameters = None

    def execute(
        self,
        query,
        parameters,
    ) -> None:
        self.executed_query = query
        self.executed_parameters = parameters

    def fetchone(self):
        return self.returned_row


def test_gets_or_creates_workflow_for_target_date() -> None:
    cursor = FakeCursor(
        returned_row=(
            12,
            TARGET_DATE,
            "pending",
            "initialized",
            None,
            None,
            None,
            None,
            None,
            0,
            None,
            None,
            None,
            None,
            None,
            TIMESTAMP,
            TIMESTAMP,
        )
    )

    workflow = get_or_create_moneyline_daily_workflow_run(
        cursor,
        target_date=TARGET_DATE,
    )

    assert workflow.moneyline_daily_workflow_run_id == 12
    assert workflow.target_date == TARGET_DATE
    assert workflow.status == "pending"
    assert workflow.current_stage == "initialized"
    assert workflow.attempt_count == 0

    assert "ON CONFLICT" in cursor.executed_query
    assert "RETURNING" in cursor.executed_query
    assert cursor.executed_parameters == (TARGET_DATE,)


def test_raises_when_upsert_returns_no_row() -> None:
    cursor = FakeCursor(
        returned_row=None,
    )

    with pytest.raises(
        RuntimeError,
        match="returned no row",
    ):
        get_or_create_moneyline_daily_workflow_run(
            cursor,
            target_date=TARGET_DATE,
        )



class FakeUpdateCursor:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.executed_query = None
        self.executed_parameters = None

    def execute(self, query, parameters) -> None:
        self.executed_query = query
        self.executed_parameters = parameters


def test_starts_workflow_attempt() -> None:
    cursor = FakeUpdateCursor()

    start_moneyline_daily_workflow_attempt(
        cursor,
        workflow_run_id=12,
        current_stage="schedule_sync",
    )

    assert "attempt_count = attempt_count + 1" in cursor.executed_query
    assert cursor.executed_parameters == ("schedule_sync", 12)


def test_start_attempt_requires_existing_workflow() -> None:
    cursor = FakeUpdateCursor(rowcount=0)

    with pytest.raises(
        RuntimeError,
        match="exactly one row",
    ):
        start_moneyline_daily_workflow_attempt(
            cursor,
            workflow_run_id=12,
            current_stage="schedule_sync",
        )



def test_records_prediction_run() -> None:
    cursor = FakeUpdateCursor()

    record_moneyline_daily_prediction_run(
        cursor,
        workflow_run_id=12,
        prediction_run_id=25,
    )

    assert "current_stage = 'odds_ingestion'" in cursor.executed_query
    assert cursor.executed_parameters == (25, 12)


def test_prediction_update_requires_existing_workflow() -> None:
    cursor = FakeUpdateCursor(rowcount=0)

    with pytest.raises(
        RuntimeError,
        match="exactly one row",
    ):
        record_moneyline_daily_prediction_run(
            cursor,
            workflow_run_id=12,
            prediction_run_id=25,
        )



def test_records_odds_run_and_quota() -> None:
    cursor = FakeUpdateCursor()

    record_moneyline_daily_odds_run(
        cursor,
        workflow_run_id=12,
        odds_ingestion_run_id=182,
        status_code=200,
        remaining_requests=487,
        used_requests=13,
    )

    assert "current_stage = 'evaluation'" in cursor.executed_query
    assert cursor.executed_parameters == (
        182,
        200,
        487,
        13,
        12,
    )


def test_odds_update_requires_existing_workflow() -> None:
    cursor = FakeUpdateCursor(rowcount=0)

    with pytest.raises(
        RuntimeError,
        match="exactly one row",
    ):
        record_moneyline_daily_odds_run(
            cursor,
            workflow_run_id=12,
            odds_ingestion_run_id=182,
            status_code=200,
            remaining_requests=487,
            used_requests=13,
        )



def test_marks_workflow_awaiting_results() -> None:
    cursor = FakeUpdateCursor()

    mark_moneyline_daily_workflow_awaiting_results(
        cursor,
        workflow_run_id=12,
    )

    assert "status = 'awaiting_results'" in cursor.executed_query
    assert "current_stage = 'results_ingestion'" in cursor.executed_query
    assert cursor.executed_parameters == (12,)


def test_awaiting_results_requires_existing_workflow() -> None:
    cursor = FakeUpdateCursor(rowcount=0)

    with pytest.raises(
        RuntimeError,
        match="exactly one row",
    ):
        mark_moneyline_daily_workflow_awaiting_results(
            cursor,
            workflow_run_id=12,
        )



def test_marks_workflow_failed() -> None:
    cursor = FakeUpdateCursor()

    mark_moneyline_daily_workflow_failed(
        cursor,
        workflow_run_id=12,
        current_stage="odds_ingestion",
        error_message="  quota exhausted  ",
    )

    assert "status = 'failed'" in cursor.executed_query
    assert cursor.executed_parameters == (
        "odds_ingestion",
        "quota exhausted",
        12,
    )


def test_failure_requires_nonempty_error() -> None:
    cursor = FakeUpdateCursor()

    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):
        mark_moneyline_daily_workflow_failed(
            cursor,
            workflow_run_id=12,
            current_stage="odds_ingestion",
            error_message="   ",
        )



def test_advances_workflow_stage() -> None:
    cursor = FakeUpdateCursor()

    advance_moneyline_daily_workflow_stage(
        cursor,
        workflow_run_id=12,
        current_stage="evaluation",
    )

    assert "current_stage = %s" in cursor.executed_query
    assert cursor.executed_parameters == (
        "evaluation",
        12,
    )


def test_marks_settlement_completed() -> None:
    cursor = FakeUpdateCursor()

    mark_moneyline_daily_settlement_completed(
        cursor,
        workflow_run_id=12,
    )

    assert "current_stage = 'final_audit'" in cursor.executed_query
    assert "settlement_completed_at" in cursor.executed_query
    assert cursor.executed_parameters == (12,)


def test_marks_workflow_completed() -> None:
    cursor = FakeUpdateCursor()

    mark_moneyline_daily_workflow_completed(
        cursor,
        workflow_run_id=12,
    )

    assert "status = 'completed'" in cursor.executed_query
    assert "current_stage = 'complete'" in cursor.executed_query
    assert cursor.executed_parameters == (12,)
