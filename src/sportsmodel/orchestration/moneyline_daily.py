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
