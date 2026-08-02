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


def start_moneyline_daily_workflow_attempt(
    cursor: Any,
    *,
    workflow_run_id: int,
    current_stage: str,
) -> None:
    """
    Start or restart one durable workflow attempt.
    """

    if workflow_run_id <= 0:
        raise ValueError(
            "Daily workflow run ID must be greater than zero."
        )

    cursor.execute(
        """
        UPDATE moneyline_daily_workflow_runs
        SET status = 'running',
            current_stage = %s,
            attempt_count = attempt_count + 1,
            last_attempt_started_at = CURRENT_TIMESTAMP,
            last_attempt_completed_at = NULL,
            error_message = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE moneyline_daily_workflow_run_id = %s;
        """,
        (
            current_stage,
            workflow_run_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Daily Moneyline workflow attempt update "
            "did not affect exactly one row."
        )


def record_moneyline_daily_prediction_run(
    cursor: Any,
    *,
    workflow_run_id: int,
    prediction_run_id: int,
) -> None:
    """
    Persist the completed prediction run selected for this workflow.
    """

    if workflow_run_id <= 0:
        raise ValueError(
            "Daily workflow run ID must be greater than zero."
        )

    if prediction_run_id <= 0:
        raise ValueError(
            "Moneyline prediction run ID must be greater than zero."
        )

    cursor.execute(
        """
        UPDATE moneyline_daily_workflow_runs
        SET moneyline_prediction_run_id = %s,
            current_stage = 'odds_ingestion',
            updated_at = CURRENT_TIMESTAMP
        WHERE moneyline_daily_workflow_run_id = %s;
        """,
        (
            prediction_run_id,
            workflow_run_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Daily Moneyline prediction update "
            "did not affect exactly one row."
        )


def record_moneyline_daily_odds_run(
    cursor: Any,
    *,
    workflow_run_id: int,
    odds_ingestion_run_id: int,
    status_code: int,
    remaining_requests: int | None,
    used_requests: int | None,
) -> None:
    """
    Persist the completed odds run and advance to evaluation.
    """

    if workflow_run_id <= 0:
        raise ValueError(
            "Daily workflow run ID must be greater than zero."
        )

    if odds_ingestion_run_id <= 0:
        raise ValueError(
            "Odds ingestion run ID must be greater than zero."
        )

    if not 100 <= status_code <= 599:
        raise ValueError(
            "Odds HTTP status code must be between 100 and 599."
        )

    if remaining_requests is not None and remaining_requests < 0:
        raise ValueError(
            "Remaining requests cannot be negative."
        )

    if used_requests is not None and used_requests < 0:
        raise ValueError(
            "Used requests cannot be negative."
        )

    cursor.execute(
        """
        UPDATE moneyline_daily_workflow_runs
        SET odds_ingestion_run_id = %s,
            odds_status_code = %s,
            odds_remaining_requests = %s,
            odds_used_requests = %s,
            current_stage = 'evaluation',
            updated_at = CURRENT_TIMESTAMP
        WHERE moneyline_daily_workflow_run_id = %s;
        """,
        (
            odds_ingestion_run_id,
            status_code,
            remaining_requests,
            used_requests,
            workflow_run_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Daily Moneyline odds update "
            "did not affect exactly one row."
        )


def mark_moneyline_daily_workflow_awaiting_results(
    cursor: Any,
    *,
    workflow_run_id: int,
) -> None:
    """
    Mark pregame processing complete and await final game results.
    """

    if workflow_run_id <= 0:
        raise ValueError(
            "Daily workflow run ID must be greater than zero."
        )

    cursor.execute(
        """
        UPDATE moneyline_daily_workflow_runs
        SET status = 'awaiting_results',
            current_stage = 'results_ingestion',
            pregame_completed_at = CURRENT_TIMESTAMP,
            last_attempt_completed_at = CURRENT_TIMESTAMP,
            error_message = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE moneyline_daily_workflow_run_id = %s;
        """,
        (workflow_run_id,),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Daily Moneyline pregame completion update "
            "did not affect exactly one row."
        )
