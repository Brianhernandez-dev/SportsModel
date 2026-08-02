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
