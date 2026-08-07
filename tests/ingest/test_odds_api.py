from datetime import date

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


def test_fetch_live_odds_returns_structured_result(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    create_arguments = {}
    completed_arguments = {}

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

    monkeypatch.setattr(
        odds_api.requests,
        "get",
        lambda *unused_args, **unused_kwargs: (
            FakeResponse()
        ),
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
