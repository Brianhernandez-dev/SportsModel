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
