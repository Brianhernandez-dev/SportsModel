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


def _can_reuse_completed_pregame(
    workflow: Any,
) -> bool:
    return (
        workflow.status
        in {
            "awaiting_results",
            "completed",
        }
        and workflow.moneyline_prediction_run_id
        is not None
        and workflow.odds_ingestion_run_id
        is not None
    )


def _determine_pregame_resume_stage(
    workflow: Any,
) -> str:
    if workflow.moneyline_prediction_run_id is None:
        return "schedule_sync"

    if workflow.odds_ingestion_run_id is None:
        return "odds_ingestion"

    return "evaluation"


def _run_schedule_and_prediction(
    *,
    workflow_run_id: int,
    target_date: date,
    schedule_days_ahead: int,
    connection_factory: ConnectionFactory,
    schedule_syncer: ScheduleSyncer,
    prediction_runner: PredictionRunner,
):
    schedule_summary = schedule_syncer(
        start_date=target_date,
        days_ahead=schedule_days_ahead,
    )

    if schedule_summary.dates_failed > 0:
        raise RuntimeError(
            "MLB schedule synchronization reported "
            f"{schedule_summary.dates_failed} failed date(s)."
        )

    _update_workflow(
        connection_factory=connection_factory,
        updater=advance_moneyline_daily_workflow_stage,
        workflow_run_id=workflow_run_id,
        current_stage="prediction",
    )

    prediction_result = prediction_runner(
        target_date=target_date,
    )

    _update_workflow(
        connection_factory=connection_factory,
        updater=record_moneyline_daily_prediction_run,
        workflow_run_id=workflow_run_id,
        prediction_run_id=(
            prediction_result.moneyline_prediction_run_id
        ),
    )

    return prediction_result


def _run_odds_ingestion(
    *,
    workflow_run_id: int,
    connection_factory: ConnectionFactory,
    odds_fetcher: OddsFetcher,
):
    odds_result = odds_fetcher()

    _update_workflow(
        connection_factory=connection_factory,
        updater=record_moneyline_daily_odds_run,
        workflow_run_id=workflow_run_id,
        odds_ingestion_run_id=(
            odds_result.odds_ingestion_run_id
        ),
        status_code=odds_result.status_code,
        remaining_requests=(
            odds_result.remaining_requests
        ),
        used_requests=odds_result.used_requests,
    )

    return odds_result


def _run_market_evaluation(
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    evaluator: EvaluationRunner,
):
    return evaluator(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
    )


def _audit_existing_pregame(
    *,
    workflow: Any,
    pipeline_auditor: PipelineAuditor,
) -> MoneylineDailyPregameResult:
    prediction_run_id = (
        workflow.moneyline_prediction_run_id
    )
    odds_ingestion_run_id = (
        workflow.odds_ingestion_run_id
    )

    if prediction_run_id is None:
        raise RuntimeError(
            "Reusable pregame workflow is missing "
            "its prediction run ID."
        )

    if odds_ingestion_run_id is None:
        raise RuntimeError(
            "Reusable pregame workflow is missing "
            "its odds ingestion run ID."
        )

    audit = pipeline_auditor(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
    )

    _validate_pregame_audit(audit)

    return _build_pregame_result(
        workflow=workflow,
        audit=audit,
    )


def _record_pregame_failure(
    *,
    workflow_run_id: int,
    current_stage: str,
    error: Exception,
    connection_factory: ConnectionFactory,
) -> None:
    try:
        _update_workflow(
            connection_factory=connection_factory,
            updater=mark_moneyline_daily_workflow_failed,
            workflow_run_id=workflow_run_id,
            current_stage=current_stage,
            error_message=str(error),
        )
    except Exception:
        pass
