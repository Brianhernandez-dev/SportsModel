from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import gzip
from hashlib import sha256
import inspect
import json
from pathlib import Path

import pytest

from sportsmodel.nfl import historical_market_pilot as pilot


ROOT = Path(__file__).resolve().parents[2]
SELECTION_PATH = (
    ROOT
    / "docs"
    / "architecture"
    / "nfl_historical_market_provider_pilot_selection_manifest_0.1.3.json"
)
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
TEST_SECRET = "TEST_KEY_DO_NOT_SEND"


class MutableClock:
    def __init__(self, value: datetime = NOW):
        self.value = value

    @property
    def runtime_identity(self) -> str:
        return "TEST_CLOCK_UTC_V1"

    @property
    def monotonic_identity(self) -> str:
        return "TEST_MONOTONIC_V1"

    def now_utc(self) -> datetime:
        return self.value

    def monotonic_ns(self) -> int:
        return int(self.value.timestamp() * 1_000_000_000)

    def sleep(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


@pytest.fixture(scope="module")
def selection() -> pilot.FrozenSelection:
    return pilot.load_frozen_selection(SELECTION_PATH)


@pytest.fixture()
def target(selection: pilot.FrozenSelection) -> pilot.FrozenTarget:
    return selection.targets[0]


def _config(tmp_path: Path, selection: pilot.FrozenSelection) -> pilot.PilotExecutionConfig:
    credential = pilot.SecretCredential(TEST_SECRET)
    clock = MutableClock()
    transport = pilot.DeterministicFakeTransport([])
    return pilot.PilotExecutionConfig(
        evidence_store_root=str(tmp_path / "evidence"),
        credential_identity="TEST_DEDICATED_CREDENTIAL",
        credential_fingerprint=credential.fingerprint,
        quota_attribution_mode=pilot.QuotaAttributionMode.DEDICATED_CREDENTIAL,
        implementation_revision="a" * 40,
        implementation_sha256="B" * 64,
        repository_head="a" * 40,
        repository_clean=True,
        clock_identity=pilot.component_runtime_identity(clock),
        monotonic_timer_identity="TEST_MONOTONIC_V1",
        transport_identity=pilot.component_runtime_identity(transport),
        runtime_mode=pilot.RUNTIME_MODE,
        runtime_identity="TEST_CPYTHON_RUNTIME",
        dependency_identity="D" * 64,
        timezone_identity="TEST_TZDATA_IDENTITY",
        os_sync_source="TEST_LOCAL_CLOCK_SOURCE",
        os_sync_status="SYNCHRONIZED",
        runtime_inspector_identity=pilot.RUNTIME_INSPECTOR_ID,
        target_ids=selection.target_ids,
    )


def _provenance(
    tmp_path: Path, config: pilot.PilotExecutionConfig
) -> pilot.RuntimeProvenance:
    return pilot.RuntimeProvenance(
        repository_root=str((tmp_path / "repository").resolve()),
        git_head=config.repository_head,
        git_clean=config.repository_clean,
        implementation_source_sha256=config.implementation_sha256,
        configuration_sha256=config.sha256,
        runtime_identity=config.runtime_identity,
        dependency_identity=config.dependency_identity,
        timezone_identity=config.timezone_identity,
        evidence_store_root=str(Path(config.evidence_store_root).resolve()),
        os_sync_source=config.os_sync_source,
        os_sync_status=config.os_sync_status,
        phase_offset_evidence="0.0000000s",
        last_successful_sync_evidence="2026-10-01T11:59:00Z",
        monotonic_timer_identity=config.monotonic_timer_identity,
        transport_identity=config.transport_identity,
        clock_identity=config.clock_identity,
        runtime_mode=config.runtime_mode,
        runtime_inspector_identity=pilot.RUNTIME_INSPECTOR_ID,
    )


@pytest.fixture(autouse=True)
def _offline_local_runtime_measurement(monkeypatch: pytest.MonkeyPatch) -> None:
    def inspect(
        inspector: pilot.LocalRuntimeProvenanceInspector,
        *,
        config: pilot.PilotExecutionConfig,
        transport: pilot.ProviderTransport,
        clock: pilot.PilotClock,
    ) -> pilot.RuntimeProvenance:
        del transport, clock
        return replace(
            _provenance(inspector.repository_root.parent, config),
            repository_root=str(inspector.repository_root),
        )

    def inspect_recovery(
        inspector: pilot.LocalRuntimeProvenanceInspector,
        *,
        config: pilot.PilotExecutionConfig,
        clock: pilot.PilotClock,
    ) -> pilot.RecoveryRuntimeProvenance:
        return pilot.RecoveryRuntimeProvenance(
            repository_root=str(inspector.repository_root),
            git_head=config.repository_head,
            git_clean=True,
            implementation_source_sha256=config.implementation_sha256,
            configuration_sha256=config.sha256,
            runtime_identity=config.runtime_identity,
            dependency_identity=config.dependency_identity,
            timezone_identity=config.timezone_identity,
            os_sync_source=config.os_sync_source,
            os_sync_status=config.os_sync_status,
            phase_offset_evidence="0.0000000s",
            last_successful_sync_evidence="2026-10-01T11:59:00Z",
            monotonic_timer_identity=clock.monotonic_identity,
            clock_identity=pilot.component_runtime_identity(clock),
            recovery_mode="RECOVERY_ONLY",
            runtime_inspector_identity=pilot.RUNTIME_INSPECTOR_ID,
        )

    monkeypatch.setattr(pilot.LocalRuntimeProvenanceInspector, "inspect", inspect)
    monkeypatch.setattr(
        pilot.LocalRuntimeProvenanceInspector, "inspect_recovery", inspect_recovery
    )


def _authorization_payload(
    config: pilot.PilotExecutionConfig,
    selection: pilot.FrozenSelection,
    *,
    start: datetime = NOW - timedelta(minutes=5),
    end: datetime = NOW + timedelta(minutes=30),
) -> dict[str, object]:
    text = lambda value: value.isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "authorization_id": "TEST_AUTHORIZATION_NOT_FOR_PROVIDER_USE",
        "authorizer_reference": "TEST_FIXTURE_ONLY",
        "authorized_at": text(start - timedelta(minutes=1)),
        "window_start": text(start),
        "window_end": text(end),
        "protocol": {
            "identity": pilot.PROTOCOL_ID,
            "sha256": pilot.PROTOCOL_SHA256,
        },
        "pilot_spec": {
            "identity": pilot.PILOT_SPEC_ID,
            "sha256": pilot.PILOT_SPEC_SHA256,
        },
        "selection_manifest": {
            "identity": pilot.SELECTION_ID,
            "sha256": pilot.SELECTION_SHA256,
        },
        "kickoff_authority": {
            "package_zip_sha256": pilot.KICKOFF_PACKAGE_SHA256,
            "authority_ledger_sha256": pilot.KICKOFF_LEDGER_SHA256,
        },
        "implementation": {
            "identity": pilot.IMPLEMENTATION_ID,
            "git_revision": config.implementation_revision,
            "sha256": config.implementation_sha256,
        },
        "configuration_sha256": config.sha256,
        "repository": {"head": config.repository_head, "clean": True},
        "credential": {
            "identity": config.credential_identity,
            "fingerprint": config.credential_fingerprint,
            "quota_attribution_mode": config.quota_attribution_mode.value,
        },
        "evidence_store_root": str(Path(config.evidence_store_root).resolve()),
        "clock_identity": config.clock_identity,
        "runtime_mode": pilot.RUNTIME_MODE,
        "execution_policy": {
            "mode": "INITIAL_ONLY_NO_CONTINUATION",
            "predecessor_evidence_manifest_sha256": None,
        },
        "target_ids": list(selection.target_ids),
        "ceilings": {
            "primary": 20,
            "retries": 20,
            "attempts": 40,
            "credits": 400,
            "per_attempt_reservation": 10,
        },
    }


def _write_authorization(
    tmp_path: Path,
    config: pilot.PilotExecutionConfig,
    selection: pilot.FrozenSelection,
    **kwargs: object,
) -> Path:
    path = tmp_path / "test_authorization.json"
    path.write_text(
        json.dumps(_authorization_payload(config, selection, **kwargs), sort_keys=True),
        encoding="utf-8",
    )
    return path


def _body(
    target: pilot.FrozenTarget,
    *,
    wrapper: str | None = "2021-11-07T16:55:00Z",
    previous: object = "2021-11-07T16:50:00Z",
    following: object = "2021-11-07T17:05:00Z",
    market_last: object = "2021-11-07T16:54:00Z",
    price_token: str = "1.9100",
    extra_events: list[dict[str, object]] | None = None,
    prohibited: tuple[str, object] | None = None,
) -> bytes:
    market: dict[str, object] = {
        "key": "h2h",
        "last_update": market_last,
        "outcomes": [
            {"name": pilot.TEAM_PROVIDER_NAMES[target.home_team], "price": "TOKEN"},
            {"name": pilot.TEAM_PROVIDER_NAMES[target.away_team], "price": 2.05},
        ],
    }
    event: dict[str, object] = {
        "id": "synthetic-provider-event",
        "sport_key": pilot.EXPECTED_SPORT,
        "commence_time": target.kickoff_utc,
        "home_team": pilot.TEAM_PROVIDER_NAMES[target.home_team],
        "away_team": pilot.TEAM_PROVIDER_NAMES[target.away_team],
        "bookmakers": [
            {
                "key": "draftkings",
                "last_update": "2099-01-01T00:00:00Z",
                "markets": [market],
            }
        ],
    }
    if prohibited is not None:
        event[prohibited[0]] = prohibited[1]
    payload: dict[str, object] = {
        "timestamp": wrapper,
        "previous_timestamp": previous,
        "next_timestamp": following,
        "data": [event, *(extra_events or [])],
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return text.replace('"TOKEN"', price_token).encode("utf-8")


def _empty_body(target: pilot.FrozenTarget) -> bytes:
    del target
    return json.dumps(
        {
            "timestamp": "2021-11-07T16:55:00Z",
            "previous_timestamp": "2021-11-07T16:50:00Z",
            "next_timestamp": "2021-11-07T17:05:00Z",
            "data": [],
        },
        separators=(",", ":"),
    ).encode()


def _body_for_target(target: pilot.FrozenTarget) -> bytes:
    requested = datetime.fromisoformat(target.requested_date.replace("Z", "+00:00"))
    text = lambda value: value.isoformat(timespec="seconds").replace("+00:00", "Z")
    return _body(
        target,
        wrapper=text(requested - timedelta(minutes=5)),
        previous=text(requested - timedelta(minutes=10)),
        following=text(requested + timedelta(minutes=5)),
        market_last=text(requested - timedelta(minutes=6)),
    )


def _headers(
    *, used: int = 10, remaining: int = 90, last: int = 10, **extra: str
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Date": "Thu, 01 Oct 2026 12:00:00 GMT",
        "x-requests-used": str(used),
        "x-requests-remaining": str(remaining),
        "x-requests-last": str(last),
        **extra,
    }


def _response(
    target: pilot.FrozenTarget,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> pilot.ProviderResponse:
    return pilot.ProviderResponse(
        status,
        headers or _headers(),
        _body(target) if body is None else body,
    )


def _store(tmp_path: Path) -> pilot.EvidenceStore:
    repository = tmp_path / "repository"
    repository.mkdir()
    store = pilot.EvidenceStore(tmp_path / "evidence", repository_root=repository)
    store.initialize_new()
    return store


def _executor(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    config: pilot.PilotExecutionConfig,
    authorization_path: Path,
    transport: pilot.ProviderTransport,
    *,
    credential: pilot.SecretCredential | None = None,
    clock: MutableClock | None = None,
) -> pilot.PilotExecutor:
    active_clock = clock or MutableClock()
    return pilot.PilotExecutor(
        selection=selection,
        config=config,
        authorization_path=authorization_path,
        transport=transport,
        credential=credential or pilot.SecretCredential(TEST_SECRET),
        repository_root=tmp_path / "repository",
        clock=active_clock,
    )


def _create_interrupted_store(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    state: pilot.AttemptState,
) -> tuple[pilot.PilotExecutionConfig, pilot.EvidenceStore]:
    config = _config(tmp_path, selection)
    auth = pilot.load_and_validate_authorization(
        _write_authorization(tmp_path, config, selection),
        config=config,
        selection=selection,
        now=NOW,
    )
    store = _store(tmp_path)
    provenance = _provenance(tmp_path, config)
    store.claim_authorization(auth)
    store.write_runtime_provenance(provenance)
    store.write_run_identity(config, provenance)
    ledger = pilot.AttemptLedger(store)
    _reserve_primary(ledger)
    if state is pilot.AttemptState.SENT:
        ledger.append(
            attempt_id="target.primary",
            target_id="target",
            state=pilot.AttemptState.SENT,
            observed_at=NOW,
            attempt_kind=pilot.AttemptKind.PRIMARY,
            request_sha256="A" * 64,
        )
    return config, store


def _advance_primary_to_state(
    ledger: pilot.AttemptLedger,
    state: pilot.AttemptState,
    *,
    target_id: str = "target",
    attempt_id: str = "target.primary",
) -> None:
    if state is pilot.AttemptState.RESPONSE_CAPTURED:
        ledger.append(
            attempt_id=attempt_id,
            target_id=target_id,
            state=pilot.AttemptState.SENT,
            observed_at=NOW,
            attempt_kind=pilot.AttemptKind.PRIMARY,
            request_sha256="A" * 64,
        )
    ledger.append(
        attempt_id=attempt_id,
        target_id=target_id,
        state=state,
        observed_at=NOW,
        attempt_kind=pilot.AttemptKind.PRIMARY,
        request_sha256="A" * 64,
    )


def _successful_transport(
    selection: pilot.FrozenSelection,
    *,
    before_begin: Callable[[pilot.ProviderRequest], None] | None = None,
) -> pilot.DeterministicFakeTransport:
    steps = []
    for index, item in enumerate(selection.targets, start=1):
        steps.append(
            pilot.FakeTransportStep(
                response=pilot.ProviderResponse(
                    200,
                    _headers(used=index * 10, remaining=1000 - index * 10),
                    _body_for_target(item),
                )
            )
        )
    return pilot.DeterministicFakeTransport(
        steps,
        before_begin=before_begin,
    )


def _reserve_primary(
    ledger: pilot.AttemptLedger,
    target_id: str = "target",
    attempt_id: str = "target.primary",
) -> None:
    ledger.reserve(
        attempt_id=attempt_id,
        target_id=target_id,
        kind=pilot.AttemptKind.PRIMARY,
        request_sha256="A" * 64,
        observed_at=NOW,
    )


def test_frozen_design_identity_verification(selection: pilot.FrozenSelection) -> None:
    assert selection.raw_sha256 == pilot.SELECTION_SHA256
    assert selection.population_sha256 == pilot.POPULATION_SHA256
    assert len(selection.targets) == 20
    assert len(set(selection.target_ids)) == 20


def test_selection_manifest_tamper_rejected(tmp_path: Path) -> None:
    path = tmp_path / "selection.json"
    path.write_bytes(SELECTION_PATH.read_bytes() + b" ")
    with pytest.raises(pilot.EvidenceIntegrityError, match="SHA-256"):
        pilot.load_frozen_selection(path)


def test_authorization_missing(tmp_path: Path, selection: pilot.FrozenSelection) -> None:
    config = _config(tmp_path, selection)
    with pytest.raises(pilot.AuthorizationError, match="missing"):
        pilot.load_and_validate_authorization(
            tmp_path / "missing.json", config=config, selection=selection, now=NOW
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("configuration_sha256", "0" * 64),
        ("protocol", {"identity": "wrong", "sha256": "0" * 64}),
        ("repository", {"head": "f" * 40, "clean": True}),
        ("credential", {"identity": "wrong", "quota_attribution_mode": "DEDICATED_CREDENTIAL"}),
    ],
)
def test_authorization_identity_mismatch(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    field: str,
    replacement: object,
) -> None:
    config = _config(tmp_path, selection)
    payload = _authorization_payload(config, selection)
    payload[field] = replacement
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(pilot.AuthorizationError, match="mismatch"):
        pilot.load_and_validate_authorization(path, config=config, selection=selection, now=NOW)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (NOW + timedelta(minutes=1), NOW + timedelta(minutes=2)),
        (NOW - timedelta(minutes=2), NOW - timedelta(minutes=1)),
    ],
)
def test_authorization_window_rejected(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    start: datetime,
    end: datetime,
) -> None:
    config = _config(tmp_path, selection)
    path = _write_authorization(tmp_path, config, selection, start=start, end=end)
    with pytest.raises(pilot.AuthorizationError, match="outside"):
        pilot.load_and_validate_authorization(path, config=config, selection=selection, now=NOW)


def test_authorization_already_used(tmp_path: Path, selection: pilot.FrozenSelection) -> None:
    config = _config(tmp_path, selection)
    auth = pilot.load_and_validate_authorization(
        _write_authorization(tmp_path, config, selection),
        config=config,
        selection=selection,
        now=NOW,
    )
    store = _store(tmp_path)
    store.claim_authorization(auth)
    with pytest.raises(pilot.EvidenceCollisionError):
        store.claim_authorization(auth)


def test_secret_free_canonical_request(target: pilot.FrozenTarget) -> None:
    request = pilot.provider_request(target)
    assert TEST_SECRET.encode() not in request.canonical_bytes
    assert b"apiKey" not in request.canonical_bytes
    assert request.redacted_as_sent_url.endswith("apiKey=%5BREDACTED%5D")


def test_secret_redaction() -> None:
    result = pilot.redact_headers(
        {
            "Authorization": TEST_SECRET,
            "X-API-Key": TEST_SECRET,
            "X-Diagnostic": f"prefix-{TEST_SECRET}-suffix",
            "Accept": "json",
        },
        secret_values=(TEST_SECRET,),
    )
    assert TEST_SECRET not in json.dumps(result)
    assert result["authorization"] == "[REDACTED]"


def test_durable_reservation_exists_before_fake_send(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    auth = _write_authorization(tmp_path, config, selection)
    ledger_path = Path(config.evidence_store_root) / "ledger" / "attempts.jsonl"

    def assertion(_request: pilot.ProviderRequest) -> None:
        assert ledger_path.exists()
        assert json.loads(ledger_path.read_bytes().splitlines()[-1])["state"] == "RESERVED"

    transport = pilot.DeterministicFakeTransport(
        [
            pilot.FakeTransportStep(
                receive_failure=pilot.PossibleSendFailure(
                    pilot.ReceiveFailureKind.PARTIAL_RESPONSE
                )
            )
        ],
        before_begin=assertion,
    )
    report = pilot.PilotExecutor(
        selection=selection,
        config=config,
        authorization_path=auth,
        transport=transport,
        credential=pilot.SecretCredential(TEST_SECRET),
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).run()
    assert report.disposition is pilot.PilotDisposition.FAILED


@pytest.mark.parametrize("state", [pilot.AttemptState.RESERVED, pilot.AttemptState.SENT])
def test_crash_recovery_marks_ambiguous_attempt_sent_unknown(
    tmp_path: Path, state: pilot.AttemptState
) -> None:
    ledger = pilot.AttemptLedger(_store(tmp_path))
    _reserve_primary(ledger)
    if state is pilot.AttemptState.SENT:
        ledger.append(
            attempt_id="target.primary", target_id="target", state=state,
            observed_at=NOW, attempt_kind=pilot.AttemptKind.PRIMARY,
            request_sha256="A" * 64,
        )
    assert ledger.recover_incomplete(now=NOW + timedelta(seconds=1)) == ("target.primary",)
    assert ledger.current_states()["target.primary"] is pilot.AttemptState.SENT_UNKNOWN


@pytest.mark.parametrize(
    "state",
    [
        pilot.AttemptState.PROVABLE_PRE_SEND_FAILURE,
        pilot.AttemptState.RESPONSE_CAPTURED,
        pilot.AttemptState.SENT_UNKNOWN,
        pilot.AttemptState.TERMINAL_STOP,
    ],
)
def test_restart_does_not_resume_completed_or_terminal_state(
    tmp_path: Path, state: pilot.AttemptState
) -> None:
    ledger = pilot.AttemptLedger(_store(tmp_path))
    _reserve_primary(ledger)
    if state is pilot.AttemptState.RESPONSE_CAPTURED:
        ledger.append(
            attempt_id="target.primary", target_id="target",
            state=pilot.AttemptState.SENT, observed_at=NOW,
            attempt_kind=pilot.AttemptKind.PRIMARY, request_sha256="A" * 64,
        )
    ledger.append(
        attempt_id="target.primary", target_id="target", state=state,
        observed_at=NOW, attempt_kind=pilot.AttemptKind.PRIMARY,
        request_sha256="A" * 64,
    )
    assert ledger.recover_incomplete(now=NOW + timedelta(seconds=1)) == ()
    assert ledger.current_states()["target.primary"] is state


def test_sent_unknown_has_no_retry_path(tmp_path: Path) -> None:
    ledger = pilot.AttemptLedger(_store(tmp_path))
    _reserve_primary(ledger)
    ledger.append(
        attempt_id="target.primary", target_id="target", state=pilot.AttemptState.SENT_UNKNOWN,
        observed_at=NOW, attempt_kind=pilot.AttemptKind.PRIMARY,
        request_sha256="A" * 64, details={"reason": "possible_send"},
    )
    with pytest.raises(pilot.TerminalPilotError, match="not eligible"):
        ledger.reserve(
            attempt_id="target.retry", target_id="target", kind=pilot.AttemptKind.RETRY,
            request_sha256="A" * 64, observed_at=NOW,
            predecessor_attempt_id="target.primary",
        )


@pytest.mark.parametrize("kind", list(pilot.PreSendFailureKind))
def test_provable_pre_send_failure_is_retry_eligible(
    tmp_path: Path, kind: pilot.PreSendFailureKind
) -> None:
    ledger = pilot.AttemptLedger(_store(tmp_path))
    _reserve_primary(ledger)
    ledger.append(
        attempt_id="target.primary", target_id="target",
        state=pilot.AttemptState.PROVABLE_PRE_SEND_FAILURE,
        observed_at=NOW, attempt_kind=pilot.AttemptKind.PRIMARY,
        request_sha256="A" * 64,
        details={"reason": kind.value, "retry_permitted": True},
    )
    ledger.reserve(
        attempt_id="target.retry", target_id="target", kind=pilot.AttemptKind.RETRY,
        request_sha256="A" * 64, observed_at=NOW,
        predecessor_attempt_id="target.primary",
    )
    assert ledger.counters() == pilot.AttemptCounters(1, 1, 2, 20)


def test_second_retry_prohibited(tmp_path: Path) -> None:
    ledger = pilot.AttemptLedger(_store(tmp_path))
    _reserve_primary(ledger)
    ledger.append(
        attempt_id="target.primary", target_id="target",
        state=pilot.AttemptState.PROVABLE_PRE_SEND_FAILURE,
        observed_at=NOW, attempt_kind=pilot.AttemptKind.PRIMARY,
        request_sha256="A" * 64, details={"retry_permitted": True},
    )
    ledger.reserve(
        attempt_id="target.retry", target_id="target", kind=pilot.AttemptKind.RETRY,
        request_sha256="A" * 64, observed_at=NOW,
        predecessor_attempt_id="target.primary",
    )
    ledger.append(
        attempt_id="target.retry", target_id="target",
        state=pilot.AttemptState.PROVABLE_PRE_SEND_FAILURE,
        observed_at=NOW, attempt_kind=pilot.AttemptKind.RETRY,
        request_sha256="A" * 64, predecessor_attempt_id="target.primary",
        details={"retry_permitted": True},
    )
    with pytest.raises(pilot.TerminalPilotError, match="second retry"):
        ledger.reserve(
            attempt_id="target.retry2", target_id="target", kind=pilot.AttemptKind.RETRY,
            request_sha256="A" * 64, observed_at=NOW,
            predecessor_attempt_id="target.retry",
        )


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (200, pilot.CompleteResponseAction.CONTINUE),
        (204, pilot.CompleteResponseAction.TERMINAL),
        (302, pilot.CompleteResponseAction.TERMINAL),
        (400, pilot.CompleteResponseAction.TERMINAL),
        (408, pilot.CompleteResponseAction.RETRY),
        (429, pilot.CompleteResponseAction.RETRY),
        (500, pilot.CompleteResponseAction.RETRY),
        (599, pilot.CompleteResponseAction.RETRY),
    ],
)
def test_complete_response_taxonomy(status: int, action: pilot.CompleteResponseAction) -> None:
    headers = {"Retry-After": "3"} if status == 429 else {}
    assert pilot.classify_complete_response(status, headers)[0] is action


@pytest.mark.parametrize("headers", [{}, {"Retry-After": "bad"}, {"Retry-After": "-1"}])
def test_429_requires_valid_retry_after(headers: dict[str, str]) -> None:
    with pytest.raises(pilot.TerminalPilotError, match="Retry-After"):
        pilot.classify_complete_response(429, headers)


def test_retry_after_is_deterministic() -> None:
    action, delay, _reason = pilot.classify_complete_response(429, {"Retry-After": "17"})
    assert action is pilot.CompleteResponseAction.RETRY
    assert delay == 17


def test_ordinary_and_zero_credit_quota() -> None:
    first = pilot.reconcile_quota(_headers(), previous=None, empty_data=False)
    assert first == pilot.QuotaSnapshot(10, 90, 10)
    second = pilot.reconcile_quota(
        _headers(used=10, remaining=90, last=0), previous=first, empty_data=True
    )
    assert second == pilot.QuotaSnapshot(10, 90, 0)


def test_valid_empty_no_data_response(target: pilot.FrozenTarget) -> None:
    analysis = pilot.parse_success_response(_empty_body(target), target=target)
    assert analysis.empty_data is True
    assert analysis.target_found is False
    assert pilot.reconcile_quota(
        _headers(used=0, remaining=100, last=0),
        previous=None,
        empty_data=analysis.empty_data,
    ).last == 0


@pytest.mark.parametrize(
    ("headers", "previous", "empty"),
    [
        (_headers(last=11), None, False),
        ({"x-requests-used": "10"}, None, False),
        (_headers(used=25, remaining=80, last=10), pilot.QuotaSnapshot(10, 90, 10), False),
        (_headers(used=10, remaining=90, last=0), None, False),
    ],
)
def test_quota_integrity_failures(
    headers: dict[str, str], previous: pilot.QuotaSnapshot | None, empty: bool
) -> None:
    with pytest.raises(pilot.QuotaIntegrityError):
        pilot.reconcile_quota(headers, previous=previous, empty_data=empty)


def test_restart_rebuilds_reservation_counters(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = pilot.AttemptLedger(store)
    _reserve_primary(first)
    assert pilot.AttemptLedger(store).counters() == pilot.AttemptCounters(1, 0, 1, 10)


def test_all_40_reservations_and_41st_rejection(tmp_path: Path) -> None:
    ledger = pilot.AttemptLedger(_store(tmp_path))
    for index in range(20):
        target_id = f"target-{index}"
        primary = f"{target_id}.primary"
        _reserve_primary(ledger, target_id, primary)
        ledger.append(
            attempt_id=primary, target_id=target_id,
            state=pilot.AttemptState.PROVABLE_PRE_SEND_FAILURE,
            observed_at=NOW, attempt_kind=pilot.AttemptKind.PRIMARY,
            request_sha256="A" * 64, details={"retry_permitted": True},
        )
        ledger.reserve(
            attempt_id=f"{target_id}.retry", target_id=target_id,
            kind=pilot.AttemptKind.RETRY, request_sha256="A" * 64,
            observed_at=NOW, predecessor_attempt_id=primary,
        )
    assert ledger.counters() == pilot.AttemptCounters(20, 20, 40, 400)
    with pytest.raises(pilot.TerminalPilotError, match="ceiling"):
        ledger.reserve(
            attempt_id="forty-one.primary", target_id="forty-one",
            kind=pilot.AttemptKind.PRIMARY, request_sha256="A" * 64,
            observed_at=NOW,
        )


def test_raw_body_hash_and_immutable_collision(tmp_path: Path, target: pilot.FrozenTarget) -> None:
    store = _store(tmp_path)
    response = _response(target)
    metadata = store.write_response(
        "attempt", response=response, decoded_body=response.body, received_at=NOW
    )
    assert metadata["body_sha256"] == sha256(response.body).hexdigest().upper()
    with pytest.raises(pilot.EvidenceCollisionError):
        store.write_response(
            "attempt", response=response, decoded_body=response.body, received_at=NOW
        )


@pytest.mark.parametrize(
    "market_last",
    [None, "", 7, "not-a-time", "2021-11-07T16:54:00"],
)
def test_market_timestamp_deficiency_is_localized(
    target: pilot.FrozenTarget, market_last: object
) -> None:
    analysis = pilot.parse_success_response(
        _body(target, market_last=market_last), target=target
    )
    observation = analysis.observations[0]
    assert observation.classification == "MARKET_TIMESTAMP_FIELD_MISSING_OR_INVALID"
    assert observation.timestamp_eligible is False
    assert observation.bookmaker_last_update == "2099-01-01T00:00:00Z"
    assert analysis.revision_required is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"wrapper": "2021-11-07T17:00:00.001Z"}, "after requested_date"),
        ({"market_last": "2021-11-07T17:00:00.001Z"}, "after requested_date"),
        ({"market_last": "2021-11-07T16:56:00Z"}, "after response timestamp"),
        ({"previous": "2021-11-07T16:55:00Z"}, "ordering"),
        ({"following": "2021-11-07T17:00:00Z"}, "ordering"),
    ],
)
def test_timestamp_invariants(
    target: pilot.FrozenTarget, kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(pilot.TerminalPilotError, match=message):
        pilot.parse_success_response(_body(target, **kwargs), target=target)


def test_timestamp_equality_and_integer_millisecond_age(target: pilot.FrozenTarget) -> None:
    analysis = pilot.parse_success_response(
        _body(
            target,
            wrapper="2021-11-07T17:00:00Z",
            previous="2021-11-07T16:59:59.999Z",
            following="2021-11-07T17:00:00.001Z",
            market_last="2021-11-07T16:59:59.999Z",
        ),
        target=target,
    )
    assert analysis.observations[0].snapshot_age_ms == 1
    assert analysis.observations[0].market_minus_response_ms == -1
    assert analysis.observations[0].age_bin == "[0,5m]"
    assert analysis.response_snapshot_age_ms == 0
    assert analysis.previous_interval_ms == 1
    assert analysis.next_interval_ms == 1


def test_wrapper_adjacent_nulls_are_retained(target: pilot.FrozenTarget) -> None:
    analysis = pilot.parse_success_response(
        _body(target, previous=None, following=None), target=target
    )
    assert analysis.previous_timestamp is None
    assert analysis.next_timestamp is None


def test_missing_wrapper_adjacent_field_is_terminal(target: pilot.FrozenTarget) -> None:
    payload = json.loads(_body(target))
    del payload["previous_timestamp"]
    with pytest.raises(pilot.TerminalPilotError, match="missing"):
        pilot.parse_success_response(json.dumps(payload).encode(), target=target)


def test_malformed_top_level_json(target: pilot.FrozenTarget) -> None:
    with pytest.raises(pilot.TerminalPilotError, match="unparsable"):
        pilot.parse_success_response(b"{", target=target)


def test_content_decoding_and_undecodable_body(target: pilot.FrozenTarget) -> None:
    body = _body(target)
    compressed = pilot.ProviderResponse(200, {"Content-Encoding": "gzip"}, gzip.compress(body))
    assert pilot.decode_application_body(compressed) == body
    with pytest.raises(pilot.TerminalPilotError, match="undecodable"):
        pilot.decode_application_body(
            pilot.ProviderResponse(200, {"Content-Encoding": "gzip"}, b"not-gzip")
        )


def test_lexical_decimal_price_preservation(target: pilot.FrozenTarget) -> None:
    analysis = pilot.parse_success_response(
        _body(target, price_token="1.9100"), target=target
    )
    assert analysis.observations[0].prices[0][1] == "1.9100"


def test_target_identification_and_non_target_exclusion(target: pilot.FrozenTarget) -> None:
    non_target = {
        "id": "other",
        "sport_key": pilot.EXPECTED_SPORT,
        "commence_time": "2021-11-07T20:00:00Z",
        "home_team": "New York Jets",
        "away_team": "Buffalo Bills",
        "bookmakers": [],
    }
    analysis = pilot.parse_success_response(
        _body(target, extra_events=[non_target]), target=target
    )
    assert analysis.target_event_id == "synthetic-provider-event"
    assert analysis.non_target_event_count == 1


def test_ambiguous_target_rejected(target: pilot.FrozenTarget) -> None:
    duplicate = json.loads(_body(target))["data"][0]
    with pytest.raises(pilot.IdentityError, match="multiple"):
        pilot.parse_success_response(
            _body(target, extra_events=[duplicate]), target=target
        )


@pytest.mark.parametrize(
    "field", ["final_score", "winner", "model_probability", "roi", "wagers"]
)
def test_prohibited_data_exposure_rejected(target: pilot.FrozenTarget, field: str) -> None:
    with pytest.raises(pilot.ProhibitedDataError):
        pilot.parse_success_response(
            _body(target, prohibited=(field, "forbidden")), target=target
        )


def test_procedural_disposition_floor(target: pilot.FrozenTarget) -> None:
    deficient = pilot.parse_success_response(_body(target, market_last=None), target=target)
    report = pilot.build_report(
        [pilot.TargetExecutionResult(target.canonical_game_id, False, 0, deficient, None)]
    )
    assert report.disposition is pilot.PilotDisposition.REVISION_REQUIRED


def test_evidence_manifest_tamper_and_missing_detection(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    auth = pilot.load_and_validate_authorization(
        _write_authorization(tmp_path, config, selection),
        config=config,
        selection=selection,
        now=NOW,
    )
    store = _store(tmp_path)
    store.claim_authorization(auth)
    provenance = _provenance(tmp_path, config)
    store.write_runtime_provenance(provenance)
    store.write_run_identity(config, provenance)
    report_path = store.write_report(pilot.PilotReport(pilot.PilotDisposition.SUFFICIENT, (), None))
    manifest = pilot.create_evidence_manifest(
        store, authorization=auth, config=config, report_path=report_path
    )
    pilot.verify_evidence_manifest(store, manifest)
    report_path.write_bytes(b"tampered")
    with pytest.raises(pilot.EvidenceIntegrityError, match="size/SHA"):
        pilot.verify_evidence_manifest(store, manifest)
    report_path.unlink()
    with pytest.raises(pilot.EvidenceIntegrityError, match="missing or extra"):
        pilot.verify_evidence_manifest(store, manifest)


def test_single_flight_enforcement(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.acquire_lease("auth-one")
    try:
        with pytest.raises(pilot.AuthorizationError, match="already held"):
            store.acquire_lease("auth-two")
    finally:
        first.close()


def test_authorization_mutation_detected(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    path = _write_authorization(tmp_path, config, selection)
    auth = pilot.load_and_validate_authorization(
        path, config=config, selection=selection, now=NOW
    )
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(pilot.AuthorizationError, match="changed"):
        auth.validate_unchanged()


def test_evidence_store_must_be_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    with pytest.raises(ValueError, match="outside"):
        pilot.EvidenceStore(repository / "evidence", repository_root=repository)


def test_fake_transport_never_retains_credential(target: pilot.FrozenTarget) -> None:
    transport = pilot.DeterministicFakeTransport(
        [pilot.FakeTransportStep(response=_response(target))]
    )
    exchange = transport.begin(
        pilot.provider_request(target), pilot.SecretCredential(TEST_SECRET)
    )
    assert exchange.receive().status_code == 200
    assert TEST_SECRET not in repr(transport.__dict__)


def test_http_200_provider_error_body_is_schema_failure(target: pilot.FrozenTarget) -> None:
    with pytest.raises(pilot.TerminalPilotError):
        pilot.parse_success_response(b'{"message":"provider error"}', target=target)


def test_execution_window_retry_projection() -> None:
    action, delay, _ = pilot.classify_complete_response(429, {"Retry-After": "60"})
    assert action is pilot.CompleteResponseAction.RETRY
    assert NOW + timedelta(seconds=delay) >= NOW + timedelta(seconds=30)


def test_one_xx_is_sent_unknown_without_retry(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    transport = pilot.DeterministicFakeTransport(
        [pilot.FakeTransportStep(response=pilot.ProviderResponse(100, {}, b""))]
    )
    report = pilot.PilotExecutor(
        selection=selection,
        config=config,
        authorization_path=auth_path,
        transport=transport,
        credential=pilot.SecretCredential(TEST_SECRET),
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).run()
    assert report.disposition is pilot.PilotDisposition.FAILED
    ledger = pilot.AttemptLedger(
        pilot.EvidenceStore(
            Path(config.evidence_store_root),
            repository_root=tmp_path / "repository",
        )
    )
    assert list(ledger.current_states().values()) == [pilot.AttemptState.SENT_UNKNOWN]
    assert len(transport.requests) == 1


def test_retry_that_would_cross_execution_window_is_terminal(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(
        tmp_path,
        config,
        selection,
        end=NOW + timedelta(seconds=30),
    )
    transport = pilot.DeterministicFakeTransport(
        [
            pilot.FakeTransportStep(
                response=pilot.ProviderResponse(
                    429,
                    _headers(**{"Retry-After": "30"}),
                    b'{"synthetic":"rate-limit"}',
                )
            )
        ]
    )
    report = pilot.PilotExecutor(
        selection=selection,
        config=config,
        authorization_path=auth_path,
        transport=transport,
        credential=pilot.SecretCredential(TEST_SECRET),
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).run()
    assert report.disposition is pilot.PilotDisposition.FAILED
    assert report.terminal_reason == "retry_window_or_count_exhausted"
    assert len(transport.requests) == 1


def test_fake_execution_uses_no_network_and_redacts_secret(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    response = pilot.ProviderResponse(
        500,
        _headers(**{"X-API-Key": "SYNTHETIC_HEADER_VALUE"}),
        b'{"synthetic":"error"}',
    )
    transport = pilot.DeterministicFakeTransport(
        [
            pilot.FakeTransportStep(response=response),
            pilot.FakeTransportStep(
                receive_failure=pilot.PossibleSendFailure(
                    pilot.ReceiveFailureKind.RESET_AFTER_SEND
                )
            ),
        ]
    )
    clock = MutableClock()
    report = pilot.PilotExecutor(
        selection=selection,
        config=config,
        authorization_path=auth_path,
        transport=transport,
        credential=pilot.SecretCredential(TEST_SECRET),
        repository_root=tmp_path / "repository",
        clock=clock,
    ).run()
    assert report.disposition is pilot.PilotDisposition.FAILED
    evidence = Path(config.evidence_store_root)
    assert all(
        TEST_SECRET.encode() not in path.read_bytes()
        for path in evidence.rglob("*")
        if path.is_file()
    )
    assert len(transport.requests) == 2


def test_secret_echo_response_is_not_persisted(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    transport = pilot.DeterministicFakeTransport(
        [
            pilot.FakeTransportStep(
                response=pilot.ProviderResponse(
                    200,
                    _headers(),
                    f'{{"echo":"{TEST_SECRET}"}}'.encode(),
                )
            )
        ]
    )
    report = pilot.PilotExecutor(
        selection=selection,
        config=config,
        authorization_path=auth_path,
        transport=transport,
        credential=pilot.SecretCredential(TEST_SECRET),
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).run()
    assert report.disposition is pilot.PilotDisposition.FAILED
    evidence = Path(config.evidence_store_root)
    assert all(
        TEST_SECRET.encode() not in path.read_bytes()
        for path in evidence.rglob("*")
        if path.is_file()
    )


def test_full_twenty_target_fake_run_is_procedurally_sufficient(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    responses = []
    for index, item in enumerate(selection.targets, start=1):
        responses.append(
            pilot.FakeTransportStep(
                response=pilot.ProviderResponse(
                    200,
                    _headers(used=index * 10, remaining=1000 - index * 10),
                    _body_for_target(item),
                )
            )
        )
    transport = pilot.DeterministicFakeTransport(responses)
    report = pilot.PilotExecutor(
        selection=selection,
        config=config,
        authorization_path=auth_path,
        transport=transport,
        credential=pilot.SecretCredential(TEST_SECRET),
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).run()
    assert report.disposition is pilot.PilotDisposition.SUFFICIENT
    assert len(report.target_results) == 20
    assert len(transport.requests) == 20
    assert all(
        item.analysis is not None and item.analysis.target_found
        for item in report.target_results
    )


def test_runtime_config_rejects_dirty_tree(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = replace(_config(tmp_path, selection), repository_clean=False)
    with pytest.raises(pilot.AuthorizationError, match="clean"):
        pilot.validate_runtime_config(config, selection)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("git_head", "f" * 40),
        ("git_clean", False),
        ("implementation_source_sha256", "C" * 64),
    ],
)
def test_measured_repository_identity_mismatch_fails_before_transport(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    provenance = replace(_provenance(tmp_path, config), **{field: value})
    monkeypatch.setattr(
        pilot.LocalRuntimeProvenanceInspector,
        "inspect",
        lambda _self, **_kwargs: provenance,
    )
    transport = pilot.DeterministicFakeTransport([])
    with pytest.raises(pilot.AuthorizationError, match="measured runtime"):
        _executor(
            tmp_path,
            selection,
            config,
            auth_path,
            transport,
        ).run()
    assert transport.requests == []


def test_wrong_injected_credential_fingerprint_fails_before_transport(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    transport = pilot.DeterministicFakeTransport([])
    with pytest.raises(pilot.AuthorizationError, match="credential fingerprint"):
        _executor(
            tmp_path,
            selection,
            config,
            auth_path,
            transport,
            credential=pilot.SecretCredential("WRONG_TEST_KEY_DO_NOT_SEND"),
        ).run()
    assert transport.requests == []


def test_credential_fingerprint_is_domain_separated_and_secret_free() -> None:
    credential = pilot.SecretCredential(TEST_SECRET)
    assert credential.fingerprint == sha256(
        pilot.CREDENTIAL_FINGERPRINT_DOMAIN + TEST_SECRET.encode()
    ).hexdigest().upper()
    assert TEST_SECRET not in credential.fingerprint
    assert len(credential.fingerprint) == 64


def test_runtime_transport_identity_mismatch(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = replace(_config(tmp_path, selection), transport_identity="UNPINNED")
    auth_path = _write_authorization(tmp_path, config, selection)
    transport = pilot.DeterministicFakeTransport([])
    with pytest.raises(pilot.AuthorizationError, match="transport runtime"):
        _executor(tmp_path, selection, config, auth_path, transport).run()


def test_runtime_clock_identity_mismatch(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = replace(_config(tmp_path, selection), clock_identity="OTHER_CLOCK")
    auth_path = _write_authorization(tmp_path, config, selection)
    transport = pilot.DeterministicFakeTransport([])
    with pytest.raises(pilot.AuthorizationError, match="clock runtime"):
        _executor(tmp_path, selection, config, auth_path, transport).run()


def test_invalid_runtime_provenance_is_not_ready(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    provenance = replace(
        _provenance(tmp_path, config),
        os_sync_status="UNVERIFIED",
    )
    monkeypatch.setattr(
        pilot.LocalRuntimeProvenanceInspector,
        "inspect",
        lambda _self, **_kwargs: provenance,
    )
    with pytest.raises(pilot.AuthorizationError, match="measured runtime"):
        _executor(
            tmp_path,
            selection,
            config,
            auth_path,
            pilot.DeterministicFakeTransport([]),
        ).run()


def test_executor_has_no_runtime_inspector_injection_surface(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    parameters = inspect.signature(pilot.PilotExecutor).parameters
    assert "runtime_inspector" not in parameters
    config = _config(tmp_path, selection)
    with pytest.raises(TypeError, match="runtime_inspector"):
        pilot.PilotExecutor(
            selection=selection,
            config=config,
            authorization_path=tmp_path / "unused_authorization.json",
            transport=pilot.DeterministicFakeTransport([]),
            credential=pilot.SecretCredential(TEST_SECRET),
            repository_root=tmp_path / "repository",
            clock=MutableClock(),
            runtime_inspector=object(),  # type: ignore[call-arg]
        )


def test_executor_uses_reviewed_local_inspector_before_provider_boundary(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, selection)
    authorization_path = _write_authorization(tmp_path, config, selection)
    inspected = False

    def inspect_runtime(
        inspector: pilot.LocalRuntimeProvenanceInspector, **_kwargs: object
    ) -> pilot.RuntimeProvenance:
        nonlocal inspected
        inspected = True
        return replace(
            _provenance(tmp_path, config),
            repository_root=str(inspector.repository_root),
        )

    def assert_inspected(_request: pilot.ProviderRequest) -> None:
        assert inspected is True

    monkeypatch.setattr(
        pilot.LocalRuntimeProvenanceInspector, "inspect", inspect_runtime
    )
    transport = pilot.DeterministicFakeTransport(
        [
            pilot.FakeTransportStep(
                receive_failure=pilot.PossibleSendFailure(
                    pilot.ReceiveFailureKind.PARTIAL_RESPONSE
                )
            )
        ],
        before_begin=assert_inspected,
    )
    report = _executor(
        tmp_path, selection, config, authorization_path, transport
    ).run()
    assert report.disposition is pilot.PilotDisposition.FAILED
    retained = json.loads(
        (Path(config.evidence_store_root) / "runtime_provenance.json").read_bytes()
    )
    assert retained["runtime_inspector_identity"] == pilot.RUNTIME_INSPECTOR_ID
    assert retained["phase_offset_evidence"] == "0.0000000s"
    assert retained["last_successful_sync_evidence"] == "2026-10-01T11:59:00Z"


def test_dynamic_clock_evidence_is_captured_but_not_configuration_bound(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    assert "phase_offset_evidence" not in config.canonical_payload()
    assert "last_successful_sync_evidence" not in config.canonical_payload()
    original_hash = config.sha256
    transport = pilot.DeterministicFakeTransport([])
    clock = MutableClock()
    for phase_offset, last_sync in (
        ("-0.0000123s", "2026-10-01T11:59:00Z"),
        ("0.0000456s", "10/01/2026 12:00:30 PM"),
    ):
        provenance = replace(
            _provenance(tmp_path, config),
            phase_offset_evidence=phase_offset,
            last_successful_sync_evidence=last_sync,
        )
        pilot.validate_measured_runtime(
            provenance,
            config=config,
            repository_root=tmp_path / "repository",
            transport=transport,
            clock=clock,
            credential=pilot.SecretCredential(TEST_SECRET),
        )
    assert config.sha256 == original_hash


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase_offset_evidence", "not-an-offset"),
        ("phase_offset_evidence", ""),
        ("last_successful_sync_evidence", "not-a-time"),
        ("last_successful_sync_evidence", ""),
    ],
)
def test_execution_rejects_missing_or_malformed_dynamic_clock_evidence(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    field: str,
    value: str,
) -> None:
    config = _config(tmp_path, selection)
    provenance = replace(_provenance(tmp_path, config), **{field: value})
    with pytest.raises(pilot.AuthorizationError, match="evidence is invalid"):
        pilot.validate_measured_runtime(
            provenance,
            config=config,
            repository_root=tmp_path / "repository",
            transport=pilot.DeterministicFakeTransport([]),
            clock=MutableClock(),
            credential=pilot.SecretCredential(TEST_SECRET),
        )


def test_initial_nonempty_evidence_store_rejected(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    evidence = Path(config.evidence_store_root)
    evidence.mkdir(parents=True)
    (evidence / "unrelated.txt").write_text("not governed", encoding="utf-8")
    auth_path = _write_authorization(tmp_path, config, selection)
    transport = pilot.DeterministicFakeTransport([])
    with pytest.raises(pilot.EvidenceIntegrityError, match="dedicated and empty"):
        _executor(tmp_path, selection, config, auth_path, transport).run()
    assert transport.requests == []


def test_recovery_accepts_only_governed_existing_store(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    evidence = Path(config.evidence_store_root)
    evidence.mkdir(parents=True)
    (evidence / "random.bin").write_bytes(b"not governed")
    with pytest.raises(pilot.EvidenceIntegrityError, match="incomplete"):
        pilot.PilotRecovery(
            selection=selection,
            config=config,
            repository_root=tmp_path / "repository",
            clock=MutableClock(),
        ).recover()


@pytest.mark.parametrize(
    "state", [pilot.AttemptState.RESERVED, pilot.AttemptState.SENT]
)
def test_recovery_only_converts_incomplete_attempt_to_sent_unknown(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    state: pilot.AttemptState,
) -> None:
    config, store = _create_interrupted_store(tmp_path, selection, state)
    report = pilot.PilotRecovery(
        selection=selection,
        config=config,
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).recover()
    assert report.disposition is pilot.PilotDisposition.FAILED
    assert pilot.AttemptLedger(store).current_states()["target.primary"] is (
        pilot.AttemptState.SENT_UNKNOWN
    )
    record = json.loads((store.root / "recovery" / "recovery_record.json").read_bytes())
    assert record["continuation_supported"] is False
    assert record["counters"]["reserved_credits"] == 10
    original_path = store.root / "runtime_provenance.json"
    recovery_path = store.root / "recovery" / "runtime_provenance.json"
    assert record["original_runtime_provenance_sha256"] == sha256(
        original_path.read_bytes()
    ).hexdigest().upper()
    assert record["recovery_runtime_provenance_sha256"] == sha256(
        recovery_path.read_bytes()
    ).hexdigest().upper()
    manifest = json.loads((store.root / "evidence_manifest.json").read_bytes())
    assert manifest["runtime_attribution"]["original_execution"] == {
        "implementation_identity": pilot.IMPLEMENTATION_ID,
        "runtime_provenance_path": "runtime_provenance.json",
        "runtime_provenance_sha256": record["original_runtime_provenance_sha256"],
    }
    assert manifest["runtime_attribution"]["recovery"] == {
        "implementation_identity": pilot.IMPLEMENTATION_ID,
        "runtime_provenance_path": "recovery/runtime_provenance.json",
        "runtime_provenance_sha256": record["recovery_runtime_provenance_sha256"],
    }


@pytest.mark.parametrize(
    "terminal_state",
    [
        pilot.AttemptState.RESPONSE_CAPTURED,
        pilot.AttemptState.SENT_UNKNOWN,
        pilot.AttemptState.TERMINAL_STOP,
    ],
)
def test_recovery_terminalizes_unmanifested_store_without_incomplete_attempts(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    terminal_state: pilot.AttemptState,
) -> None:
    config, store = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    ledger = pilot.AttemptLedger(store)
    _advance_primary_to_state(ledger, terminal_state)
    original_path = store.root / "runtime_provenance.json"
    original_before = original_path.read_bytes()

    report = pilot.PilotRecovery(
        selection=selection,
        config=config,
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).recover()

    assert report.disposition is pilot.PilotDisposition.FAILED
    assert report.terminal_reason == "crash_recovery_no_continuation_supported"
    record = json.loads((store.root / "recovery" / "recovery_record.json").read_bytes())
    assert record["recovered_attempt_ids"] == []
    assert original_path.read_bytes() == original_before
    assert (store.root / "recovery" / "runtime_provenance.json").is_file()
    manifest_path = store.root / "evidence_manifest.json"
    pilot.verify_evidence_manifest(store, manifest_path)
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["runtime_attribution"]["original_execution"] is not None
    assert manifest["runtime_attribution"]["recovery"] is not None
    terminal_report = json.loads(
        (store.root / "reports" / "recovery_terminal_report.json").read_bytes()
    )
    assert terminal_report["disposition"] == pilot.PilotDisposition.FAILED.value


def test_recovery_terminalizes_all_twenty_captured_before_manifest(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    authorization = pilot.load_and_validate_authorization(
        _write_authorization(tmp_path, config, selection),
        config=config,
        selection=selection,
        now=NOW,
    )
    store = _store(tmp_path)
    provenance = _provenance(tmp_path, config)
    store.claim_authorization(authorization)
    store.write_runtime_provenance(provenance)
    store.write_run_identity(config, provenance)
    ledger = pilot.AttemptLedger(store)
    for target in selection.targets:
        attempt_id = f"{target.canonical_game_id}.primary"
        _reserve_primary(
            ledger,
            target_id=target.canonical_game_id,
            attempt_id=attempt_id,
        )
        _advance_primary_to_state(
            ledger,
            pilot.AttemptState.RESPONSE_CAPTURED,
            target_id=target.canonical_game_id,
            attempt_id=attempt_id,
        )

    report = pilot.PilotRecovery(
        selection=selection,
        config=config,
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).recover()

    assert report.disposition is pilot.PilotDisposition.FAILED
    record = json.loads((store.root / "recovery" / "recovery_record.json").read_bytes())
    assert record["recovered_attempt_ids"] == []
    assert record["counters"] == {
        "attempts": 20,
        "primary": 20,
        "reserved_credits": 200,
        "retries": 0,
    }
    pilot.verify_evidence_manifest(store, store.root / "evidence_manifest.json")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("git_clean", False),
        ("git_head", "f" * 40),
        ("implementation_source_sha256", "C" * 64),
        ("runtime_identity", "OTHER_RUNTIME"),
        ("dependency_identity", "E" * 64),
        ("timezone_identity", "OTHER_TZDATA"),
        ("os_sync_source", "OTHER_SYNC_SOURCE"),
        ("os_sync_status", "UNHEALTHY"),
        ("clock_identity", "OTHER_CLOCK"),
        ("monotonic_timer_identity", "OTHER_MONOTONIC"),
        ("runtime_inspector_identity", "UNREVIEWED_INSPECTOR"),
    ],
)
def test_recovery_runtime_mismatch_fails_before_evidence_mutation(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    config, store = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    ledger_path = store.root / "ledger" / "attempts.jsonl"
    original_path = store.root / "runtime_provenance.json"
    ledger_before = ledger_path.read_bytes()
    original_before = original_path.read_bytes()
    clock = MutableClock()
    good = pilot.RecoveryRuntimeProvenance(
        repository_root=str((tmp_path / "repository").resolve()),
        git_head=config.repository_head,
        git_clean=True,
        implementation_source_sha256=config.implementation_sha256,
        configuration_sha256=config.sha256,
        runtime_identity=config.runtime_identity,
        dependency_identity=config.dependency_identity,
        timezone_identity=config.timezone_identity,
        os_sync_source=config.os_sync_source,
        os_sync_status=config.os_sync_status,
        phase_offset_evidence="0.0000000s",
        last_successful_sync_evidence="2026-10-01T11:59:00Z",
        monotonic_timer_identity=config.monotonic_timer_identity,
        clock_identity=config.clock_identity,
        recovery_mode="RECOVERY_ONLY",
        runtime_inspector_identity=pilot.RUNTIME_INSPECTOR_ID,
    )
    monkeypatch.setattr(
        pilot.LocalRuntimeProvenanceInspector,
        "inspect_recovery",
        lambda _self, **_kwargs: replace(good, **{field: value}),
    )
    with pytest.raises(pilot.AuthorizationError, match="recovery runtime"):
        pilot.PilotRecovery(
            selection=selection,
            config=config,
            repository_root=tmp_path / "repository",
            clock=clock,
        ).recover()
    assert ledger_path.read_bytes() == ledger_before
    assert original_path.read_bytes() == original_before
    assert not (store.root / "recovery").exists()


def test_recovery_preserves_original_runtime_provenance_bytes(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config, store = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    original_path = store.root / "runtime_provenance.json"
    original_before = original_path.read_bytes()
    pilot.PilotRecovery(
        selection=selection,
        config=config,
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).recover()
    assert original_path.read_bytes() == original_before


def test_recovery_retains_fresh_healthy_dynamic_clock_evidence(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, store = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    original = json.loads((store.root / "runtime_provenance.json").read_bytes())
    later_phase = "0.0000678s"
    later_sync = "2026-10-02T08:15:30Z"
    measured = pilot.RecoveryRuntimeProvenance(
        repository_root=str((tmp_path / "repository").resolve()),
        git_head=config.repository_head,
        git_clean=True,
        implementation_source_sha256=config.implementation_sha256,
        configuration_sha256=config.sha256,
        runtime_identity=config.runtime_identity,
        dependency_identity=config.dependency_identity,
        timezone_identity=config.timezone_identity,
        os_sync_source=config.os_sync_source,
        os_sync_status=config.os_sync_status,
        phase_offset_evidence=later_phase,
        last_successful_sync_evidence=later_sync,
        monotonic_timer_identity=config.monotonic_timer_identity,
        clock_identity=config.clock_identity,
        recovery_mode="RECOVERY_ONLY",
        runtime_inspector_identity=pilot.RUNTIME_INSPECTOR_ID,
    )
    monkeypatch.setattr(
        pilot.LocalRuntimeProvenanceInspector,
        "inspect_recovery",
        lambda _self, **_kwargs: measured,
    )
    pilot.PilotRecovery(
        selection=selection,
        config=config,
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).recover()
    recovery = json.loads(
        (store.root / "recovery" / "runtime_provenance.json").read_bytes()
    )
    assert original["phase_offset_evidence"] == "0.0000000s"
    assert original["last_successful_sync_evidence"] == "2026-10-01T11:59:00Z"
    assert recovery["phase_offset_evidence"] == later_phase
    assert recovery["last_successful_sync_evidence"] == later_sync


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase_offset_evidence", "malformed"),
        ("last_successful_sync_evidence", "missing"),
    ],
)
def test_recovery_rejects_malformed_dynamic_clock_evidence_before_mutation(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    config, store = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    original = store.root / "runtime_provenance.json"
    original_before = original.read_bytes()
    measured = pilot.RecoveryRuntimeProvenance(
        repository_root=str((tmp_path / "repository").resolve()),
        git_head=config.repository_head,
        git_clean=True,
        implementation_source_sha256=config.implementation_sha256,
        configuration_sha256=config.sha256,
        runtime_identity=config.runtime_identity,
        dependency_identity=config.dependency_identity,
        timezone_identity=config.timezone_identity,
        os_sync_source=config.os_sync_source,
        os_sync_status=config.os_sync_status,
        phase_offset_evidence="0.0000000s",
        last_successful_sync_evidence="2026-10-02T08:15:30Z",
        monotonic_timer_identity=config.monotonic_timer_identity,
        clock_identity=config.clock_identity,
        recovery_mode="RECOVERY_ONLY",
        runtime_inspector_identity=pilot.RUNTIME_INSPECTOR_ID,
    )
    monkeypatch.setattr(
        pilot.LocalRuntimeProvenanceInspector,
        "inspect_recovery",
        lambda _self, **_kwargs: replace(measured, **{field: value}),
    )
    with pytest.raises(pilot.AuthorizationError, match="evidence is invalid"):
        pilot.PilotRecovery(
            selection=selection,
            config=config,
            repository_root=tmp_path / "repository",
            clock=MutableClock(),
        ).recover()
    assert original.read_bytes() == original_before
    assert not (store.root / "recovery").exists()


def test_recovery_revalidates_after_lease_and_preserves_completed_store(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, store = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    stale_lease = store.acquire_lease("executor-owner")
    stale_lease.close()
    original_acquire = pilot.EvidenceStore.acquire_lease
    completed_snapshot: dict[str, bytes] = {}
    completed_paths: set[str] = set()

    def complete_then_acquire(
        active_store: pilot.EvidenceStore, authorization_id: str
    ) -> pilot.PilotLease:
        ledger = pilot.AttemptLedger(active_store)
        for state in (
            pilot.AttemptState.SENT,
            pilot.AttemptState.RESPONSE_CAPTURED,
        ):
            ledger.append(
                attempt_id="target.primary",
                target_id="target",
                state=state,
                observed_at=NOW,
                attempt_kind=pilot.AttemptKind.PRIMARY,
                request_sha256="A" * 64,
                details={"status_code": 200},
            )
        authorization = pilot.load_and_validate_authorization(
            active_store.root / "authorization.json",
            config=config,
            selection=selection,
            now=NOW,
            require_active_window=False,
        )
        report_path = active_store.write_report(
            pilot.PilotReport(pilot.PilotDisposition.SUFFICIENT, (), None)
        )
        manifest_path = pilot.create_evidence_manifest(
            active_store,
            authorization=authorization,
            config=config,
            report_path=report_path,
        )
        pilot.verify_evidence_manifest(active_store, manifest_path)
        lease = original_acquire(active_store, authorization_id)
        completed_paths.update(
            path.relative_to(active_store.root).as_posix()
            for path in active_store.root.rglob("*")
            if path.is_file()
        )
        completed_snapshot.update(
            {
                path.relative_to(active_store.root).as_posix(): path.read_bytes()
                for path in active_store.root.rglob("*")
                if path.is_file() and path.name != ".pilot.lock"
            }
        )
        return lease

    monkeypatch.setattr(
        pilot.EvidenceStore, "acquire_lease", complete_then_acquire
    )
    with pytest.raises(
        pilot.EvidenceIntegrityError, match="completed or terminal"
    ):
        pilot.PilotRecovery(
            selection=selection,
            config=config,
            repository_root=tmp_path / "repository",
            clock=MutableClock(),
        ).recover()
    after = {
        path.relative_to(store.root).as_posix(): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file() and path.name != ".pilot.lock"
    }
    after_paths = {
        path.relative_to(store.root).as_posix()
        for path in store.root.rglob("*")
        if path.is_file()
    }
    assert after == completed_snapshot
    assert after_paths == completed_paths
    assert not (store.root / "recovery").exists()
    pilot.verify_evidence_manifest(store, store.root / "evidence_manifest.json")


def test_stale_lock_artifact_allows_recovery_after_owner_release(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config, store = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    lease = store.acquire_lease("simulated-crashed-owner")
    lease.close()
    assert (store.root / ".pilot.lock").exists()
    report = pilot.PilotRecovery(
        selection=selection,
        config=config,
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).recover()
    assert report.disposition is pilot.PilotDisposition.FAILED


def test_recovery_closes_crash_after_report_before_manifest(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config, store = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    store.write_report(
        pilot.PilotReport(
            pilot.PilotDisposition.FAILED,
            (),
            "synthetic_pre_manifest_crash",
        )
    )
    report = pilot.PilotRecovery(
        selection=selection,
        config=config,
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).recover()
    assert report.disposition is pilot.PilotDisposition.FAILED
    assert (store.root / "reports" / "pilot_report.json").exists()
    assert (store.root / "reports" / "recovery_terminal_report.json").exists()
    pilot.verify_evidence_manifest(store, store.root / "evidence_manifest.json")


def test_live_owner_blocks_recovery(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config, store = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    lease = store.acquire_lease("live-owner")
    try:
        with pytest.raises(pilot.AuthorizationError, match="already held"):
            pilot.PilotRecovery(
                selection=selection,
                config=config,
                repository_root=tmp_path / "repository",
                clock=MutableClock(),
            ).recover()
    finally:
        lease.close()


def test_recovery_lifecycle_has_no_transport_boundary(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config, _store_value = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    recovery = pilot.PilotRecovery(
        selection=selection,
        config=config,
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    )
    assert not hasattr(recovery, "transport")
    recovery.recover()


def test_terminal_recovered_store_cannot_be_continued(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config, _store_value = _create_interrupted_store(
        tmp_path, selection, pilot.AttemptState.RESERVED
    )
    pilot.PilotRecovery(
        selection=selection,
        config=config,
        repository_root=tmp_path / "repository",
        clock=MutableClock(),
    ).recover()
    transport = pilot.DeterministicFakeTransport([])
    with pytest.raises(pilot.EvidenceIntegrityError, match="dedicated and empty"):
        _executor(
            tmp_path,
            selection,
            config,
            tmp_path / "test_authorization.json",
            transport,
        ).run()
    assert transport.requests == []


def test_fresh_store_rejects_declared_continuation(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    payload = _authorization_payload(config, selection)
    payload["execution_policy"] = {
        "mode": "CONTINUATION",
        "predecessor_evidence_manifest_sha256": "D" * 64,
    }
    path = tmp_path / "continuation_authorization.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    transport = pilot.DeterministicFakeTransport([])
    with pytest.raises(pilot.AuthorizationError, match="continuation is unsupported"):
        _executor(tmp_path, selection, config, path, transport).run()
    assert transport.requests == []


def test_authorization_mutation_during_first_provider_boundary(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)

    def mutate(_request: pilot.ProviderRequest) -> None:
        auth_path.write_bytes(auth_path.read_bytes() + b" ")

    transport = _successful_transport(selection, before_begin=mutate)
    report = _executor(tmp_path, selection, config, auth_path, transport).run()
    assert report.disposition is pilot.PilotDisposition.FAILED
    assert len(transport.requests) == 1


def test_authorization_mutation_during_final_provider_boundary(
    tmp_path: Path, selection: pilot.FrozenSelection
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    calls = 0

    def mutate_final(_request: pilot.ProviderRequest) -> None:
        nonlocal calls
        calls += 1
        if calls == 20:
            auth_path.write_bytes(auth_path.read_bytes() + b" ")

    transport = _successful_transport(selection, before_begin=mutate_final)
    report = _executor(tmp_path, selection, config, auth_path, transport).run()
    assert report.disposition is pilot.PilotDisposition.FAILED
    assert report.disposition is not pilot.PilotDisposition.SUFFICIENT
    assert len(transport.requests) == 20


def test_authorization_mutation_before_report_is_terminal(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    original = pilot.build_report

    def mutate_then_build(results: object) -> pilot.PilotReport:
        auth_path.write_bytes(auth_path.read_bytes() + b" ")
        return original(results)  # type: ignore[arg-type]

    monkeypatch.setattr(pilot, "build_report", mutate_then_build)
    report = _executor(
        tmp_path,
        selection,
        config,
        auth_path,
        _successful_transport(selection),
    ).run()
    assert report.disposition is pilot.PilotDisposition.FAILED


def test_authorization_mutation_before_manifest_acceptance_is_terminal(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    original = pilot.create_evidence_manifest

    def create_then_mutate(*args: object, **kwargs: object) -> Path:
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        auth_path.write_bytes(auth_path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(pilot, "create_evidence_manifest", create_then_mutate)
    report = _executor(
        tmp_path,
        selection,
        config,
        auth_path,
        _successful_transport(selection),
    ).run()
    assert report.disposition is pilot.PilotDisposition.FAILED


def test_io_failure_before_send_performs_no_transport_call(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    transport = _successful_transport(selection)

    def fail_request(*_args: object, **_kwargs: object) -> None:
        raise pilot.EvidenceIOError("synthetic pre-send failure")

    monkeypatch.setattr(pilot.EvidenceStore, "write_attempt_request", fail_request)
    report = _executor(tmp_path, selection, config, auth_path, transport).run()
    assert report.disposition is pilot.PilotDisposition.FAILED
    assert transport.requests == []


def test_io_failure_after_send_becomes_sent_unknown(
    tmp_path: Path,
    selection: pilot.FrozenSelection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, selection)
    auth_path = _write_authorization(tmp_path, config, selection)
    transport = _successful_transport(selection)

    def fail_response(*_args: object, **_kwargs: object) -> object:
        raise pilot.EvidenceIOError("synthetic post-send failure")

    monkeypatch.setattr(pilot.EvidenceStore, "write_response", fail_response)
    report = _executor(tmp_path, selection, config, auth_path, transport).run()
    assert report.disposition is pilot.PilotDisposition.FAILED
    assert len(transport.requests) == 1
    ledger = pilot.AttemptLedger(
        pilot.EvidenceStore(
            Path(config.evidence_store_root),
            repository_root=tmp_path / "repository",
        )
    )
    assert list(ledger.current_states().values()) == [pilot.AttemptState.SENT_UNKNOWN]
