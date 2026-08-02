from datetime import date, datetime, timezone

import pytest

from sportsmodel.database.moneyline_daily_workflow_repository import (
    get_or_create_moneyline_daily_workflow_run,
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
