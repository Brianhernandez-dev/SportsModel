from datetime import date
from typing import Any

from sportsmodel.models.moneyline_daily_workflow import (
    MoneylineDailyWorkflowRun,
)


_WORKFLOW_COLUMNS = """
    moneyline_daily_workflow_run_id,
    target_date,
    status,
    current_stage,
    moneyline_prediction_run_id,
    odds_ingestion_run_id,
    odds_status_code,
    odds_remaining_requests,
    odds_used_requests,
    attempt_count,
    last_attempt_started_at,
    last_attempt_completed_at,
    pregame_completed_at,
    settlement_completed_at,
    error_message,
    created_at,
    updated_at
"""


def get_or_create_moneyline_daily_workflow_run(
    cursor: Any,
    *,
    target_date: date,
) -> MoneylineDailyWorkflowRun:
    """
    Return the durable daily workflow row for one target date.

    Re-running the same date returns the existing row rather than
    creating a duplicate workflow.
    """

    cursor.execute(
        f"""
        INSERT INTO moneyline_daily_workflow_runs (
            target_date
        )
        VALUES (%s)
        ON CONFLICT (
            target_date
        )
        DO UPDATE SET
            updated_at = CURRENT_TIMESTAMP
        RETURNING
            {_WORKFLOW_COLUMNS};
        """,
        (target_date,),
    )

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Daily Moneyline workflow upsert returned no row."
        )

    return _build_workflow_run(row)


def _build_workflow_run(
    row: tuple[Any, ...],
) -> MoneylineDailyWorkflowRun:
    return MoneylineDailyWorkflowRun(
        moneyline_daily_workflow_run_id=row[0],
        target_date=row[1],
        status=row[2],
        current_stage=row[3],
        moneyline_prediction_run_id=row[4],
        odds_ingestion_run_id=row[5],
        odds_status_code=row[6],
        odds_remaining_requests=row[7],
        odds_used_requests=row[8],
        attempt_count=row[9],
        last_attempt_started_at=row[10],
        last_attempt_completed_at=row[11],
        pregame_completed_at=row[12],
        settlement_completed_at=row[13],
        error_message=row[14],
        created_at=row[15],
        updated_at=row[16],
    )
