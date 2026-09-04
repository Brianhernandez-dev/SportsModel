from datetime import date
from dataclasses import dataclass
from typing import Any

from sportsmodel.models.moneyline_daily_workflow import (
    MoneylineDailyWorkflowRun,
)


@dataclass(frozen=True)
class MoneylineDailyOfficialEvidenceCounts:
    prediction_runs: int
    entry_odds_runs: int


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


def load_moneyline_daily_official_evidence_counts(
    cursor: Any,
    *,
    target_date: date,
    sport: str,
) -> MoneylineDailyOfficialEvidenceCounts:
    """Count independently persisted official evidence for one date."""

    cursor.execute(
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM moneyline_prediction_runs
                WHERE target_date = %s
                  AND run_type = 'official'
            ),
            (
                SELECT COUNT(*)
                FROM odds_ingestion_runs
                WHERE target_date = %s
                  AND snapshot_role = 'entry'
                  AND sport = %s
            );
        """,
        (
            target_date,
            target_date,
            sport,
        ),
    )
    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Official Moneyline evidence count query returned no row."
        )

    return MoneylineDailyOfficialEvidenceCounts(
        prediction_runs=row[0],
        entry_odds_runs=row[1],
    )


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


def mark_moneyline_daily_workflow_failed(
    cursor: Any,
    *,
    workflow_run_id: int,
    current_stage: str,
    error_message: str,
) -> None:
    """
    Record a failed workflow attempt while preserving completed run IDs.
    """

    if workflow_run_id <= 0:
        raise ValueError(
            "Daily workflow run ID must be greater than zero."
        )

    normalized_error = error_message.strip()

    if not normalized_error:
        raise ValueError(
            "Workflow error message cannot be empty."
        )

    cursor.execute(
        """
        UPDATE moneyline_daily_workflow_runs
        SET status = 'failed',
            current_stage = %s,
            last_attempt_completed_at = CURRENT_TIMESTAMP,
            error_message = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE moneyline_daily_workflow_run_id = %s;
        """,
        (
            current_stage,
            normalized_error,
            workflow_run_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Daily Moneyline failure update "
            "did not affect exactly one row."
        )


def advance_moneyline_daily_workflow_stage(
    cursor: Any,
    *,
    workflow_run_id: int,
    current_stage: str,
) -> None:
    """
    Record the workflow stage currently being executed.
    """

    if workflow_run_id <= 0:
        raise ValueError(
            "Daily workflow run ID must be greater than zero."
        )

    cursor.execute(
        """
        UPDATE moneyline_daily_workflow_runs
        SET current_stage = %s,
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
            "Daily Moneyline stage update "
            "did not affect exactly one row."
        )


def mark_moneyline_daily_settlement_completed(
    cursor: Any,
    *,
    workflow_run_id: int,
) -> None:
    """
    Record settlement completion and advance to the final audit.
    """

    if workflow_run_id <= 0:
        raise ValueError(
            "Daily workflow run ID must be greater than zero."
        )

    cursor.execute(
        """
        UPDATE moneyline_daily_workflow_runs
        SET current_stage = 'final_audit',
            settlement_completed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE moneyline_daily_workflow_run_id = %s;
        """,
        (workflow_run_id,),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Daily Moneyline settlement update "
            "did not affect exactly one row."
        )


def mark_moneyline_daily_workflow_completed(
    cursor: Any,
    *,
    workflow_run_id: int,
) -> None:
    """
    Mark the daily prediction-to-settlement workflow complete.
    """

    if workflow_run_id <= 0:
        raise ValueError(
            "Daily workflow run ID must be greater than zero."
        )

    cursor.execute(
        """
        UPDATE moneyline_daily_workflow_runs
        SET status = 'completed',
            current_stage = 'complete',
            last_attempt_completed_at = CURRENT_TIMESTAMP,
            error_message = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE moneyline_daily_workflow_run_id = %s;
        """,
        (workflow_run_id,),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Daily Moneyline completion update "
            "did not affect exactly one row."
        )


def mark_moneyline_daily_postgame_pending(
    cursor: Any,
    *,
    workflow_run_id: int,
) -> None:
    """
    Return an incomplete postgame attempt to results ingestion.
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
            last_attempt_completed_at = CURRENT_TIMESTAMP,
            error_message = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE moneyline_daily_workflow_run_id = %s;
        """,
        (workflow_run_id,),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Daily Moneyline postgame pending update "
            "did not affect exactly one row."
        )
