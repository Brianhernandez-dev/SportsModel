from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from sportsmodel.dashboard import startup_probe


class _FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.statements: list[str] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _FakeConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.fake_cursor = _FakeCursor(rows)
        self.session_calls: list[dict[str, object]] = []
        self.closed = False

    def set_session(self, **settings: object) -> None:
        self.session_calls.append(settings)

    def cursor(self) -> _FakeCursor:
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True


def _slate_row() -> tuple[object, ...]:
    return (
        64,
        352,
        "1.0.0",
        date(2026, 9, 5),
        "morning",
        datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc),
        "official",
    )


def test_probe_reads_daily_card_boundary_in_read_only_session() -> None:
    connection = _FakeConnection([_slate_row()])

    result = startup_probe.probe_dashboard_production_read(
        connection_factory=lambda: connection,
    )

    assert result.slate_count == 1
    assert result.latest_prediction_run_id == 64
    assert result.latest_odds_ingestion_run_id == 352
    assert result.latest_target_date == "2026-09-05"
    assert connection.session_calls == [
        {"readonly": True, "autocommit": False}
    ]
    assert connection.closed is True
    assert len(connection.fake_cursor.statements) == 1
    normalized_statement = (
        connection.fake_cursor.statements[0].strip().upper()
    )
    assert normalized_statement.startswith("SELECT")
    for mutation in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE "):
        assert mutation not in normalized_statement


def test_probe_fails_when_persisted_dashboard_data_is_unavailable() -> None:
    connection = _FakeConnection([])

    with pytest.raises(LookupError, match="No persisted MLB Moneyline slates"):
        startup_probe.probe_dashboard_production_read(
            connection_factory=lambda: connection,
        )

    assert connection.session_calls == [
        {"readonly": True, "autocommit": False}
    ]
    assert connection.closed is True


def test_probe_cli_reports_success_without_configuration_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = startup_probe.DashboardStartupProbeResult(
        slate_count=12,
        latest_prediction_run_id=64,
        latest_odds_ingestion_run_id=352,
        latest_target_date="2026-09-05",
    )
    monkeypatch.setattr(
        startup_probe,
        "probe_dashboard_production_read",
        lambda: result,
    )

    assert startup_probe.main([]) == 0
    output = capsys.readouterr().out
    assert "Dashboard production read probe: READY" in output
    assert "latest prediction run=64" in output
    assert "latest odds run=352" in output
    assert "password" not in output.lower()
    assert "connection" not in output.lower()


def test_probe_cli_failure_is_fail_closed_and_does_not_leak_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_probe() -> startup_probe.DashboardStartupProbeResult:
        raise RuntimeError("sensitive-value-should-not-appear")

    monkeypatch.setattr(
        startup_probe,
        "probe_dashboard_production_read",
        fail_probe,
    )

    assert startup_probe.main([]) == 1
    output = capsys.readouterr().out
    assert "Dashboard production read probe: FAILED" in output
    assert "sensitive-value-should-not-appear" not in output
