from datetime import date, datetime, timezone

import pytest

from sportsmodel.ingest import odds_api
from sportsmodel.ingest.odds_provenance import (
    ProviderSportsbookIdentity,
)


def test_evening_roles_are_live_scheduled_snapshots() -> None:
    for snapshot_role in (
        "evening",
        "late_night",
    ):
        assert snapshot_role in odds_api.LIVE_SNAPSHOT_ROLES
        assert snapshot_role in odds_api.SCHEDULED_SNAPSHOT_ROLES


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
                odds_api.REQUEST_PATH,
                odds_api.REGIONS,
                odds_api.MARKETS,
                odds_api.ODDS_FORMAT,
                datetime(
                    2026,
                    8,
                    7,
                    7,
                    tzinfo=timezone.utc,
                ),
                datetime(
                    2026,
                    8,
                    8,
                    6,
                    59,
                    59,
                    tzinfo=timezone.utc,
                ),
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
    response_arguments = {}
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

    observed_at = datetime(
        2026,
        8,
        1,
        18,
        tzinfo=timezone.utc,
    )

    def fake_record_response(
        unused_connection,
        **arguments,
    ) -> datetime:
        response_arguments.update(arguments)
        return observed_at

    monkeypatch.setattr(
        odds_api,
        "record_ingestion_response",
        fake_record_response,
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
    assert response_arguments == {
        "ingestion_run_id": 182,
        "status_code": 200,
        "remaining_requests": 487,
        "used_requests": 13,
    }

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


def test_records_response_metadata_once_with_database_time() -> None:
    observed_at = datetime(
        2026,
        8,
        2,
        12,
        tzinfo=timezone.utc,
    )

    class ResponseCursor:
        def __enter__(self):
            return self

        def __exit__(self, *unused_arguments) -> bool:
            return False

        def execute(self, query, parameters) -> None:
            assert "response_received_at = clock_timestamp()" in query
            assert "response_received_at IS NULL" in query
            assert parameters == (200, 487, 13, 182)

        def fetchone(self):
            return (observed_at,)

    class ResponseConnection:
        def __init__(self) -> None:
            self.commits = 0

        def cursor(self):
            return ResponseCursor()

        def commit(self) -> None:
            self.commits += 1

    connection = ResponseConnection()
    assert odds_api.record_ingestion_response(
        connection,
        ingestion_run_id=182,
        status_code=200,
        remaining_requests=487,
        used_requests=13,
    ) == observed_at
    assert connection.commits == 1


def test_mlb_adapter_passes_exact_provider_provenance(
    monkeypatch,
) -> None:
    event_time = datetime(
        2026,
        8,
        21,
        23,
        10,
        tzinfo=timezone.utc,
    )
    observed_at = datetime(
        2026,
        8,
        21,
        18,
        1,
        tzinfo=timezone.utc,
    )
    payload = [
        {
            "id": "mlb-provider-event",
            "sport_key": "baseball_mlb",
            "commence_time": event_time.isoformat(),
            "home_team": "Seattle Mariners",
            "away_team": "New York Yankees",
            "bookmakers": [
                {
                    "key": "fanduel",
                    "title": "FanDuel",
                    "last_update": "2026-08-21T18:00:01Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "last_update": "2026-08-21T18:00:00Z",
                            "outcomes": [
                                {
                                    "name": "Seattle Mariners",
                                    "price": -112,
                                },
                                {
                                    "name": "New York Yankees",
                                    "price": 102,
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    class PayloadResponse(FakeResponse):
        def json(self):
            return payload

    connection = FakeConnection()
    event_calls = []
    sportsbook_calls = []
    saved_quotes = []
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setattr(odds_api, "get_connection", lambda: connection)
    monkeypatch.setattr(
        odds_api,
        "create_ingestion_run",
        lambda *unused_args, **unused_kwargs: 182,
    )
    monkeypatch.setattr(
        odds_api.requests,
        "get",
        lambda *unused_args, **unused_kwargs: PayloadResponse(),
    )
    monkeypatch.setattr(
        odds_api,
        "record_ingestion_response",
        lambda *unused_args, **unused_kwargs: observed_at,
    )
    monkeypatch.setattr(odds_api, "get_team_id", lambda *args: 10)
    monkeypatch.setattr(
        odds_api,
        "get_or_create_canonical_game",
        lambda *unused_args, **unused_kwargs: 77,
    )

    def fake_event_observation(*unused_args, **arguments) -> int:
        event_calls.append(arguments)
        return 91

    monkeypatch.setattr(
        odds_api,
        "create_provider_event_observation",
        fake_event_observation,
    )

    def fake_sportsbook(*unused_args, **arguments):
        sportsbook_calls.append(arguments)
        return ProviderSportsbookIdentity(41, 7)

    monkeypatch.setattr(
        odds_api,
        "resolve_provider_sportsbook",
        fake_sportsbook,
    )
    monkeypatch.setattr(
        odds_api,
        "save_market_selection",
        lambda **arguments: saved_quotes.append(arguments),
    )
    monkeypatch.setattr(
        odds_api,
        "mark_ingestion_run_completed",
        lambda **unused_arguments: None,
    )

    result = odds_api.fetch_live_odds(
        target_date=date(2026, 8, 21),
        snapshot_role="manual",
    )

    assert result.games_processed == 1
    assert result.selections_inserted == 2
    assert event_calls[0]["provider_name"] == "odds_api"
    assert event_calls[0]["event"].event_id == "mlb-provider-event"
    assert event_calls[0]["event"].sport_key == "baseball_mlb"
    assert event_calls[0]["observed_at"] == observed_at
    assert sportsbook_calls == [
        {
            "provider_name": "odds_api",
            "provider_bookmaker_key": "fanduel",
            "bookmaker_title": "FanDuel",
        }
    ]
    assert {
        quote["selection_name"] for quote in saved_quotes
    } == {"Seattle Mariners", "New York Yankees"}
    for quote in saved_quotes:
        assert quote["event_observation_id"] == 91
        assert quote["sportsbook_provider_identity_id"] == 41
        assert quote["sportsbook_id"] == 7
        assert quote["bookmaker_title"] == "FanDuel"
        assert quote["bookmaker_updated_at"] == datetime(
            2026,
            8,
            21,
            18,
            0,
            1,
            tzinfo=timezone.utc,
        )
        assert quote["market_updated_at"] == datetime(
            2026,
            8,
            21,
            18,
            tzinfo=timezone.utc,
        )
        assert quote["snapshot_time"] == observed_at

@pytest.fixture(autouse=True)
def freeze_odds_snapshot_time(
    monkeypatch,
) -> None:
    """
    Keep existing ingestion fixtures deterministically pregame.
    """

    monkeypatch.setattr(
        odds_api,
        "_current_snapshot_time",
        lambda: datetime(
            2000,
            1,
            1,
            tzinfo=timezone.utc,
        ),
    )


def test_pregame_event_requires_future_start() -> None:
    snapshot_time = datetime(
        2026,
        8,
        7,
        18,
        0,
        tzinfo=timezone.utc,
    )

    assert odds_api._is_pregame_event(
        datetime(
            2026,
            8,
            7,
            18,
            1,
            tzinfo=timezone.utc,
        ),
        snapshot_time,
    )

    assert not odds_api._is_pregame_event(
        snapshot_time,
        snapshot_time,
    )

    assert not odds_api._is_pregame_event(
        datetime(
            2026,
            8,
            7,
            17,
            59,
            tzinfo=timezone.utc,
        ),
        snapshot_time,
    )


def test_process_event_rejects_in_play_game() -> None:
    target_window = odds_api.build_target_date_window(
        date(2026, 8, 7)
    )

    assert not odds_api._should_process_event(
        datetime(
            2026,
            8,
            7,
            23,
            10,
            tzinfo=timezone.utc,
        ),
        target_window,
        datetime(
            2026,
            8,
            7,
            23,
            11,
            tzinfo=timezone.utc,
        ),
    )


def test_process_event_rejects_wrong_slate_date() -> None:
    target_window = odds_api.build_target_date_window(
        date(2026, 8, 7)
    )

    assert not odds_api._should_process_event(
        datetime(
            2026,
            8,
            6,
            23,
            10,
            tzinfo=timezone.utc,
        ),
        target_window,
        datetime(
            2026,
            8,
            6,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert odds_api._should_process_event(
        datetime(
            2026,
            8,
            7,
            23,
            10,
            tzinfo=timezone.utc,
        ),
        target_window,
        datetime(
            2026,
            8,
            7,
            20,
            0,
            tzinfo=timezone.utc,
        ),
    )
