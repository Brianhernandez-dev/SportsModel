import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from sportsmodel.ingest.odds_provenance import ProviderIdentityConflictError
from sportsmodel.nfl import manual_odds_capture as capture
from sportsmodel.nfl import manual_odds_capture_cli as cli
from sportsmodel.nfl.odds_identity import (
    AmbiguousNflGameMatchError,
    CanonicalNflGameNotFoundError,
    NflProviderEventConflictError,
    UnacceptableNflKickoffDriftError,
    UnknownNflTeamIdentityError,
)
from sportsmodel.nfl.official_pregame_evidence import (
    NflObservationNotPregameError,
)


ROOT = Path(__file__).parents[2]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "odds_api"
    / "nfl_h2h_multi_event_response.json"
)
TARGET_DATE = date(2026, 9, 13)
OBSERVED_AT = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)


class _FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _FakeCursor()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _response(body=None) -> capture.NflProviderResponse:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return capture.NflProviderResponse(
        status_code=fixture["status_code"],
        headers=fixture["headers"],
        body=json.dumps(fixture["body"] if body is None else body),
    )


def _configure_after_reservation(monkeypatch, *, persisted=None) -> None:
    monkeypatch.setattr(capture, "reserve_nfl_capture_run", lambda *_a, **_k: 41)
    monkeypatch.setattr(capture, "_record_response_once", lambda *_a, **_k: OBSERVED_AT)
    monkeypatch.setattr(capture, "_mark_run_failed", lambda *_a, **_k: None)
    if persisted is not None:
        monkeypatch.setattr(capture, "_persist_capture_payload", lambda *_a, **_k: persisted)


def test_default_cli_is_no_network_no_write_dry_run(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "get_connection",
        lambda: pytest.fail("dry run opened a database connection"),
    )
    monkeypatch.setattr(
        cli,
        "call_odds_api_once",
        lambda *_a, **_k: pytest.fail("dry run called the provider"),
    )

    assert cli.main([]) == 0
    assert "no database writes and no provider request" in capsys.readouterr().out


def test_live_cli_requires_explicit_one_request_confirmation(monkeypatch) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "mock-key-never-used")
    monkeypatch.setattr(
        cli,
        "get_connection",
        lambda: pytest.fail("unconfirmed live mode opened the database"),
    )

    with pytest.raises(SystemExit):
        cli.main(["--live", "--target-date", TARGET_DATE.isoformat()])


def test_live_adapter_invokes_requests_get_exactly_once(monkeypatch) -> None:
    calls = []

    class Response:
        status_code = 200
        headers = {"x-requests-remaining": "487"}
        text = "[]"

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr(capture.requests, "get", fake_get)
    start, end = capture.utc_target_date_window(TARGET_DATE)
    request = capture.NflProviderRequest(
        capture.NFL_SPORT_KEY,
        capture.REGIONS,
        capture.MARKETS,
        capture.ODDS_FORMAT,
        start,
        end,
    )

    response = capture.call_odds_api_once(request, api_key="test-key")

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][1]["params"]["markets"] == "h2h"
    assert calls[0][1]["params"]["regions"] == "us"
    assert calls[0][1]["allow_redirects"] is False


def test_live_adapter_rejects_non_nfl_h2h_contract_before_http(monkeypatch) -> None:
    monkeypatch.setattr(
        capture.requests,
        "get",
        lambda *_a, **_k: pytest.fail("invalid request reached HTTP transport"),
    )
    start, end = capture.utc_target_date_window(TARGET_DATE)
    request = capture.NflProviderRequest(
        "baseball_mlb",
        capture.REGIONS,
        capture.MARKETS,
        capture.ODDS_FORMAT,
        start,
        end,
    )

    with pytest.raises(ValueError, match="sport=americanfootball_nfl"):
        capture.call_odds_api_once(request, api_key="test-key")


def test_duplicate_reservation_stops_before_provider_call(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        capture,
        "reserve_nfl_capture_run",
        lambda *_a, **_k: (_ for _ in ()).throw(
            capture.DuplicateNflCaptureReservationError("duplicate")
        ),
    )

    with pytest.raises(capture.DuplicateNflCaptureReservationError):
        capture.execute_manual_nfl_capture(
            _FakeConnection(),
            target_date=TARGET_DATE,
            provider_call=lambda request: calls.append(request),
        )

    assert calls == []


def test_parser_failure_has_no_hidden_second_call(monkeypatch) -> None:
    _configure_after_reservation(monkeypatch)
    calls = []

    def provider(request):
        calls.append(request)
        return capture.NflProviderResponse(200, {}, "not-json")

    with pytest.raises(capture.NflCaptureProcessingError, match="parse"):
        capture.execute_manual_nfl_capture(
            _FakeConnection(),
            target_date=TARGET_DATE,
            provider_call=provider,
        )

    assert len(calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        UnknownNflTeamIdentityError("unknown"),
        CanonicalNflGameNotFoundError("missing"),
        AmbiguousNflGameMatchError("ambiguous"),
        UnacceptableNflKickoffDriftError("drift"),
        ProviderIdentityConflictError("book conflict"),
        NflProviderEventConflictError("event conflict"),
    ],
)
def test_mapping_or_persistence_failures_make_one_provider_call(
    monkeypatch,
    error,
) -> None:
    _configure_after_reservation(monkeypatch)
    monkeypatch.setattr(
        capture,
        "_persist_capture_payload",
        lambda *_a, **_k: (_ for _ in ()).throw(error),
    )
    calls = []

    with pytest.raises(capture.NflCaptureProcessingError, match="persistence"):
        capture.execute_manual_nfl_capture(
            _FakeConnection(),
            target_date=TARGET_DATE,
            provider_call=lambda request: calls.append(request) or _response(),
        )

    assert len(calls) == 1


@pytest.mark.parametrize(
    "malformation",
    ["cross_sport", "wrong_market", "third", "duplicate"],
)
def test_malformed_payload_failure_makes_one_provider_call(
    monkeypatch,
    malformation,
) -> None:
    _configure_after_reservation(monkeypatch)
    body = json.loads(_response().body)
    if malformation == "cross_sport":
        body[0]["sport_key"] = "baseball_mlb"
    elif malformation == "wrong_market":
        body[0]["bookmakers"][0]["markets"][0]["key"] = "spreads"
    elif malformation == "third":
        body[0]["bookmakers"][0]["markets"][0]["outcomes"].append(
            {"name": "New York Jets", "price": 200}
        )
    else:
        outcomes = body[0]["bookmakers"][0]["markets"][0]["outcomes"]
        outcomes[1]["name"] = outcomes[0]["name"]
    calls = []

    with pytest.raises(capture.NflCaptureProcessingError, match="parse"):
        capture.execute_manual_nfl_capture(
            _FakeConnection(),
            target_date=TARGET_DATE,
            provider_call=lambda request: calls.append(request) or _response(body),
        )

    assert len(calls) == 1


def test_provider_transport_failure_has_no_hidden_second_call(monkeypatch) -> None:
    monkeypatch.setattr(capture, "reserve_nfl_capture_run", lambda *_a, **_k: 41)
    monkeypatch.setattr(capture, "_mark_run_failed", lambda *_a, **_k: None)
    calls = []

    def provider(request):
        calls.append(request)
        raise TimeoutError("provider timeout")

    with pytest.raises(capture.NflCaptureProcessingError, match="provider_call"):
        capture.execute_manual_nfl_capture(
            _FakeConnection(),
            target_date=TARGET_DATE,
            provider_call=provider,
        )

    assert len(calls) == 1


def test_response_persistence_failure_makes_one_provider_call(monkeypatch) -> None:
    monkeypatch.setattr(capture, "reserve_nfl_capture_run", lambda *_a, **_k: 41)
    monkeypatch.setattr(
        capture,
        "_record_response_once",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("database write")),
    )
    monkeypatch.setattr(capture, "_mark_run_failed", lambda *_a, **_k: None)
    calls = []

    with pytest.raises(capture.NflCaptureProcessingError, match="response_persistence"):
        capture.execute_manual_nfl_capture(
            _FakeConnection(),
            target_date=TARGET_DATE,
            provider_call=lambda request: calls.append(request) or _response(),
        )

    assert len(calls) == 1


def test_pregame_rejection_is_skipped_without_second_call(monkeypatch) -> None:
    persisted = capture._PersistedCapture((1,), (2,), (3,), ((4, 5),))
    _configure_after_reservation(monkeypatch, persisted=persisted)
    monkeypatch.setattr(
        capture,
        "create_official_nfl_pregame_evidence",
        lambda *_a, **_k: (_ for _ in ()).throw(
            NflObservationNotPregameError("at kickoff")
        ),
    )
    calls = []

    audit = capture.execute_manual_nfl_capture(
        _FakeConnection(),
        target_date=TARGET_DATE,
        provider_call=lambda request: calls.append(request) or _response(),
    )

    assert len(calls) == 1
    assert audit.official_pregame_skipped == 1
    assert audit.official_pregame_evidence_ids == ()


def test_qualification_failure_retains_raw_run_without_second_call(monkeypatch) -> None:
    persisted = capture._PersistedCapture((1,), (2,), (3,), ((4, 5),))
    _configure_after_reservation(monkeypatch, persisted=persisted)
    monkeypatch.setattr(
        capture,
        "create_official_nfl_pregame_evidence",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("qualification write")),
    )
    calls = []

    with pytest.raises(capture.NflCaptureQualificationError, match="do not call"):
        capture.execute_manual_nfl_capture(
            _FakeConnection(),
            target_date=TARGET_DATE,
            provider_call=lambda request: calls.append(request) or _response(),
        )

    assert len(calls) == 1


def test_quota_metadata_is_case_insensitive_and_never_invented() -> None:
    headers = {"X-Requests-Remaining": "487", "x-requests-used": "13"}

    assert capture._quota_header(headers, "x-requests-remaining") == 487
    assert capture._quota_header(headers, "x-requests-used") == 13
    assert capture._quota_header({}, "x-requests-used") is None
    assert capture._quota_header({"x-requests-used": "unknown"}, "x-requests-used") is None
