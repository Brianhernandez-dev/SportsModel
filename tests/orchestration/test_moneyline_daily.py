from datetime import date
from types import SimpleNamespace

import pytest

from sportsmodel.ingest.mlb_schedule import (
    ScheduleSyncDateSummary,
    ScheduleSyncSummary,
)
from sportsmodel.orchestration import moneyline_daily


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def _schedule_summary(
    *date_summaries: ScheduleSyncDateSummary,
) -> ScheduleSyncSummary:
    schedule_dates = tuple(
        item.schedule_date
        for item in date_summaries
    )

    return ScheduleSyncSummary(
        start_date=min(schedule_dates),
        end_date=max(schedule_dates),
        date_summaries=date_summaries,
    )


def test_gets_or_creates_workflow_transactionally(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    expected = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "get_or_create_moneyline_daily_workflow_run",
        lambda cursor, target_date: expected,
    )

    result = moneyline_daily._get_or_create_workflow(
        target_date=date(2026, 8, 2),
        connection_factory=lambda: connection,
    )

    assert result is expected
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_updates_workflow_transactionally() -> None:
    connection = FakeConnection()
    calls = []

    def updater(cursor, *, workflow_run_id) -> None:
        calls.append((cursor, workflow_run_id))

    moneyline_daily._update_workflow(
        connection_factory=lambda: connection,
        updater=updater,
        workflow_run_id=12,
    )

    assert calls == [(connection.cursor_instance, 12)]
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_update_rolls_back_on_failure() -> None:
    connection = FakeConnection()

    def failing_updater(cursor, **arguments) -> None:
        raise RuntimeError("update failed")

    with pytest.raises(RuntimeError, match="update failed"):
        moneyline_daily._update_workflow(
            connection_factory=lambda: connection,
            updater=failing_updater,
            workflow_run_id=12,
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed is True


def test_accepts_pregame_audit_awaiting_results() -> None:
    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=10,
        evaluated_predictions=10,
        paper_candidates=5,
        settlements=0,
        pipeline_state="awaiting_results",
    )

    moneyline_daily._validate_pregame_audit(audit)


def test_accepts_complete_zero_candidate_slate() -> None:
    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=10,
        evaluated_predictions=10,
        paper_candidates=0,
        settlements=0,
        pipeline_state="complete",
    )

    moneyline_daily._validate_pregame_audit(audit)


def test_rejects_pregame_integrity_issues() -> None:
    audit = SimpleNamespace(
        integrity_issues=("duplicate_evaluations",),
        predictions=10,
        evaluated_predictions=10,
        paper_candidates=5,
        settlements=0,
        pipeline_state="invalid",
    )

    with pytest.raises(
        RuntimeError,
        match="duplicate_evaluations",
    ):
        moneyline_daily._validate_pregame_audit(audit)


def test_rejects_unexpected_pregame_state() -> None:
    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=10,
        evaluated_predictions=10,
        paper_candidates=5,
        settlements=0,
        pipeline_state="complete",
    )

    with pytest.raises(
        RuntimeError,
        match="Unexpected pregame pipeline state",
    ):
        moneyline_daily._validate_pregame_audit(audit)


def test_builds_pregame_result_from_existing_workflow() -> None:
    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 2),
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
        odds_remaining_requests=487,
    )

    audit = SimpleNamespace(
        predictions=10,
        evaluations=10,
        paper_candidates=5,
        pipeline_state="awaiting_results",
    )

    result = moneyline_daily._build_pregame_result(
        workflow=workflow,
        audit=audit,
    )

    assert result == moneyline_daily.MoneylineDailyPregameResult(
        workflow_run_id=12,
        target_date=date(2026, 8, 2),
        prediction_run_id=25,
        odds_ingestion_run_id=182,
        predictions_created=10,
        evaluations_saved=10,
        paper_candidates=5,
        odds_remaining_requests=487,
        pipeline_state="awaiting_results",
    )


def test_build_pregame_result_requires_run_ids() -> None:
    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 2),
        moneyline_prediction_run_id=None,
        odds_ingestion_run_id=None,
        odds_remaining_requests=None,
    )

    audit = SimpleNamespace(
        predictions=0,
        evaluations=0,
        paper_candidates=0,
        pipeline_state="complete",
    )

    with pytest.raises(
        RuntimeError,
        match="no prediction run ID",
    ):
        moneyline_daily._build_pregame_result(
            workflow=workflow,
            audit=audit,
        )


def test_marks_candidate_slate_awaiting_results(
    monkeypatch,
) -> None:
    calls = []

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: calls.append(arguments),
    )

    moneyline_daily._mark_pregame_terminal_state(
        workflow_run_id=12,
        audit=SimpleNamespace(paper_candidates=5),
        connection_factory=lambda: None,
    )

    assert calls[0]["updater"] is (
        moneyline_daily
        .mark_moneyline_daily_workflow_awaiting_results
    )


def test_marks_zero_candidate_slate_completed(
    monkeypatch,
) -> None:
    calls = []

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: calls.append(arguments),
    )

    moneyline_daily._mark_pregame_terminal_state(
        workflow_run_id=12,
        audit=SimpleNamespace(paper_candidates=0),
        connection_factory=lambda: None,
    )

    assert calls[0]["updater"] is (
        moneyline_daily
        .mark_moneyline_daily_workflow_completed
    )


def test_can_reuse_completed_pregame() -> None:
    workflow = SimpleNamespace(
        status="awaiting_results",
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
    )

    assert (
        moneyline_daily
        ._can_reuse_completed_pregame(workflow)
        is True
    )


def test_cannot_reuse_incomplete_pregame() -> None:
    workflow = SimpleNamespace(
        status="failed",
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=None,
    )

    assert (
        moneyline_daily
        ._can_reuse_completed_pregame(workflow)
        is False
    )


@pytest.mark.parametrize(
    (
        "prediction_run_id",
        "odds_run_id",
        "expected_stage",
    ),
    [
        (None, None, "schedule_sync"),
        (25, None, "odds_ingestion"),
        (25, 182, "evaluation"),
    ],
)
def test_determines_pregame_resume_stage(
    prediction_run_id,
    odds_run_id,
    expected_stage,
) -> None:
    workflow = SimpleNamespace(
        moneyline_prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_run_id,
    )

    assert (
        moneyline_daily
        ._determine_pregame_resume_stage(workflow)
        == expected_stage
    )


def test_runs_schedule_and_prediction(
    monkeypatch,
) -> None:
    updates = []
    prediction_result = SimpleNamespace(
        moneyline_prediction_run_id=25,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: updates.append(arguments),
    )

    result = moneyline_daily._run_schedule_and_prediction(
        workflow_run_id=12,
        target_date=date(2026, 8, 2),
        schedule_days_ahead=7,
        connection_factory=lambda: None,
        schedule_syncer=lambda **arguments: _schedule_summary(
            ScheduleSyncDateSummary(
                schedule_date=date(2026, 8, 2),
                games_received=15,
                games_synchronized=15,
                games_skipped=0,
            ),
        ),
        prediction_runner=lambda **arguments: prediction_result,
    )

    assert result is prediction_result
    assert updates[0]["current_stage"] == "prediction"
    assert updates[1]["prediction_run_id"] == 25


def test_stops_when_required_schedule_date_fails() -> None:
    prediction_calls = []

    with pytest.raises(
        RuntimeError,
        match=(
            "failed for required date.*2026-08-02.*"
            "ReadTimeout: target timeout"
        ),
    ):
        moneyline_daily._run_schedule_and_prediction(
            workflow_run_id=12,
            target_date=date(2026, 8, 2),
            schedule_days_ahead=7,
            connection_factory=lambda: None,
            schedule_syncer=lambda **arguments: _schedule_summary(
                ScheduleSyncDateSummary(
                    schedule_date=date(2026, 8, 2),
                    games_received=0,
                    games_synchronized=0,
                    games_skipped=0,
                    error_message=(
                        "ReadTimeout: target timeout"
                    ),
                ),
            ),
            prediction_runner=lambda **arguments: (
                prediction_calls.append(arguments)
            ),
        )

    assert prediction_calls == []


def test_continues_after_nonrequired_future_schedule_failure(
    monkeypatch,
    capsys,
) -> None:
    updates = []
    prediction_calls = []
    prediction_result = SimpleNamespace(
        moneyline_prediction_run_id=25,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: updates.append(arguments),
    )

    result = moneyline_daily._run_schedule_and_prediction(
        workflow_run_id=12,
        target_date=date(2026, 8, 2),
        schedule_days_ahead=7,
        connection_factory=lambda: None,
        schedule_syncer=lambda **arguments: _schedule_summary(
            ScheduleSyncDateSummary(
                schedule_date=date(2026, 8, 2),
                games_received=15,
                games_synchronized=15,
                games_skipped=0,
            ),
            ScheduleSyncDateSummary(
                schedule_date=date(2026, 8, 8),
                games_received=0,
                games_synchronized=0,
                games_skipped=0,
                error_message="ReadTimeout: future timeout",
            ),
        ),
        prediction_runner=lambda **arguments: (
            prediction_calls.append(arguments)
            or prediction_result
        ),
    )

    output = capsys.readouterr().out
    assert result is prediction_result
    assert prediction_calls == [
        {"target_date": date(2026, 8, 2)}
    ]
    assert updates[0]["current_stage"] == "prediction"
    assert "schedule synchronization was partial" in output
    assert "required Pregame date 2026-08-02 succeeded" in output
    assert "2026-08-08 (ReadTimeout: future timeout)" in output


def test_stops_when_explicitly_required_future_date_fails() -> None:
    target_date = date(2026, 8, 2)
    required_future_date = date(2026, 8, 3)
    summary = _schedule_summary(
        ScheduleSyncDateSummary(
            schedule_date=target_date,
            games_received=15,
            games_synchronized=15,
            games_skipped=0,
        ),
        ScheduleSyncDateSummary(
            schedule_date=required_future_date,
            games_received=0,
            games_synchronized=0,
            games_skipped=0,
            error_message="ReadTimeout: required future timeout",
        ),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "failed for required date.*2026-08-03.*"
            "required future timeout"
        ),
    ):
        moneyline_daily._validate_schedule_sync_for_required_dates(
            schedule_summary=summary,
            required_dates=frozenset(
                {target_date, required_future_date}
            ),
        )


def test_stops_when_required_schedule_date_is_not_reported() -> None:
    with pytest.raises(
        RuntimeError,
        match="did not report required date.*2026-08-02",
    ):
        moneyline_daily._validate_schedule_sync_for_required_dates(
            schedule_summary=_schedule_summary(
                ScheduleSyncDateSummary(
                    schedule_date=date(2026, 8, 3),
                    games_received=9,
                    games_synchronized=9,
                    games_skipped=0,
                ),
            ),
            required_dates=frozenset({date(2026, 8, 2)}),
        )


def test_runs_odds_ingestion_and_persists_quota(
    monkeypatch,
) -> None:
    updates = []
    fetch_calls = []

    odds_result = SimpleNamespace(
        odds_ingestion_run_id=182,
        status_code=200,
        remaining_requests=487,
        used_requests=13,
    )

    def fake_odds_fetcher(**arguments):
        fetch_calls.append(arguments)
        return odds_result

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: updates.append(arguments),
    )

    result = moneyline_daily._run_odds_ingestion(
        workflow_run_id=12,
        target_date=date(2026, 8, 2),
        connection_factory=lambda: None,
        odds_fetcher=fake_odds_fetcher,
    )

    assert result is odds_result

    assert fetch_calls == [
        {
            "target_date": date(2026, 8, 2),
            "snapshot_role": "entry",
        }
    ]

    assert updates[0]["odds_ingestion_run_id"] == 182
    assert updates[0]["status_code"] == 200
    assert updates[0]["remaining_requests"] == 487
    assert updates[0]["used_requests"] == 13


def test_runs_market_evaluation_with_both_run_ids() -> None:
    calls = []
    evaluation_result = SimpleNamespace(
        evaluations_saved=10,
        paper_candidates=5,
    )

    def evaluator(**arguments):
        calls.append(arguments)
        return evaluation_result

    result = moneyline_daily._run_market_evaluation(
        prediction_run_id=25,
        odds_ingestion_run_id=182,
        evaluator=evaluator,
    )

    assert result is evaluation_result
    assert calls == [
        {
            "prediction_run_id": 25,
            "odds_ingestion_run_id": 182,
        }
    ]


def test_audits_and_reuses_existing_pregame() -> None:
    calls = []

    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 2),
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
        odds_remaining_requests=487,
    )

    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=10,
        evaluated_predictions=10,
        evaluations=10,
        paper_candidates=5,
        settlements=0,
        pipeline_state="awaiting_results",
    )

    def pipeline_auditor(**arguments):
        calls.append(arguments)
        return audit

    result = moneyline_daily._audit_existing_pregame(
        workflow=workflow,
        pipeline_auditor=pipeline_auditor,
    )

    assert calls == [
        {
            "prediction_run_id": 25,
            "odds_ingestion_run_id": 182,
        }
    ]
    assert result.workflow_run_id == 12
    assert result.prediction_run_id == 25
    assert result.odds_ingestion_run_id == 182
    assert result.predictions_created == 10
    assert result.evaluations_saved == 10
    assert result.paper_candidates == 5
    assert result.odds_remaining_requests == 487
    assert result.pipeline_state == "awaiting_results"


def test_records_pregame_failure(
    monkeypatch,
) -> None:
    updates = []

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: updates.append(arguments),
    )

    moneyline_daily._record_pregame_failure(
        workflow_run_id=12,
        current_stage="odds_ingestion",
        error=RuntimeError("Odds provider unavailable."),
        connection_factory=lambda: None,
    )

    assert updates[0]["workflow_run_id"] == 12
    assert updates[0]["current_stage"] == "odds_ingestion"
    assert (
        updates[0]["error_message"]
        == "Odds provider unavailable."
    )
    assert (
        updates[0]["updater"]
        is moneyline_daily.mark_moneyline_daily_workflow_failed
    )


def test_failure_recording_does_not_mask_original_error(
    monkeypatch,
) -> None:
    def failing_update(**arguments):
        raise RuntimeError("Database unavailable.")

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        failing_update,
    )

    moneyline_daily._record_pregame_failure(
        workflow_run_id=12,
        current_stage="prediction",
        error=RuntimeError("Prediction failed."),
        connection_factory=lambda: None,
    )


def test_starts_pregame_attempt_at_resume_stage(
    monkeypatch,
) -> None:
    updates = []

    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=None,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: updates.append(arguments),
    )

    stage = moneyline_daily._start_pregame_attempt(
        workflow=workflow,
        connection_factory=lambda: None,
    )

    assert stage == "odds_ingestion"
    assert updates[0]["workflow_run_id"] == 12
    assert updates[0]["current_stage"] == "odds_ingestion"
    assert (
        updates[0]["updater"]
        is moneyline_daily.start_moneyline_daily_workflow_attempt
    )


def test_prepares_reusable_pregame_workflow(
    monkeypatch,
) -> None:
    workflow = SimpleNamespace(
        status="awaiting_results",
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
    )
    reused_result = SimpleNamespace(
        workflow_run_id=12,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: workflow,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_audit_existing_pregame",
        lambda **arguments: reused_result,
    )

    def unexpected_start(**arguments):
        raise AssertionError(
            "Reusable workflow should not start another attempt."
        )

    monkeypatch.setattr(
        moneyline_daily,
        "_start_pregame_attempt",
        unexpected_start,
    )

    result = moneyline_daily._prepare_pregame_workflow(
        target_date=date(2026, 8, 2),
        connection_factory=lambda: None,
        pipeline_auditor=lambda **arguments: None,
    )

    assert result == (
        workflow,
        reused_result,
        None,
    )


def test_prepares_resumable_pregame_attempt(
    monkeypatch,
) -> None:
    workflow = SimpleNamespace(
        status="failed",
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=None,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: workflow,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_start_pregame_attempt",
        lambda **arguments: "odds_ingestion",
    )

    def unexpected_audit(**arguments):
        raise AssertionError(
            "Incomplete workflow should not be reused."
        )

    monkeypatch.setattr(
        moneyline_daily,
        "_audit_existing_pregame",
        unexpected_audit,
    )

    result = moneyline_daily._prepare_pregame_workflow(
        target_date=date(2026, 8, 2),
        connection_factory=lambda: None,
        pipeline_auditor=lambda **arguments: None,
    )

    assert result == (
        workflow,
        None,
        "odds_ingestion",
    )


def test_runs_complete_fresh_pregame_workflow(
    monkeypatch,
) -> None:
    calls = []
    initial_workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 2),
        moneyline_prediction_run_id=None,
        odds_ingestion_run_id=None,
    )
    refreshed_workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 2),
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
        odds_remaining_requests=487,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_prepare_pregame_workflow",
        lambda **arguments: (
            initial_workflow,
            None,
            "schedule_sync",
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_schedule_and_prediction",
        lambda **arguments: SimpleNamespace(
            moneyline_prediction_run_id=25,
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_odds_ingestion",
        lambda **arguments: SimpleNamespace(
            odds_ingestion_run_id=182,
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_market_evaluation",
        lambda **arguments: calls.append(
            ("evaluation", arguments)
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: calls.append(
            ("update", arguments)
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_mark_pregame_terminal_state",
        lambda **arguments: calls.append(
            ("terminal", arguments)
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: refreshed_workflow,
    )

    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=10,
        evaluated_predictions=10,
        evaluations=10,
        paper_candidates=5,
        settlements=0,
        pipeline_state="awaiting_results",
    )

    result = moneyline_daily.run_moneyline_daily_pregame(
        target_date=date(2026, 8, 2),
        connection_factory=lambda: None,
        schedule_syncer=lambda **arguments: None,
        prediction_runner=lambda **arguments: None,
        odds_fetcher=lambda: None,
        evaluator=lambda **arguments: None,
        pipeline_auditor=lambda **arguments: audit,
    )

    assert result.workflow_run_id == 12
    assert result.prediction_run_id == 25
    assert result.odds_ingestion_run_id == 182
    assert result.predictions_created == 10
    assert result.evaluations_saved == 10
    assert result.paper_candidates == 5
    assert result.odds_remaining_requests == 487
    assert result.pipeline_state == "awaiting_results"

    assert calls[0][0] == "evaluation"
    assert calls[0][1]["prediction_run_id"] == 25
    assert calls[0][1]["odds_ingestion_run_id"] == 182


def test_resumes_pregame_after_prediction(
    monkeypatch,
) -> None:
    calls = []

    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 2),
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=None,
    )
    refreshed_workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 2),
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
        odds_remaining_requests=487,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_prepare_pregame_workflow",
        lambda **arguments: (
            workflow,
            None,
            "odds_ingestion",
        ),
    )

    def unexpected_prediction(**arguments):
        raise AssertionError(
            "Existing prediction run should be reused."
        )

    monkeypatch.setattr(
        moneyline_daily,
        "_run_schedule_and_prediction",
        unexpected_prediction,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_odds_ingestion",
        lambda **arguments: SimpleNamespace(
            odds_ingestion_run_id=182,
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_market_evaluation",
        lambda **arguments: calls.append(arguments),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: None,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_mark_pregame_terminal_state",
        lambda **arguments: None,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: refreshed_workflow,
    )

    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=10,
        evaluated_predictions=10,
        evaluations=10,
        paper_candidates=5,
        settlements=0,
        pipeline_state="awaiting_results",
    )

    result = moneyline_daily.run_moneyline_daily_pregame(
        target_date=date(2026, 8, 2),
        connection_factory=lambda: None,
        pipeline_auditor=lambda **arguments: audit,
    )

    assert result.prediction_run_id == 25
    assert result.odds_ingestion_run_id == 182
    assert calls[0]["prediction_run_id"] == 25
    assert calls[0]["odds_ingestion_run_id"] == 182


def test_resumes_pregame_at_evaluation(
    monkeypatch,
) -> None:
    evaluation_calls = []

    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 2),
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
    )
    refreshed_workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 2),
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
        odds_remaining_requests=487,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_prepare_pregame_workflow",
        lambda **arguments: (
            workflow,
            None,
            "evaluation",
        ),
    )

    def unexpected_prediction(**arguments):
        raise AssertionError(
            "Existing prediction run should be reused."
        )

    def unexpected_odds(**arguments):
        raise AssertionError(
            "Existing odds run should be reused."
        )

    monkeypatch.setattr(
        moneyline_daily,
        "_run_schedule_and_prediction",
        unexpected_prediction,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_odds_ingestion",
        unexpected_odds,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_market_evaluation",
        lambda **arguments: evaluation_calls.append(
            arguments
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: None,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_mark_pregame_terminal_state",
        lambda **arguments: None,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: refreshed_workflow,
    )

    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=10,
        evaluated_predictions=10,
        evaluations=10,
        paper_candidates=5,
        settlements=0,
        pipeline_state="awaiting_results",
    )

    result = moneyline_daily.run_moneyline_daily_pregame(
        target_date=date(2026, 8, 2),
        connection_factory=lambda: None,
        pipeline_auditor=lambda **arguments: audit,
    )

    assert result.prediction_run_id == 25
    assert result.odds_ingestion_run_id == 182
    assert evaluation_calls == [
        {
            "prediction_run_id": 25,
            "odds_ingestion_run_id": 182,
            "evaluator": (
                moneyline_daily
                .evaluate_moneyline_prediction_run
            ),
        }
    ]


def test_pregame_runner_records_failure_and_reraises(
    monkeypatch,
) -> None:
    recorded_failures = []

    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 2),
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
    )
    failed_workflow = SimpleNamespace(
        current_stage="evaluation",
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_prepare_pregame_workflow",
        lambda **arguments: (
            workflow,
            None,
            "evaluation",
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_market_evaluation",
        lambda **arguments: (
            (_ for _ in ()).throw(
                RuntimeError("Evaluation failed.")
            )
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: failed_workflow,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_record_pregame_failure",
        lambda **arguments: recorded_failures.append(
            arguments
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="Evaluation failed",
    ):
        moneyline_daily.run_moneyline_daily_pregame(
            target_date=date(2026, 8, 2),
            connection_factory=lambda: None,
        )

    assert len(recorded_failures) == 1
    assert recorded_failures[0]["workflow_run_id"] == 12
    assert recorded_failures[0]["current_stage"] == "evaluation"
    assert str(recorded_failures[0]["error"]) == (
        "Evaluation failed."
    )


def test_pregame_runner_reuses_completed_workflow(
    monkeypatch,
) -> None:
    reused_result = moneyline_daily.MoneylineDailyPregameResult(
        workflow_run_id=12,
        target_date=date(2026, 8, 2),
        prediction_run_id=25,
        odds_ingestion_run_id=182,
        predictions_created=10,
        evaluations_saved=10,
        paper_candidates=5,
        odds_remaining_requests=487,
        pipeline_state="awaiting_results",
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_prepare_pregame_workflow",
        lambda **arguments: (
            SimpleNamespace(),
            reused_result,
            None,
        ),
    )

    def unexpected_call(*args, **kwargs):
        raise AssertionError(
            "Reusable workflow should perform no new pipeline work."
        )

    monkeypatch.setattr(
        moneyline_daily,
        "_run_schedule_and_prediction",
        unexpected_call,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_odds_ingestion",
        unexpected_call,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_market_evaluation",
        unexpected_call,
    )

    result = moneyline_daily.run_moneyline_daily_pregame(
        target_date=date(2026, 8, 2),
        connection_factory=lambda: None,
    )

    assert result is reused_result


def test_gets_postgame_run_ids() -> None:
    workflow = SimpleNamespace(
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
    )

    assert moneyline_daily._get_postgame_run_ids(
        workflow
    ) == (25, 182)


@pytest.mark.parametrize(
    (
        "prediction_run_id",
        "odds_run_id",
        "expected_message",
    ),
    [
        (
            None,
            182,
            "no prediction run ID",
        ),
        (
            25,
            None,
            "no odds ingestion run ID",
        ),
    ],
)
def test_rejects_missing_postgame_run_ids(
    prediction_run_id,
    odds_run_id,
    expected_message,
) -> None:
    workflow = SimpleNamespace(
        moneyline_prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_run_id,
    )

    with pytest.raises(
        RuntimeError,
        match=expected_message,
    ):
        moneyline_daily._get_postgame_run_ids(
            workflow
        )


def _no_card_workflow(**overrides):
    values = {
        "moneyline_daily_workflow_run_id": 148,
        "target_date": date(2026, 9, 2),
        "status": "failed",
        "current_stage": "schedule_sync",
        "moneyline_prediction_run_id": None,
        "odds_ingestion_run_id": None,
        "pregame_completed_at": None,
        "error_message": "Required schedule synchronization failed.",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _no_official_evidence(**overrides):
    values = {
        "prediction_runs": 0,
        "entry_odds_runs": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_postgame_completes_legitimate_no_card_day(
    monkeypatch,
    capsys,
) -> None:
    calls = []
    summary = SimpleNamespace(
        dates_failed=0,
        boxscores_failed=0,
        games_processed=12,
        boxscores_processed=12,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: _no_card_workflow(),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_load_postgame_official_evidence_counts",
        lambda **arguments: _no_official_evidence(),
    )

    def unexpected_official_call(**arguments):
        raise AssertionError("Official settlement/audit must not run.")

    result = moneyline_daily.run_moneyline_daily_postgame(
        target_date=date(2026, 9, 2),
        connection_factory=lambda: None,
        results_fetcher=lambda **arguments: (
            calls.append(("results", arguments)) or summary
        ),
        settlement_runner=unexpected_official_call,
        early_entry_settlement_runner=lambda **arguments: (
            calls.append(("early_entry", arguments))
            or SimpleNamespace(
                cohort_settlements=(),
                performance=SimpleNamespace(pending=0),
            )
        ),
        pipeline_auditor=unexpected_official_call,
    )

    assert [item[0] for item in calls] == ["results", "early_entry"]
    assert calls[0][1] == {
        "start_date": date(2026, 9, 2),
        "end_date": date(2026, 9, 2),
    }
    assert result.prediction_run_id is None
    assert result.odds_ingestion_run_id is None
    assert result.games_processed == 12
    assert result.boxscores_processed == 12
    assert result.settlements_saved == 0
    assert result.pending_candidates == 0
    assert result.pipeline_state == "no_official_card"

    output = capsys.readouterr().out
    assert "completed without an official card" in output
    assert "official candidate settlement was skipped" in output
    assert "Early Entry evidence was reconciled independently" in output


@pytest.mark.parametrize(
    ("workflow_overrides", "evidence_overrides"),
    [
        ({"status": "awaiting_results"}, {}),
        ({"current_stage": "odds_ingestion"}, {}),
        ({}, {"prediction_runs": 1}),
        ({}, {"entry_odds_runs": 1}),
    ],
)
def test_postgame_rejects_unexpected_missing_official_linkage(
    monkeypatch,
    workflow_overrides,
    evidence_overrides,
) -> None:
    results_calls = []
    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: _no_card_workflow(**workflow_overrides),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_load_postgame_official_evidence_counts",
        lambda **arguments: _no_official_evidence(**evidence_overrides),
    )

    with pytest.raises(
        RuntimeError,
        match="outside the legitimate no-card state",
    ):
        moneyline_daily.run_moneyline_daily_postgame(
            target_date=date(2026, 9, 2),
            connection_factory=lambda: None,
            results_fetcher=lambda **arguments: results_calls.append(
                arguments
            ),
        )

    assert results_calls == []


def test_repeated_no_card_postgame_remains_idempotent(
    monkeypatch,
) -> None:
    persisted_results = set()
    persisted_early_entry_settlements = set()
    official_settlement_calls = []

    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: _no_card_workflow(),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_load_postgame_official_evidence_counts",
        lambda **arguments: _no_official_evidence(),
    )

    def ingest_results(**arguments):
        persisted_results.add((arguments["start_date"], 1))
        return SimpleNamespace(
            dates_failed=0,
            boxscores_failed=0,
            games_processed=1,
            boxscores_processed=1,
        )

    def settle_early_entry(**arguments):
        persisted_early_entry_settlements.add(
            (arguments["target_date"], 77)
        )
        return SimpleNamespace(
            cohort_settlements=(),
            performance=SimpleNamespace(pending=0),
        )

    def settle_official(**arguments):
        official_settlement_calls.append(arguments)
        raise AssertionError("No official candidate settlement is valid.")

    results = [
        moneyline_daily.run_moneyline_daily_postgame(
            target_date=date(2026, 9, 2),
            connection_factory=lambda: None,
            results_fetcher=ingest_results,
            settlement_runner=settle_official,
            early_entry_settlement_runner=settle_early_entry,
        )
        for _ in range(2)
    ]

    assert persisted_results == {(date(2026, 9, 2), 1)}
    assert persisted_early_entry_settlements == {
        (date(2026, 9, 2), 77)
    }
    assert official_settlement_calls == []
    assert [result.pipeline_state for result in results] == [
        "no_official_card",
        "no_official_card",
    ]


def test_runs_postgame_results_ingestion(
    monkeypatch,
) -> None:
    calls = []
    summary = SimpleNamespace(
        dates_failed=0,
        boxscores_failed=0,
        games_processed=8,
        boxscores_processed=8,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: calls.append(arguments),
    )

    result = (
        moneyline_daily
        ._run_postgame_results_ingestion(
            workflow_run_id=12,
            target_date=date(2026, 8, 3),
            connection_factory=lambda: None,
            results_fetcher=lambda **arguments: summary,
        )
    )

    assert result is summary
    assert calls[0]["workflow_run_id"] == 12
    assert calls[0]["current_stage"] == "settlement"


@pytest.mark.parametrize(
    (
        "dates_failed",
        "boxscores_failed",
    ),
    [
        (1, 0),
        (0, 1),
    ],
)
def test_rejects_postgame_results_failures(
    dates_failed,
    boxscores_failed,
) -> None:
    summary = SimpleNamespace(
        dates_failed=dates_failed,
        boxscores_failed=boxscores_failed,
    )

    with pytest.raises(
        RuntimeError,
        match="results ingestion reported failures",
    ):
        moneyline_daily._run_postgame_results_ingestion(
            workflow_run_id=12,
            target_date=date(2026, 8, 3),
            connection_factory=lambda: None,
            results_fetcher=lambda **arguments: summary,
        )


def test_runs_postgame_settlement_with_run_ids() -> None:
    calls = []
    settlement_result = SimpleNamespace(
        report=SimpleNamespace(
            settlements_saved=1,
            pending_candidates=0,
        ),
    )

    def settlement_runner(**arguments):
        calls.append(arguments)
        return settlement_result

    result = moneyline_daily._run_postgame_settlement(
        prediction_run_id=25,
        odds_ingestion_run_id=182,
        settlement_runner=settlement_runner,
    )

    assert result is settlement_result
    assert calls == [
        {
            "prediction_run_id": 25,
            "odds_ingestion_run_id": 182,
        }
    ]


@pytest.mark.parametrize(
    (
        "pending_candidates",
        "early_entry_pending",
        "expected_updater",
    ),
    [
        (
            1,
            0,
            moneyline_daily
            .mark_moneyline_daily_postgame_pending,
        ),
        (
            0,
            1,
            moneyline_daily
            .mark_moneyline_daily_postgame_pending,
        ),
        (
            0,
            0,
            moneyline_daily
            .mark_moneyline_daily_settlement_completed,
        ),
    ],
)
def test_marks_postgame_settlement_state(
    monkeypatch,
    pending_candidates,
    early_entry_pending,
    expected_updater,
) -> None:
    updates = []

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: updates.append(arguments),
    )

    settlement_result = SimpleNamespace(
        report=SimpleNamespace(
            pending_candidates=pending_candidates,
        ),
    )
    early_entry_result = SimpleNamespace(
        performance=SimpleNamespace(
            pending=early_entry_pending,
        ),
    )

    moneyline_daily._mark_postgame_settlement_state(
        workflow_run_id=12,
        settlement_result=settlement_result,
        early_entry_result=early_entry_result,
        connection_factory=lambda: None,
    )

    assert updates[0]["workflow_run_id"] == 12
    assert updates[0]["updater"] is expected_updater


def test_postgame_runner_returns_to_awaiting_results(
    monkeypatch,
) -> None:
    updates = []

    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 3),
        status="awaiting_results",
        current_stage="results_ingestion",
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: workflow,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: updates.append(arguments),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_postgame_results_ingestion",
        lambda **arguments: SimpleNamespace(
            games_processed=7,
            boxscores_processed=7,
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_postgame_settlement",
        lambda **arguments: SimpleNamespace(
            report=SimpleNamespace(
                settlements_saved=0,
                pending_candidates=1,
            ),
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_mark_postgame_settlement_state",
        lambda **arguments: None,
    )

    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=8,
        evaluated_predictions=8,
        evaluations=8,
        paper_candidates=1,
        settlements=0,
        pipeline_state="awaiting_results",
    )

    result = moneyline_daily.run_moneyline_daily_postgame(
        target_date=date(2026, 8, 3),
        connection_factory=lambda: None,
        early_entry_settlement_runner=lambda **arguments: (
            SimpleNamespace(
                performance=SimpleNamespace(pending=0),
            )
        ),
        pipeline_auditor=lambda **arguments: audit,
    )

    assert result.games_processed == 7
    assert result.boxscores_processed == 7
    assert result.settlements_saved == 0
    assert result.pending_candidates == 1
    assert result.pipeline_state == "awaiting_results"

    assert not any(
        update["updater"]
        is moneyline_daily.mark_moneyline_daily_workflow_completed
        for update in updates
    )


def test_postgame_runner_completes_settled_workflow(
    monkeypatch,
) -> None:
    updates = []

    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 3),
        status="awaiting_results",
        current_stage="results_ingestion",
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: workflow,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: updates.append(arguments),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_postgame_results_ingestion",
        lambda **arguments: SimpleNamespace(
            games_processed=8,
            boxscores_processed=8,
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_postgame_settlement",
        lambda **arguments: SimpleNamespace(
            report=SimpleNamespace(
                settlements_saved=1,
                pending_candidates=0,
            ),
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_mark_postgame_settlement_state",
        lambda **arguments: None,
    )

    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=8,
        evaluated_predictions=8,
        evaluations=8,
        paper_candidates=1,
        settlements=1,
        pipeline_state="complete",
    )

    result = moneyline_daily.run_moneyline_daily_postgame(
        target_date=date(2026, 8, 3),
        connection_factory=lambda: None,
        early_entry_settlement_runner=lambda **arguments: (
            SimpleNamespace(
                performance=SimpleNamespace(pending=0),
            )
        ),
        pipeline_auditor=lambda **arguments: audit,
    )

    assert result.settlements_saved == 1
    assert result.pending_candidates == 0
    assert result.pipeline_state == "complete"

    assert any(
        update["updater"]
        is moneyline_daily.mark_moneyline_daily_workflow_completed
        for update in updates
    )


def test_postgame_settles_early_entry_after_official(
    monkeypatch,
) -> None:
    calls = []
    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 3),
        status="awaiting_results",
        current_stage="results_ingestion",
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: workflow,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: None,
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_postgame_results_ingestion",
        lambda **arguments: (
            calls.append("results")
            or SimpleNamespace(
                games_processed=1,
                boxscores_processed=1,
            )
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_run_postgame_settlement",
        lambda **arguments: (
            calls.append("official")
            or SimpleNamespace(
                report=SimpleNamespace(
                    settlements_saved=1,
                    pending_candidates=0,
                ),
            )
        ),
    )
    monkeypatch.setattr(
        moneyline_daily,
        "_mark_postgame_settlement_state",
        lambda **arguments: None,
    )

    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=1,
        evaluated_predictions=1,
        evaluations=1,
        paper_candidates=1,
        settlements=1,
        pipeline_state="complete",
    )

    result = moneyline_daily.run_moneyline_daily_postgame(
        target_date=date(2026, 8, 3),
        connection_factory=lambda: None,
        early_entry_settlement_runner=lambda **arguments: (
            calls.append("early_entry")
            or SimpleNamespace(
                performance=SimpleNamespace(pending=0),
            )
        ),
        pipeline_auditor=lambda **arguments: (
            calls.append("audit") or audit
        ),
    )

    assert calls == [
        "results",
        "official",
        "early_entry",
        "audit",
    ]
    assert result.settlements_saved == 1
    assert result.pending_candidates == 0


def test_completed_official_workflow_still_settles_early_entry(
    monkeypatch,
) -> None:
    calls = []
    workflow = SimpleNamespace(
        moneyline_daily_workflow_run_id=12,
        target_date=date(2026, 8, 3),
        status="completed",
        current_stage="complete",
        moneyline_prediction_run_id=25,
        odds_ingestion_run_id=182,
    )
    audit = SimpleNamespace(
        integrity_issues=(),
        predictions=1,
        evaluated_predictions=1,
        evaluations=1,
        paper_candidates=1,
        settlements=1,
        pipeline_state="complete",
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_get_or_create_workflow",
        lambda **arguments: workflow,
    )

    moneyline_daily.run_moneyline_daily_postgame(
        target_date=date(2026, 8, 3),
        connection_factory=lambda: None,
        early_entry_settlement_runner=lambda **arguments: (
            calls.append(arguments)
            or SimpleNamespace(
                performance=SimpleNamespace(pending=0),
            )
        ),
        pipeline_auditor=lambda **arguments: audit,
    )

    assert len(calls) == 1
    assert calls[0]["target_date"] == date(2026, 8, 3)
