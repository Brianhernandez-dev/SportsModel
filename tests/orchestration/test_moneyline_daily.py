from datetime import date
from types import SimpleNamespace

import pytest

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
        schedule_syncer=lambda **arguments: SimpleNamespace(
            dates_failed=0,
        ),
        prediction_runner=lambda **arguments: prediction_result,
    )

    assert result is prediction_result
    assert updates[0]["current_stage"] == "prediction"
    assert updates[1]["prediction_run_id"] == 25


def test_stops_when_schedule_sync_fails() -> None:
    with pytest.raises(
        RuntimeError,
        match="1 failed date",
    ):
        moneyline_daily._run_schedule_and_prediction(
            workflow_run_id=12,
            target_date=date(2026, 8, 2),
            schedule_days_ahead=7,
            connection_factory=lambda: None,
            schedule_syncer=lambda **arguments: SimpleNamespace(
                dates_failed=1,
            ),
            prediction_runner=lambda **arguments: None,
        )


def test_runs_odds_ingestion_and_persists_quota(
    monkeypatch,
) -> None:
    updates = []

    odds_result = SimpleNamespace(
        odds_ingestion_run_id=182,
        status_code=200,
        remaining_requests=487,
        used_requests=13,
    )

    monkeypatch.setattr(
        moneyline_daily,
        "_update_workflow",
        lambda **arguments: updates.append(arguments),
    )

    result = moneyline_daily._run_odds_ingestion(
        workflow_run_id=12,
        connection_factory=lambda: None,
        odds_fetcher=lambda: odds_result,
    )

    assert result is odds_result

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
