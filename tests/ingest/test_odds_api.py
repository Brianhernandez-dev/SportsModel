from datetime import date, datetime, timezone

import pytest

from sportsmodel.ingest import odds_api


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(
        self,
        exception_type,
        exception,
        traceback,
    ) -> bool:
        return False


class FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class FakeResponse:
    status_code = 200

    headers = {
        "x-requests-remaining": "487",
        "x-requests-used": "13",
    }

    text = ""

    def json(self) -> list[object]:
        return []


def test_create_ingestion_run_rejects_duplicate_snapshot(
) -> None:
    class DuplicateCursor:
        def __enter__(self):
            return self

        def __exit__(
            self,
            exception_type,
            exception,
            traceback,
        ) -> bool:
            return False

        def execute(
            self,
            query,
            parameters,
        ) -> None:
            assert "ON CONFLICT DO NOTHING" in query
            assert parameters == (
                odds_api.SPORT,
                odds_api.SOURCE_NAME,
                date(2026, 8, 7),
                "morning",
            )

        def fetchone(self):
            return None

    class DuplicateConnection:
        def __init__(self) -> None:
            self.commits = 0

        def cursor(self):
            return DuplicateCursor()

        def commit(self) -> None:
            self.commits += 1

    connection = DuplicateConnection()

    with pytest.raises(
        odds_api.DuplicateOddsSnapshotError,
        match="active odds snapshot already exists",
    ):
        odds_api.create_ingestion_run(
            connection,
            target_date=date(2026, 8, 7),
            snapshot_role="morning",
        )

    assert connection.commits == 0


def test_duplicate_snapshot_does_not_request_odds(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    request_calls = 0

    monkeypatch.setenv(
        "ODDS_API_KEY",
        "test-key",
    )

    monkeypatch.setattr(
        odds_api,
        "get_connection",
        lambda: connection,
    )

    def duplicate_run(
        unused_connection,
        **unused_arguments,
    ):
        raise odds_api.DuplicateOddsSnapshotError(
            "snapshot already exists"
        )

    monkeypatch.setattr(
        odds_api,
        "create_ingestion_run",
        duplicate_run,
    )

    def fake_request(
        *unused_args,
        **unused_kwargs,
    ):
        nonlocal request_calls
        request_calls += 1
        return FakeResponse()

    monkeypatch.setattr(
        odds_api.requests,
        "get",
        fake_request,
    )

    with pytest.raises(
        odds_api.DuplicateOddsSnapshotError,
        match="snapshot already exists",
    ):
        odds_api.fetch_live_odds(
            target_date=date(2026, 8, 7),
            snapshot_role="morning",
        )

    assert request_calls == 0
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed is True


def test_fetch_live_odds_returns_structured_result(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    create_arguments = {}
    completed_arguments = {}
    request_arguments = {}

    monkeypatch.setenv(
        "ODDS_API_KEY",
        "test-key",
    )

    monkeypatch.setattr(
        odds_api,
        "get_connection",
        lambda: connection,
    )

    def fake_create_ingestion_run(
        unused_connection,
        **arguments,
    ) -> int:
        create_arguments.update(arguments)
        return 182

    monkeypatch.setattr(
        odds_api,
        "create_ingestion_run",
        fake_create_ingestion_run,
    )

    def fake_request(
        *arguments,
        **keyword_arguments,
    ):
        request_arguments["args"] = arguments
        request_arguments["kwargs"] = keyword_arguments
        return FakeResponse()

    monkeypatch.setattr(
        odds_api.requests,
        "get",
        fake_request,
    )

    def fake_mark_completed(
        **arguments,
    ) -> None:
        completed_arguments.update(arguments)

    monkeypatch.setattr(
        odds_api,
        "mark_ingestion_run_completed",
        fake_mark_completed,
    )

    result = odds_api.fetch_live_odds(
        target_date=date(2026, 8, 2),
        snapshot_role="entry",
    )

    request_params = (
        request_arguments["kwargs"]["params"]
    )

    assert request_params["commenceTimeFrom"] == (
        "2026-08-02T07:00:00Z"
    )
    assert request_params["commenceTimeTo"] == (
        "2026-08-03T06:59:59Z"
    )

    assert result == odds_api.OddsIngestionResult(
        odds_ingestion_run_id=182,
        target_date=date(2026, 8, 2),
        snapshot_role="entry",
        status_code=200,
        remaining_requests=487,
        used_requests=13,
        games_returned=0,
        games_processed=0,
        selections_inserted=0,
        selections_skipped=0,
    )

    assert create_arguments == {
        "target_date": date(2026, 8, 2),
        "snapshot_role": "entry",
    }

    assert (
        completed_arguments["ingestion_run_id"]
        == 182
    )
    assert completed_arguments["status_code"] == 200
    assert completed_arguments["remaining_requests"] == 487
    assert completed_arguments["used_requests"] == 13

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_builds_pacific_target_date_window() -> None:
    window_start, window_end = (
        odds_api.build_target_date_window(
            date(2026, 8, 7)
        )
    )

    assert window_start == datetime(
        2026,
        8,
        7,
        7,
        0,
        tzinfo=timezone.utc,
    )
    assert window_end == datetime(
        2026,
        8,
        8,
        7,
        0,
        tzinfo=timezone.utc,
    )


def test_target_date_window_handles_dst_transition(
) -> None:
    window_start, window_end = (
        odds_api.build_target_date_window(
            date(2026, 11, 1)
        )
    )

    assert window_start == datetime(
        2026,
        11,
        1,
        7,
        0,
        tzinfo=timezone.utc,
    )
    assert window_end == datetime(
        2026,
        11,
        2,
        8,
        0,
        tzinfo=timezone.utc,
    )


def test_checks_event_against_half_open_target_window(
) -> None:
    target_window = odds_api.build_target_date_window(
        date(2026, 8, 7)
    )

    assert odds_api._is_in_target_date_window(
        datetime(
            2026,
            8,
            7,
            22,
            40,
            tzinfo=timezone.utc,
        ),
        target_window,
    )

    assert not odds_api._is_in_target_date_window(
        datetime(
            2026,
            8,
            6,
            23,
            10,
            tzinfo=timezone.utc,
        ),
        target_window,
    )

    assert not odds_api._is_in_target_date_window(
        target_window[1],
        target_window,
    )


def test_scheduled_snapshot_requires_target_date() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "Scheduled odds snapshots "
            "require a target date"
        ),
    ):
        odds_api.fetch_live_odds(
            snapshot_role="entry",
        )


def test_rejects_unsupported_snapshot_role() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported odds snapshot role",
    ):
        odds_api.fetch_live_odds(
            target_date=date(2026, 8, 2),
            snapshot_role="closing",
        )


def test_parse_quota_header_returns_none_for_missing_value(
) -> None:
    assert odds_api._parse_quota_header(None) is None


def test_parse_quota_header_returns_none_for_invalid_value(
) -> None:
    assert (
        odds_api._parse_quota_header(
            "unavailable"
        )
        is None
    )


def test_parse_quota_header_returns_integer() -> None:
    assert odds_api._parse_quota_header("487") == 487
