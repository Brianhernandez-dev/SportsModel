from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sportsmodel.analysis.moneyline_market_evaluation_service import (
    MoneylineMarketEvaluationRunResult,
    evaluate_moneyline_prediction_run,
)
from sportsmodel.database.connection import get_connection
from sportsmodel.ingest.odds_api_parser import (
    ODDS_API_MLB_SPORT_KEY,
)


ConnectionFactory = Callable[[], Any]
EvaluationRunner = Callable[..., MoneylineMarketEvaluationRunResult]


@dataclass(frozen=True)
class MoneylineEarlyEntryCaptureResult:
    """Persisted late-night evaluation of one preview run."""

    target_date: date
    prediction_run_id: int
    odds_ingestion_run_id: int
    evaluations_saved: int
    early_entry_candidates: int
    evaluation_result: MoneylineMarketEvaluationRunResult


def capture_moneyline_early_entry(
    *,
    target_date: date,
    connection_factory: ConnectionFactory = get_connection,
    evaluator: EvaluationRunner = evaluate_moneyline_prediction_run,
) -> MoneylineEarlyEntryCaptureResult:
    """Evaluate the latest preview run against late-night odds."""

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            prediction_run_id = _load_preview_prediction_run_id(
                cursor,
                target_date=target_date,
            )
            odds_ingestion_run_id = _load_late_night_odds_run_id(
                cursor,
                target_date=target_date,
            )
    finally:
        connection.close()

    evaluation_result = evaluator(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
        require_complete_market_coverage=False,
    )

    return MoneylineEarlyEntryCaptureResult(
        target_date=target_date,
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
        evaluations_saved=evaluation_result.evaluations_saved,
        early_entry_candidates=evaluation_result.paper_candidates,
        evaluation_result=evaluation_result,
    )


def _load_preview_prediction_run_id(
    cursor: Any,
    *,
    target_date: date,
) -> int:
    cursor.execute(
        """
        SELECT moneyline_prediction_run_id
        FROM moneyline_prediction_runs
        WHERE
            target_date = %s
            AND run_type = 'preview'
            AND status = 'completed'
        ORDER BY
            completed_at DESC,
            moneyline_prediction_run_id DESC
        LIMIT 1;
        """,
        (target_date,),
    )
    row = cursor.fetchone()

    if row is None:
        raise LookupError(
            "No completed preview prediction run exists "
            f"for {target_date}."
        )

    return row[0]


def _load_late_night_odds_run_id(
    cursor: Any,
    *,
    target_date: date,
) -> int:
    cursor.execute(
        """
        SELECT odds_ingestion_run_id
        FROM odds_ingestion_runs
        WHERE
            target_date = %s
            AND snapshot_role = 'late_night'
            AND status = 'completed'
            AND sport = %s
        ORDER BY odds_ingestion_run_id DESC
        LIMIT 1;
        """,
        (target_date, ODDS_API_MLB_SPORT_KEY),
    )
    row = cursor.fetchone()

    if row is None:
        raise LookupError(
            "No completed late-night odds snapshot exists "
            f"for {target_date}."
        )

    return row[0]
