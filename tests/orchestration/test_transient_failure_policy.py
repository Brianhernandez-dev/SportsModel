from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
import requests

from sportsmodel.ingest.mlb_schedule import ScheduleSyncDateSummary
from sportsmodel.ingest.mlb_stats import (
    HistoricalResultsBackfillSummary,
    HistoricalResultsDateSummary,
)
from sportsmodel.ingest.odds_cli import main as odds_main
from sportsmodel.orchestration import moneyline_daily
from sportsmodel.orchestration.moneyline_daily_cli import main as pregame_main
from sportsmodel.orchestration.moneyline_daily_postgame_cli import (
    main as postgame_main,
)
from sportsmodel.predictions.moneyline_preview_cli import main as preview_main
from sportsmodel.utils.transient_errors import (
    RETRYABLE_EXIT_CODE,
    RetryableOperationalError,
    is_retryable_provider_error,
)


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(response=response)


@pytest.mark.parametrize(
    "error",
    [
        requests.Timeout("provider timeout"),
        requests.ConnectionError("temporary connection failure"),
        _http_error(502),
        _http_error(429),
        RetryableOperationalError("typed transient failure"),
    ],
)
def test_proven_provider_failures_are_retryable(error: BaseException) -> None:
    assert is_retryable_provider_error(error)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("invariant failure"),
        ValueError("invalid configuration"),
        _http_error(401),
        _http_error(404),
    ],
)
def test_ambiguous_or_permanent_failures_are_not_retryable(
    error: BaseException,
) -> None:
    assert not is_retryable_provider_error(error)


@pytest.mark.parametrize(
    "cli",
    [odds_main, pregame_main, postgame_main],
)
def test_operational_clis_emit_retryable_exit_code(cli) -> None:
    def transient_failure(**unused_arguments):
        raise requests.Timeout("provider timeout")

    keyword = {
        odds_main: "odds_fetcher",
        pregame_main: "pregame_runner",
        postgame_main: "postgame_runner",
    }[cli]

    assert cli([], **{keyword: transient_failure}) == RETRYABLE_EXIT_CODE


def test_preview_cli_emits_retryable_exit_code(monkeypatch) -> None:
    monkeypatch.setattr(
        "sportsmodel.predictions.moneyline_preview_cli."
        "run_moneyline_predictions",
        lambda **unused_arguments: (_ for _ in ()).throw(
            requests.Timeout("provider timeout")
        ),
    )

    assert (
        preview_main(["--target-date", "2026-09-03"])
        == RETRYABLE_EXIT_CODE
    )


def test_required_schedule_timeout_is_typed_retryable() -> None:
    summary = SimpleNamespace(
        date_summaries=(
            ScheduleSyncDateSummary(
                schedule_date=date(2026, 9, 2),
                games_received=0,
                games_synchronized=0,
                games_skipped=0,
                error_message="ReadTimeout: provider timeout",
                failure_is_retryable=True,
            ),
        )
    )

    with pytest.raises(RetryableOperationalError):
        moneyline_daily._validate_schedule_sync_for_required_dates(
            schedule_summary=summary,
            required_dates=frozenset({date(2026, 9, 2)}),
        )


def test_required_schedule_invariant_failure_is_permanent() -> None:
    summary = SimpleNamespace(
        date_summaries=(
            ScheduleSyncDateSummary(
                schedule_date=date(2026, 9, 2),
                games_received=0,
                games_synchronized=0,
                games_skipped=0,
                error_message="ValueError: malformed schedule",
            ),
        )
    )

    with pytest.raises(RuntimeError) as error:
        moneyline_daily._validate_schedule_sync_for_required_dates(
            schedule_summary=summary,
            required_dates=frozenset({date(2026, 9, 2)}),
        )

    assert not isinstance(error.value, RetryableOperationalError)


def test_postgame_provider_failure_is_retryable() -> None:
    target_date = date(2026, 9, 1)
    summary = HistoricalResultsBackfillSummary(
        start_date=target_date,
        end_date=target_date,
        date_summaries=(
            HistoricalResultsDateSummary(
                schedule_date=target_date,
                schedule_games_received=0,
                finalized_games_processed=0,
                games_skipped=0,
                boxscores_processed=0,
                boxscores_skipped_complete=0,
                boxscores_failed=0,
                schedule_error="ReadTimeout: provider timeout",
                retryable_failures=1,
            ),
        ),
    )

    with pytest.raises(RetryableOperationalError):
        moneyline_daily._run_postgame_results_ingestion(
            workflow_run_id=12,
            target_date=target_date,
            connection_factory=lambda: None,
            results_fetcher=lambda **unused_arguments: summary,
        )


def test_pregame_retry_reuses_linked_prediction_without_duplicate(
    monkeypatch,
) -> None:
    initial_workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 9, 2),
        moneyline_prediction_run_id=None,
        odds_ingestion_run_id=None,
    )
    resumable_workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 9, 2),
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=None,
    )
    completed_workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 9, 2),
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
        odds_remaining_requests=487,
    )
    prepare_calls = 0
    prediction_calls = 0
    odds_calls = 0

    def prepare(**unused_arguments):
        nonlocal prepare_calls
        prepare_calls += 1
        workflow = initial_workflow if prepare_calls == 1 else resumable_workflow
        return workflow, None, (
            "schedule_sync" if prepare_calls == 1 else "odds_ingestion"
        )

    def run_prediction(**unused_arguments):
        nonlocal prediction_calls
        prediction_calls += 1
        return SimpleNamespace(moneyline_prediction_run_id=25)

    def run_odds(**unused_arguments):
        nonlocal odds_calls
        odds_calls += 1
        if odds_calls == 1:
            raise RetryableOperationalError("provider timeout")
        return SimpleNamespace(odds_ingestion_run_id=182)

    monkeypatch.setattr(moneyline_daily, "_prepare_pregame_workflow", prepare)
    monkeypatch.setattr(
        moneyline_daily,
        "_run_schedule_and_prediction",
        run_prediction,
    )
    monkeypatch.setattr(moneyline_daily, "_run_odds_ingestion", run_odds)
    monkeypatch.setattr(
        moneyline_daily,
        "_run_market_evaluation",
        lambda **unused_arguments: None,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **unused_arguments: None,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_mark_pregame_terminal_state",
        lambda **unused_arguments: None,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_record_pregame_failure",
        lambda **unused_arguments: None,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **unused_arguments: completed_workflow,
    )
    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=10,
        evaluated_predictions=10,
        evaluations=10,
        paper_candidates=2,
        settlements=0,
        pipeline_state="awaiting_results",
    )

    with pytest.raises(RetryableOperationalError):
        moneyline_daily.run_moneyline_daily_pregame(
            target_date=date(2026, 9, 2),
            connection_factory=lambda: None,
            pipeline_auditor=lambda **unused_arguments: audit,
        )

    result = moneyline_daily.run_moneyline_daily_pregame(
        target_date=date(2026, 9, 2),
        connection_factory=lambda: None,
        pipeline_auditor=lambda **unused_arguments: audit,
    )

    assert result.prediction_run_id == 25
    assert result.odds_ingestion_run_id == 182
    assert prediction_calls == 1
    assert odds_calls == 2
