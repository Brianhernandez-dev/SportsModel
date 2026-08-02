from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sportsmodel.analysis.moneyline_market_evaluation_service import (
    evaluate_moneyline_prediction_run,
)
from sportsmodel.auditing.moneyline_live_pipeline import (
    audit_moneyline_live_pipeline,
)
from sportsmodel.database.connection import get_connection
from sportsmodel.database.moneyline_daily_workflow_repository import (
    advance_moneyline_daily_workflow_stage,
    get_or_create_moneyline_daily_workflow_run,
    mark_moneyline_daily_workflow_awaiting_results,
    mark_moneyline_daily_workflow_completed,
    mark_moneyline_daily_workflow_failed,
    record_moneyline_daily_odds_run,
    record_moneyline_daily_prediction_run,
    start_moneyline_daily_workflow_attempt,
)
from sportsmodel.ingest.mlb_schedule import sync_mlb_schedule
from sportsmodel.ingest.odds_api import fetch_live_odds
from sportsmodel.predictions.moneyline_service import (
    run_moneyline_predictions,
)


DEFAULT_SCHEDULE_DAYS_AHEAD = 7
EXPECTED_PREGAME_PIPELINE_STATE = "awaiting_results"
EXPECTED_FINAL_PIPELINE_STATE = "complete"


ConnectionFactory = Callable[[], Any]
ScheduleSyncer = Callable[..., Any]
PredictionRunner = Callable[..., Any]
OddsFetcher = Callable[[], Any]
EvaluationRunner = Callable[..., Any]
PipelineAuditor = Callable[..., Any]


@dataclass(frozen=True)
class MoneylineDailyPregameResult:
    workflow_run_id: int
    target_date: date
    prediction_run_id: int
    odds_ingestion_run_id: int
    predictions_created: int
    evaluations_saved: int
    paper_candidates: int
    odds_remaining_requests: int | None
    pipeline_state: str


def _get_or_create_workflow(
    *,
    target_date: date,
    connection_factory: ConnectionFactory,
):
    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            workflow = (
                get_or_create_moneyline_daily_workflow_run(
                    cursor,
                    target_date=target_date,
                )
            )

        connection.commit()
        return workflow

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def _update_workflow(
    *,
    connection_factory: ConnectionFactory,
    updater: Callable[..., None],
    **arguments: Any,
) -> None:
    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            updater(
                cursor,
                **arguments,
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def _validate_pregame_audit(
    audit: Any,
) -> None:
    if audit.integrity_issues:
        issues = ", ".join(
            audit.integrity_issues
        )
        raise RuntimeError(
            "Pregame pipeline audit found integrity issues: "
            f"{issues}"
        )

    if (
        audit.evaluated_predictions
        != audit.predictions
    ):
        raise RuntimeError(
            "Pregame audit found unevaluated predictions."
        )

    expected_state = (
        "awaiting_results"
        if audit.settlements < audit.paper_candidates
        else "complete"
    )

    if audit.pipeline_state != expected_state:
        raise RuntimeError(
            "Unexpected pregame pipeline state: "
            f"{audit.pipeline_state}. "
            f"Expected: {expected_state}."
        )


def _build_pregame_result(
    *,
    workflow: Any,
    audit: Any,
) -> MoneylineDailyPregameResult:
    prediction_run_id = (
        workflow.moneyline_prediction_run_id
    )
    odds_ingestion_run_id = (
        workflow.odds_ingestion_run_id
    )

    if prediction_run_id is None:
        raise RuntimeError(
            "Daily workflow has no prediction run ID."
        )

    if odds_ingestion_run_id is None:
        raise RuntimeError(
            "Daily workflow has no odds ingestion run ID."
        )

    return MoneylineDailyPregameResult(
        workflow_run_id=(
            workflow.moneyline_daily_workflow_run_id
        ),
        target_date=workflow.target_date,
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
        predictions_created=audit.predictions,
        evaluations_saved=audit.evaluations,
        paper_candidates=audit.paper_candidates,
        odds_remaining_requests=(
            workflow.odds_remaining_requests
        ),
        pipeline_state=audit.pipeline_state,
    )



def _mark_pregame_terminal_state(
    *,
    workflow_run_id: int,
    audit: Any,
    connection_factory: ConnectionFactory,
) -> None:
    if audit.paper_candidates > 0:
        updater = (
            mark_moneyline_daily_workflow_awaiting_results
        )
    else:
        updater = mark_moneyline_daily_workflow_completed

    _update_workflow(
        connection_factory=connection_factory,
        updater=updater,
        workflow_run_id=workflow_run_id,
    )
