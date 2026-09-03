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
    mark_moneyline_daily_postgame_pending,
    mark_moneyline_daily_settlement_completed,
    record_moneyline_daily_odds_run,
    record_moneyline_daily_prediction_run,
    start_moneyline_daily_workflow_attempt,
)
from sportsmodel.ingest.mlb_schedule import (
    ScheduleSyncDateSummary,
    ScheduleSyncSummary,
    sync_mlb_schedule,
)
from sportsmodel.ingest.mlb_stats import fetch_historical_results
from sportsmodel.ingest.odds_api import fetch_live_odds
from sportsmodel.predictions.moneyline_service import (
    run_moneyline_predictions,
)
from sportsmodel.settlement.moneyline_paper_service import (
    settle_moneyline_paper_candidate_run,
)
from sportsmodel.settlement.moneyline_early_entry_service import (
    settle_moneyline_early_entry,
)


DEFAULT_SCHEDULE_DAYS_AHEAD = 7
EXPECTED_PREGAME_PIPELINE_STATE = "awaiting_results"
EXPECTED_FINAL_PIPELINE_STATE = "complete"


ConnectionFactory = Callable[[], Any]
ScheduleSyncer = Callable[..., Any]
PredictionRunner = Callable[..., Any]
OddsFetcher = Callable[..., Any]
EvaluationRunner = Callable[..., Any]
PipelineAuditor = Callable[..., Any]
ResultsFetcher = Callable[..., Any]
SettlementRunner = Callable[..., Any]
EarlyEntrySettlementRunner = Callable[..., Any]


@dataclass(frozen=True)
class MoneylineDailyPostgameResult:
    workflow_run_id: int
    target_date: date
    prediction_run_id: int
    odds_ingestion_run_id: int
    games_processed: int
    boxscores_processed: int
    settlements_saved: int
    pending_candidates: int
    pipeline_state: str


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


def _validate_schedule_sync_for_required_dates(
    *,
    schedule_summary: ScheduleSyncSummary,
    required_dates: frozenset[date],
) -> tuple[ScheduleSyncDateSummary, ...]:
    """
    Fail closed for required dates and return ancillary failures.

    Pregame currently requires only its target date. The wider schedule
    horizon preloads canonical games for later workflows and must not make an
    otherwise valid current-date official card depend on an unrelated future
    provider response.
    """

    summaries_by_date = {
        item.schedule_date: item
        for item in schedule_summary.date_summaries
    }
    missing_required_dates = sorted(
        required_dates - summaries_by_date.keys()
    )

    if missing_required_dates:
        raise RuntimeError(
            "MLB schedule synchronization did not report required date(s): "
            + ", ".join(
                item.isoformat()
                for item in missing_required_dates
            )
            + "."
        )

    failed_required_dates = tuple(
        summaries_by_date[item]
        for item in sorted(required_dates)
        if summaries_by_date[item].failed
    )

    if failed_required_dates:
        raise RuntimeError(
            "MLB schedule synchronization failed for required date(s): "
            + _format_schedule_failures(
                failed_required_dates
            )
            + "."
        )

    return tuple(
        item
        for item in schedule_summary.date_summaries
        if item.failed
        and item.schedule_date not in required_dates
    )


def _format_schedule_failures(
    failures: tuple[ScheduleSyncDateSummary, ...],
) -> str:
    return ", ".join(
        f"{item.schedule_date} ({item.error_message})"
        for item in failures
    )


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

    ancillary_failures = (
        _validate_schedule_sync_for_required_dates(
            schedule_summary=schedule_summary,
            required_dates=frozenset({target_date}),
        )
    )

    if ancillary_failures:
        print(
            "WARNING: MLB schedule synchronization was partial; "
            f"required Pregame date {target_date} succeeded. "
            "Continuing despite nonrequired future date failure(s): "
            f"{_format_schedule_failures(ancillary_failures)}."
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
    target_date: date,
    connection_factory: ConnectionFactory,
    odds_fetcher: OddsFetcher,
):
    odds_result = odds_fetcher(
        target_date=target_date,
        snapshot_role="entry",
    )

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


def _start_pregame_attempt(
    *,
    workflow: Any,
    connection_factory: ConnectionFactory,
) -> str:
    current_stage = _determine_pregame_resume_stage(
        workflow
    )

    _update_workflow(
        connection_factory=connection_factory,
        updater=start_moneyline_daily_workflow_attempt,
        workflow_run_id=(
            workflow.moneyline_daily_workflow_run_id
        ),
        current_stage=current_stage,
    )

    return current_stage


def _prepare_pregame_workflow(
    *,
    target_date: date,
    connection_factory: ConnectionFactory,
    pipeline_auditor: PipelineAuditor,
) -> tuple[
    Any,
    MoneylineDailyPregameResult | None,
    str | None,
]:
    workflow = _get_or_create_workflow(
        target_date=target_date,
        connection_factory=connection_factory,
    )

    if _can_reuse_completed_pregame(workflow):
        reused_result = _audit_existing_pregame(
            workflow=workflow,
            pipeline_auditor=pipeline_auditor,
        )
        return workflow, reused_result, None

    current_stage = _start_pregame_attempt(
        workflow=workflow,
        connection_factory=connection_factory,
    )

    return workflow, None, current_stage


def run_moneyline_daily_pregame(
    *,
    target_date: date,
    schedule_days_ahead: int = DEFAULT_SCHEDULE_DAYS_AHEAD,
    connection_factory: ConnectionFactory = get_connection,
    schedule_syncer: ScheduleSyncer = sync_mlb_schedule,
    prediction_runner: PredictionRunner = run_moneyline_predictions,
    odds_fetcher: OddsFetcher = fetch_live_odds,
    evaluator: EvaluationRunner = (
        evaluate_moneyline_prediction_run
    ),
    pipeline_auditor: PipelineAuditor = (
        audit_moneyline_live_pipeline
    ),
) -> MoneylineDailyPregameResult:
    """
    Run or safely resume one MLB Moneyline pregame workflow.
    """

    workflow, reused_result, current_stage = (
        _prepare_pregame_workflow(
            target_date=target_date,
            connection_factory=connection_factory,
            pipeline_auditor=pipeline_auditor,
        )
    )

    if reused_result is not None:
        return reused_result

    workflow_run_id = (
        workflow.moneyline_daily_workflow_run_id
    )
    prediction_run_id = (
        workflow.moneyline_prediction_run_id
    )
    odds_ingestion_run_id = (
        workflow.odds_ingestion_run_id
    )

    try:
        if prediction_run_id is None:
            current_stage = "schedule_sync"

            prediction_result = (
                _run_schedule_and_prediction(
                    workflow_run_id=workflow_run_id,
                    target_date=target_date,
                    schedule_days_ahead=(
                        schedule_days_ahead
                    ),
                    connection_factory=(
                        connection_factory
                    ),
                    schedule_syncer=schedule_syncer,
                    prediction_runner=prediction_runner,
                )
            )

            prediction_run_id = (
                prediction_result
                .moneyline_prediction_run_id
            )

        if odds_ingestion_run_id is None:
            current_stage = "odds_ingestion"

            odds_result = _run_odds_ingestion(
                workflow_run_id=workflow_run_id,
                target_date=target_date,
                connection_factory=connection_factory,
                odds_fetcher=odds_fetcher,
            )

            odds_ingestion_run_id = (
                odds_result.odds_ingestion_run_id
            )

        current_stage = "evaluation"

        _run_market_evaluation(
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=(
                odds_ingestion_run_id
            ),
            evaluator=evaluator,
        )

        current_stage = "pregame_audit"

        _update_workflow(
            connection_factory=connection_factory,
            updater=advance_moneyline_daily_workflow_stage,
            workflow_run_id=workflow_run_id,
            current_stage=current_stage,
        )

        audit = pipeline_auditor(
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=(
                odds_ingestion_run_id
            ),
        )

        _validate_pregame_audit(audit)

        _mark_pregame_terminal_state(
            workflow_run_id=workflow_run_id,
            audit=audit,
            connection_factory=connection_factory,
        )

        refreshed_workflow = _get_or_create_workflow(
            target_date=target_date,
            connection_factory=connection_factory,
        )

        return _build_pregame_result(
            workflow=refreshed_workflow,
            audit=audit,
        )

    except Exception as error:
        failure_stage = current_stage or "initialized"

        try:
            failed_workflow = _get_or_create_workflow(
                target_date=target_date,
                connection_factory=connection_factory,
            )
            failure_stage = failed_workflow.current_stage
        except Exception:
            pass

        _record_pregame_failure(
            workflow_run_id=workflow_run_id,
            current_stage=failure_stage,
            error=error,
            connection_factory=connection_factory,
        )
        raise



def _get_postgame_run_ids(
    workflow: Any,
) -> tuple[int, int]:
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

    return (
        prediction_run_id,
        odds_ingestion_run_id,
    )


def _run_postgame_results_ingestion(
    *,
    workflow_run_id: int,
    target_date: date,
    connection_factory: ConnectionFactory,
    results_fetcher: ResultsFetcher,
):
    results_summary = results_fetcher(
        start_date=target_date,
        end_date=target_date,
    )

    if (
        results_summary.dates_failed > 0
        or results_summary.boxscores_failed > 0
    ):
        raise RuntimeError(
            "MLB results ingestion reported failures: "
            f"dates={results_summary.dates_failed}, "
            f"boxscores={results_summary.boxscores_failed}."
        )

    _update_workflow(
        connection_factory=connection_factory,
        updater=advance_moneyline_daily_workflow_stage,
        workflow_run_id=workflow_run_id,
        current_stage="settlement",
    )

    return results_summary


def _run_postgame_settlement(
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    settlement_runner: SettlementRunner,
):
    return settlement_runner(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
    )



def _mark_postgame_settlement_state(
    *,
    workflow_run_id: int,
    settlement_result: Any,
    early_entry_result: Any,
    connection_factory: ConnectionFactory,
) -> None:
    pending_candidates = (
        settlement_result.report.pending_candidates
        + early_entry_result.performance.pending
    )

    if pending_candidates > 0:
        updater = mark_moneyline_daily_postgame_pending
    else:
        updater = mark_moneyline_daily_settlement_completed

    _update_workflow(
        connection_factory=connection_factory,
        updater=updater,
        workflow_run_id=workflow_run_id,
    )


def _build_postgame_result(
    *,
    workflow: Any,
    results_summary: Any | None,
    audit: Any,
) -> MoneylineDailyPostgameResult:
    prediction_run_id, odds_ingestion_run_id = (
        _get_postgame_run_ids(workflow)
    )

    return MoneylineDailyPostgameResult(
        workflow_run_id=(
            workflow.moneyline_daily_workflow_run_id
        ),
        target_date=workflow.target_date,
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
        games_processed=(
            0
            if results_summary is None
            else results_summary.games_processed
        ),
        boxscores_processed=(
            0
            if results_summary is None
            else results_summary.boxscores_processed
        ),
        settlements_saved=audit.settlements,
        pending_candidates=max(
            audit.paper_candidates - audit.settlements,
            0,
        ),
        pipeline_state=audit.pipeline_state,
    )


def run_moneyline_daily_postgame(
    *,
    target_date: date,
    connection_factory: ConnectionFactory = get_connection,
    results_fetcher: ResultsFetcher = fetch_historical_results,
    settlement_runner: SettlementRunner = (
        settle_moneyline_paper_candidate_run
    ),
    early_entry_settlement_runner: (
        EarlyEntrySettlementRunner
    ) = settle_moneyline_early_entry,
    pipeline_auditor: PipelineAuditor = (
        audit_moneyline_live_pipeline
    ),
) -> MoneylineDailyPostgameResult:
    """
    Run or safely resume one MLB Moneyline postgame workflow.
    """

    workflow = _get_or_create_workflow(
        target_date=target_date,
        connection_factory=connection_factory,
    )

    prediction_run_id, odds_ingestion_run_id = (
        _get_postgame_run_ids(workflow)
    )

    if workflow.status == "completed":
        early_entry_settlement_runner(
            target_date=target_date,
            connection_factory=connection_factory,
        )

        audit = pipeline_auditor(
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=odds_ingestion_run_id,
        )

        _validate_pregame_audit(audit)

        return _build_postgame_result(
            workflow=workflow,
            results_summary=None,
            audit=audit,
        )

    workflow_run_id = (
        workflow.moneyline_daily_workflow_run_id
    )
    current_stage = "results_ingestion"

    try:
        _update_workflow(
            connection_factory=connection_factory,
            updater=start_moneyline_daily_workflow_attempt,
            workflow_run_id=workflow_run_id,
            current_stage=current_stage,
        )

        results_summary = (
            _run_postgame_results_ingestion(
                workflow_run_id=workflow_run_id,
                target_date=target_date,
                connection_factory=connection_factory,
                results_fetcher=results_fetcher,
            )
        )

        current_stage = "settlement"

        settlement_result = _run_postgame_settlement(
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=odds_ingestion_run_id,
            settlement_runner=settlement_runner,
        )

        current_stage = "early_entry_settlement"

        early_entry_result = early_entry_settlement_runner(
            target_date=target_date,
            connection_factory=connection_factory,
        )

        _mark_postgame_settlement_state(
            workflow_run_id=workflow_run_id,
            settlement_result=settlement_result,
            early_entry_result=early_entry_result,
            connection_factory=connection_factory,
        )

        current_stage = (
            "results_ingestion"
            if (
                settlement_result.report.pending_candidates > 0
                or early_entry_result.performance.pending > 0
            )
            else "final_audit"
        )

        audit = pipeline_auditor(
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=odds_ingestion_run_id,
        )

        _validate_pregame_audit(audit)

        if (
            settlement_result.report.pending_candidates == 0
            and early_entry_result.performance.pending == 0
        ):
            _update_workflow(
                connection_factory=connection_factory,
                updater=mark_moneyline_daily_workflow_completed,
                workflow_run_id=workflow_run_id,
            )

        refreshed_workflow = _get_or_create_workflow(
            target_date=target_date,
            connection_factory=connection_factory,
        )

        return _build_postgame_result(
            workflow=refreshed_workflow,
            results_summary=results_summary,
            audit=audit,
        )

    except Exception as error:
        failure_stage = current_stage

        try:
            failed_workflow = _get_or_create_workflow(
                target_date=target_date,
                connection_factory=connection_factory,
            )
            failure_stage = failed_workflow.current_stage
        except Exception:
            pass

        _record_pregame_failure(
            workflow_run_id=workflow_run_id,
            current_stage=failure_stage,
            error=error,
            connection_factory=connection_factory,
        )
        raise
