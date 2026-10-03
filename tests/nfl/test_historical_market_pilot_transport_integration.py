"""Synthetic fixtures only; every OS socket/DNS path is killed before testing."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import gzip
import http.client
import inspect
import json
from pathlib import Path
import socket
import ssl

import pytest

from sportsmodel.nfl import historical_market_pilot as core
from sportsmodel.nfl import historical_market_odds_api_transport as transport
from sportsmodel.nfl import historical_market_pilot_integrated as integrated

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
SECRET = "TEST_KEY_DO_NOT_SEND"
SELECTION = core.load_frozen_selection(ROOT / "docs/architecture/nfl_historical_market_provider_pilot_selection_manifest_0.1.3.json")


class Clock:
    value = NOW
    runtime_identity = "SYNTHETIC_CLOCK"
    monotonic_identity = "SYNTHETIC_MONOTONIC"

    def now_utc(self):
        return self.value

    def monotonic_ns(self):
        return int(self.value.timestamp() * 1_000_000_000)

    def sleep(self, seconds):
        self.value += timedelta(seconds=seconds)


def body(target, empty=False):
    stamp = datetime.fromisoformat(target.requested_date.replace("Z", "+00:00"))
    text = lambda d: d.isoformat().replace("+00:00", "Z")
    event = {"id": "SYNTHETIC_EVENT", "sport_key": core.EXPECTED_SPORT,
             "commence_time": target.kickoff_utc,
             "home_team": core.TEAM_PROVIDER_NAMES[target.home_team],
             "away_team": core.TEAM_PROVIDER_NAMES[target.away_team],
             "bookmakers": [{"key": key, "markets": [{"key": "h2h",
                "last_update": text(stamp - timedelta(minutes=6)),
                "outcomes": [{"name": core.TEAM_PROVIDER_NAMES[target.home_team], "price": 1.91},
                             {"name": core.TEAM_PROVIDER_NAMES[target.away_team], "price": 2.05}]}]}
                            for key in core.EXPECTED_BOOKS]}
    return json.dumps({"timestamp": text(stamp - timedelta(minutes=5)),
                       "previous_timestamp": text(stamp - timedelta(minutes=10)),
                       "next_timestamp": text(stamp + timedelta(minutes=5)),
                       "data": [] if empty else [event]}).encode()


class Response:
    chunked = False
    status = 200

    def __init__(self, data, used, last=10, headers=(), status=200):
        self.data, self.used, self.last = data, used, last
        self.extra_headers, self.status = headers, status

    def getheaders(self):
        return [("Content-Type", "application/json"), ("Date", "Thu, 01 Oct 2026 12:00:00 GMT"),
                ("x-requests-used", str(self.used)), ("x-requests-remaining", str(1000 - self.used)),
                ("x-requests-last", str(self.last)), *self.extra_headers]

    def read(self):
        return self.data


class Connection:
    def __init__(self, harness, response):
        self.harness, self.response = harness, response
        self.sock = self
        self.closed = False

    def settimeout(self, seconds):
        self.timeout = seconds

    def connect(self):
        h = self.harness
        entries = h.ledger().entries()
        assert entries[-1]["state"] == "RESERVED"
        assert (h.store / "attempts" / entries[-1]["attempt_id"] / "request.json").exists()
        h.events.append("prepare")
        if h.prepare_hook:
            h.prepare_hook()
        if h.prepare_errors:
            raise h.prepare_errors.pop(0)

    def putrequest(self, method, target, **kwargs):
        assert method == "GET" and f"apiKey={SECRET}" in target
        assert self.harness.events[-1] == "gate"
        if self.harness.buffer_error:
            raise self.harness.buffer_error
        self.harness.events.append("buffer")
        self.harness.buffer_count += 1

    def putheader(self, name, value):
        pass

    def endheaders(self):
        self.harness.events.append("send")
        self.harness.sends += 1
        if self.harness.send_hook:
            self.harness.send_hook()
        if self.harness.send_error:
            raise self.harness.send_error

    def getresponse(self):
        assert self.harness.ledger().entries()[-1]["state"] == "SENT"
        self.harness.events.append("receive")
        if self.harness.receive_error:
            raise self.harness.receive_error
        self.harness.credit_used = self.response.used
        return self.response

    def close(self):
        self.closed = True
        self.harness.events.append("close")


class Harness:
    def __init__(self, tmp_path, monkeypatch):
        self.clock = Clock()
        self.store = tmp_path / "evidence"
        self.events, self.connections = [], []
        self.sends = self.buffer_count = self.credit_used = 0
        self.prepare_hook = self.send_hook = None
        self.prepare_errors = []
        self.send_error = self.receive_error = self.buffer_error = None
        self.responses = []
        credential = core.SecretCredential(SECRET)
        network = transport.OddsApiHistoricalTransport()
        self.config = integrated.IntegratedConfig(
            evidence_store_root=str(self.store), credential_identity="SYNTHETIC_ONLY",
            credential_fingerprint=credential.fingerprint,
            quota_attribution_mode=core.QuotaAttributionMode.DEDICATED_CREDENTIAL,
            implementation_revision="a" * 40,
            implementation_sha256=core._digest(Path(integrated.__file__).read_bytes()),
            repository_head="a" * 40, repository_clean=True,
            clock_identity=core.component_runtime_identity(self.clock),
            monotonic_timer_identity=self.clock.monotonic_identity,
            transport_identity=core.component_runtime_identity(network), runtime_mode=integrated.RUNTIME_MODE,
            runtime_identity="SYNTHETIC_RUNTIME", dependency_identity="D" * 64,
            timezone_identity="SYNTHETIC_TZ", os_sync_source="SYNTHETIC_SOURCE",
            os_sync_status="SYNCHRONIZED", runtime_inspector_identity=core.RUNTIME_INSPECTOR_ID,
            target_ids=SELECTION.target_ids)
        self.auth = tmp_path / "SYNTHETIC_NOT_EXECUTION_AUTHORITY.json"
        self.write_auth()
        self.executor = integrated.IntegratedPilotExecutor(selection=SELECTION,
            config=self.config, authorization_path=self.auth, credential=credential,
            repository_root=tmp_path / "repository", clock=self.clock)
        monkeypatch.setattr(transport.http.client, "HTTPSConnection", self.factory)
        monkeypatch.setattr(integrated, "_inspect_runtime", self.measure)

    def measure(self, executor):
        c = executor.config
        return core.RuntimeProvenance(repository_root=str(executor.repository_root.resolve()),
            git_head=c.repository_head, git_clean=c.repository_clean,
            implementation_source_sha256=c.implementation_sha256, configuration_sha256=c.sha256,
            runtime_identity=c.runtime_identity, dependency_identity=c.dependency_identity,
            timezone_identity=c.timezone_identity, evidence_store_root=str(self.store.resolve()),
            os_sync_source=c.os_sync_source, os_sync_status=c.os_sync_status,
            phase_offset_evidence="0.000000s", last_successful_sync_evidence="2026-10-01T11:59:00Z",
            monotonic_timer_identity=c.monotonic_timer_identity,
            transport_identity=core.component_runtime_identity(self.executor._network),
            clock_identity=core.component_runtime_identity(self.clock), runtime_mode=c.runtime_mode,
            runtime_inspector_identity=core.RUNTIME_INSPECTOR_ID)

    def write_auth(self, **changes):
        c = self.config
        p = {"authorization_id": "SYNTHETIC_ONLY", "authorizer_reference": "SYNTHETIC_ONLY",
             "authorized_at": "2026-10-01T11:00:00Z", "window_start": "2026-10-01T11:30:00Z",
             "window_end": "2026-10-01T12:30:00Z",
             "protocol": {"identity": core.PROTOCOL_ID, "sha256": core.PROTOCOL_SHA256},
             "pilot_spec": {"identity": core.PILOT_SPEC_ID, "sha256": core.PILOT_SPEC_SHA256},
             "selection_manifest": {"identity": core.SELECTION_ID, "sha256": core.SELECTION_SHA256},
             "kickoff_authority": {"package_zip_sha256": core.KICKOFF_PACKAGE_SHA256,
                                   "authority_ledger_sha256": core.KICKOFF_LEDGER_SHA256},
             "implementation": {"identity": integrated.IMPLEMENTATION_ID,
                                "git_revision": c.repository_head, "sha256": c.implementation_sha256},
             "components": c.component_bundle(), "configuration_sha256": c.sha256,
             "repository": {"head": c.repository_head, "clean": True},
             "credential": {"identity": c.credential_identity, "fingerprint": c.credential_fingerprint,
                            "quota_attribution_mode": c.quota_attribution_mode.value},
             "evidence_store_root": str(self.store.resolve()), "clock_identity": c.clock_identity,
             "runtime_mode": integrated.RUNTIME_MODE,
             "execution_policy": {"mode": "INITIAL_ONLY_NO_CONTINUATION",
                                  "predecessor_evidence_manifest_sha256": None},
             "target_ids": list(SELECTION.target_ids),
             "ceilings": {"primary": 20, "retries": 20, "attempts": 40, "credits": 400,
                          "per_attempt_reservation": 10}, **changes}
        self.auth.write_text(json.dumps(p), encoding="utf-8")

    def ledger(self):
        return core.AttemptLedger(core.EvidenceStore(self.store, repository_root=ROOT))

    def factory(self, host, *, port, timeout, context):
        assert host == transport.PROVIDER_HOST and port == 443
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        target_id = self.ledger().entries()[-1]["target_id"]
        target = next(t for t in SELECTION.targets if t.canonical_game_id == target_id)
        response = self.responses.pop(0) if self.responses else Response(body(target), self.credit_used + 10)
        connection = Connection(self, response)
        self.connections.append(connection)
        return connection


@pytest.fixture(autouse=True)
def network_kill(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("OS network prohibited")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, blocked)


@pytest.fixture
def h(tmp_path, monkeypatch):
    harness = Harness(tmp_path, monkeypatch)
    original = integrated.IntegratedPilotExecutor._validate_live_gate
    def gated(executor, authorization):
        value = original(executor, authorization)
        harness.events.append("gate")
        return value
    monkeypatch.setattr(integrated.IntegratedPilotExecutor, "_validate_live_gate", gated)
    return harness


def test_full_twenty_targets(h):
    report = h.executor.run()
    assert report.disposition != core.PilotDisposition.FAILED
    assert len(report.target_results) == 20 and h.sends == 20
    assert h.ledger().counters().reserved_credits == 200
    assert all(c.closed for c in h.connections)
    core.verify_evidence_manifest(core.EvidenceStore(h.store, repository_root=ROOT), h.store / "evidence_manifest.json")
    files = list(h.store.rglob("*"))
    assert all(SECRET.encode() not in p.read_bytes() for p in files if p.is_file())
    manifest = json.loads((h.store / "evidence_manifest.json").read_bytes())
    assert manifest["components"] == h.config.component_bundle()
    assert manifest["implementation"]["identity"] == integrated.IMPLEMENTATION_ID
    assert h.events.index("prepare") < h.events.index("send") < h.events.index("receive")


@pytest.mark.parametrize("error", [socket.gaierror(), ConnectionRefusedError(), ssl.SSLError(), socket.timeout()])
def test_prepare_failure_retry_uses_frozen_taxonomy(h, error):
    h.prepare_errors = [error]
    h.executor.run()
    entries = h.ledger().entries()
    assert entries[1]["state"] == "PROVABLE_PRE_SEND_FAILURE"
    assert h.ledger().counters().attempts == 21 and h.sends == 20
    assert all(c.closed for c in h.connections)


def test_post_prepare_expiry_aborts_zero_bytes(h):
    h.prepare_hook = lambda: setattr(h.clock, "value", NOW + timedelta(hours=1))
    assert h.executor.run().disposition == core.PilotDisposition.FAILED
    assert h.sends == h.buffer_count == 0
    assert all(c.closed for c in h.connections)
    assert h.ledger().counters().attempts == 1


def test_expiry_after_send_is_sent_and_not_retried(h):
    h.send_hook = lambda: setattr(h.clock, "value", NOW + timedelta(hours=1))
    h.executor.run()
    assert h.sends == 1 and h.ledger().counters().attempts == 1
    assert h.ledger().entries()[1]["state"] == "SENT"
    assert all(c.closed for c in h.connections)


@pytest.mark.parametrize("phase", ["prepare", "send"])
def test_authorization_mutation_at_boundary_is_terminal(h, phase):
    def mutate():
        h.auth.write_bytes(h.auth.read_bytes() + b" ")
    setattr(h, phase + "_hook", mutate)
    assert h.executor.run().disposition == core.PilotDisposition.FAILED
    assert h.sends == (phase == "send")
    assert h.ledger().entries()[-1]["state"] == "SENT_UNKNOWN"
    assert all(c.closed for c in h.connections)


@pytest.mark.parametrize("phase,error", [("send", BrokenPipeError()), ("send", ValueError("after possible send")), ("receive", ConnectionResetError()),
    ("receive", socket.timeout()), ("receive", http.client.IncompleteRead(b"partial", 10))])
def test_ambiguous_and_receive_failures_never_retry(h, phase, error):
    setattr(h, phase + "_error", error)
    h.executor.run()
    assert h.sends == 1 and h.ledger().counters().attempts == 1
    assert h.ledger().entries()[-1]["state"] == "SENT_UNKNOWN"
    assert all(c.closed for c in h.connections)


@pytest.mark.parametrize("field,value", [("transport_identity", "WRONG"),
    ("credential_fingerprint", "F" * 64), ("implementation_sha256", "F" * 64),
    ("repository_clean", False), ("runtime_mode", "OFFLINE_ONLY"),
    ("timeouts", transport.TransportTimeouts(11, 31))])
def test_wrong_identity_fails_before_prepare(h, field, value):
    h.executor.config = replace(h.config, **{field: value})
    with pytest.raises(core.AuthorizationError):
        h.executor.run()
    assert h.connections == []


@pytest.mark.parametrize("field", ["components", "implementation", "credential", "ceilings", "repository"])
def test_wrong_authorization_fails_before_prepare(h, field):
    h.write_auth(**{field: {}})
    with pytest.raises(core.AuthorizationError):
        h.executor.run()
    assert h.connections == []


def test_sent_durability_failure_closes_and_preserves_unknown(h, monkeypatch):
    original = core.AttemptLedger.append
    def append(ledger, **kwargs):
        if kwargs["state"] == core.AttemptState.SENT:
            raise core.EvidenceIOError("synthetic SENT failure")
        return original(ledger, **kwargs)
    monkeypatch.setattr(core.AttemptLedger, "append", append)
    h.executor.run()
    assert h.sends == 1 and h.ledger().counters().attempts == 1
    assert h.ledger().entries()[-1]["state"] == "SENT_UNKNOWN"
    assert all(c.closed for c in h.connections)


@pytest.mark.parametrize("encoding,data", [("gzip", None), ("gzip", b"corrupt")])
def test_encoded_entity_retention_and_single_frozen_decode(h, monkeypatch, encoding, data):
    entity = data if data is not None else gzip.compress(body(SELECTION.targets[0]))
    h.responses = [Response(entity, 10, headers=(("Content-Encoding", encoding),))]
    calls = []
    original = core.decode_application_body
    def decode(response):
        calls.append(response.body)
        return original(response)
    monkeypatch.setattr(core, "decode_application_body", decode)
    report = h.executor.run()
    assert calls.count(entity) == 1
    directory = h.store / "attempts" / (SELECTION.target_ids[0] + ".primary")
    assert (directory / "transport_entity.bin").read_bytes() == entity
    meta = json.loads((directory / "transport_response.json").read_bytes())
    assert ["Content-Encoding", encoding] in meta["raw_headers"]
    assert meta["transfer_decoding"] == transport.TRANSFER_DECODING_NONE
    assert (report.disposition == core.PilotDisposition.FAILED) == (data is not None)


@pytest.mark.parametrize("last", [11, -1])
def test_quota_violation_terminal_without_retry(h, last):
    h.responses = [Response(body(SELECTION.targets[0]), 10, last=last)]
    assert h.executor.run().disposition == core.PilotDisposition.FAILED
    assert h.sends == 1


def test_zero_credit_empty_response(h):
    h.responses = [Response(body(SELECTION.targets[0], empty=True), 0, last=0)]
    report = h.executor.run()
    assert report.target_results[0].analysis.empty_data
    assert h.sends == 20


def test_retry_ceiling_second_presend_failure(h):
    h.prepare_errors = [socket.gaierror(), socket.gaierror()]
    h.executor.run()
    assert h.sends == 0 and h.ledger().counters().attempts == 2


def test_closed_production_constructor_and_frozen_components():
    assert "transport" not in inspect.signature(integrated.IntegratedPilotExecutor).parameters
    assert "factory" not in inspect.signature(integrated.IntegratedPilotExecutor).parameters
    assert not hasattr(transport.OddsApiHistoricalTransport(), "begin")
    assert core._digest(Path(core.__file__).read_bytes()) == integrated.EXECUTOR_SHA256
    assert core._digest(Path(transport.__file__).read_bytes()) == integrated.TRANSPORT_SHA256


def test_network_kill_switch():
    with pytest.raises(AssertionError, match="OS network prohibited"):
        transport.OddsApiHistoricalTransport().prepare()


@pytest.mark.parametrize("stage", ["request", "response"])
def test_evidence_io_failure_is_terminal(h, monkeypatch, stage):
    def fail(*args, **kwargs):
        raise core.EvidenceIOError("synthetic durability failure")
    monkeypatch.setattr(integrated._IntegratedStore, "write_attempt_request" if stage == "request" else "write_response", fail)
    assert h.executor.run().disposition == core.PilotDisposition.FAILED
    assert h.sends == (stage == "response")
    assert all(c.closed for c in h.connections)
    if stage == "response":
        assert h.ledger().entries()[-1]["state"] == "SENT_UNKNOWN"


def test_mutation_before_prepare_blocks_preparation(h, monkeypatch):
    original = core.EvidenceStore.write_attempt_request
    def write(store, *args, **kwargs):
        result = original(store, *args, **kwargs)
        h.auth.write_bytes(h.auth.read_bytes() + b" ")
        return result
    monkeypatch.setattr(core.EvidenceStore, "write_attempt_request", write)
    assert h.executor.run().disposition == core.PilotDisposition.FAILED
    assert h.connections == []


@pytest.mark.parametrize("phase", ["report", "manifest", "acceptance"])
def test_final_authorization_gates_retained(h, monkeypatch, phase):
    owner, name = {"report": (core, "build_report"),
                   "manifest": (integrated, "create_evidence_manifest"),
                   "acceptance": (core, "verify_evidence_manifest")}[phase]
    original = getattr(owner, name)
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        h.auth.write_bytes(h.auth.read_bytes() + b" ")
        return result
    monkeypatch.setattr(owner, name, mutate)
    assert h.executor.run().disposition == core.PilotDisposition.FAILED
    assert all(c.closed for c in h.connections)


@pytest.mark.parametrize("field", ["primary_ceiling", "retry_ceiling", "attempt_ceiling",
                                   "credit_ceiling", "per_attempt_reservation"])
def test_exact_ceiling_configuration_required(h, field):
    h.executor.config = replace(h.config, **{field: getattr(h.config, field) + 1})
    with pytest.raises(core.AuthorizationError):
        h.executor.run()
    assert h.connections == []


def test_all_twenty_eligible_retries_stop_at_forty_and_four_hundred(h):
    for index, target in enumerate(SELECTION.targets):
        h.responses.extend([Response(b"{}", (2 * index + 1) * 10, status=500),
                            Response(body(target), (2 * index + 2) * 10)])
    assert h.executor.run().disposition != core.PilotDisposition.FAILED
    counters = h.ledger().counters()
    assert counters.attempts == h.sends == 40
    assert counters.reserved_credits == 400
    assert all(c.closed for c in h.connections)


def test_unclassified_retry_send_failure_closes_its_own_connection(h):
    h.responses = [Response(b"{}", 10, status=500)]
    def fail_second_send():
        if h.sends == 2:
            h.send_error = ValueError("synthetic retry send failure")
    h.send_hook = fail_second_send
    assert h.executor.run().disposition == core.PilotDisposition.FAILED
    assert h.sends == h.ledger().counters().attempts == 2
    assert h.ledger().entries()[-1]["state"] == "SENT_UNKNOWN"
    assert all(c.closed for c in h.connections)


def test_quota_inconsistency_is_terminal(h):
    h.responses = [Response(body(SELECTION.targets[0]), 10),
                   Response(body(SELECTION.targets[1]), 9)]
    assert h.executor.run().disposition == core.PilotDisposition.FAILED
    assert h.sends == 2


@pytest.mark.parametrize("error", [ValueError("synthetic validation"), OSError("synthetic buffering")])
def test_local_buffer_failure_is_provable_presend(h, error):
    h.buffer_error = error
    h.executor.run()
    assert h.sends == 0 and h.ledger().counters().attempts == 2
    assert h.ledger().entries()[1]["state"] == "PROVABLE_PRE_SEND_FAILURE"
    assert all(c.closed for c in h.connections)


def test_transport_request_validation_failure_is_provable_presend(h, monkeypatch):
    original = core.provider_request
    monkeypatch.setattr(core, "provider_request", lambda target: replace(original(target), path="/wrong"))
    h.executor.run()
    assert h.sends == h.buffer_count == 0
    assert h.ledger().entries()[1]["state"] == "PROVABLE_PRE_SEND_FAILURE"
    assert all(c.closed for c in h.connections)


@pytest.mark.parametrize("headers", [(("Transfer-Encoding", "invalid"),),
                                    (("Transfer-Encoding", "chunked"), ("Content-Length", "10"))])
def test_transfer_framing_failure_is_postsend_without_retry(h, headers):
    h.responses = [Response(body(SELECTION.targets[0]), 10, headers=headers)]
    h.executor.run()
    assert h.sends == 1 and h.ledger().entries()[-1]["state"] == "SENT_UNKNOWN"
    assert all(c.closed for c in h.connections)


def test_compressed_secret_echo_is_not_retained(h):
    entity = gzip.compress(json.dumps({"secret": SECRET}).encode())
    h.responses = [Response(entity, 10, headers=(("Content-Encoding", "gzip"),))]
    assert h.executor.run().disposition == core.PilotDisposition.FAILED
    assert not list(h.store.rglob("transport_entity.bin"))
    assert all(SECRET.encode() not in p.read_bytes() for p in h.store.rglob("*") if p.is_file())


def test_secret_echo_in_raw_header_name_is_not_retained(h):
    h.responses = [Response(body(SELECTION.targets[0]), 10, headers=((SECRET, "echo"),))]
    assert h.executor.run().disposition == core.PilotDisposition.FAILED
    assert h.sends == 1 and h.ledger().entries()[-1]["state"] == "SENT_UNKNOWN"
    assert all(SECRET.encode() not in p.read_bytes() for p in h.store.rglob("*") if p.is_file())


@pytest.mark.parametrize("state", ["RESERVED", "SENT"])
def test_hard_durability_failure_recovery_never_resumes(h, monkeypatch, state):
    original = core.AttemptLedger.append
    def append(ledger, **kwargs):
        if kwargs["state"] == core.AttemptState.SENT_UNKNOWN or (state == "RESERVED" and kwargs["state"] == core.AttemptState.SENT):
            raise core.EvidenceIOError("synthetic unavailable durable ledger")
        return original(ledger, **kwargs)
    monkeypatch.setattr(core.AttemptLedger, "append", append)
    h.receive_error = ConnectionResetError()
    with pytest.raises(core.EvidenceIOError):
        h.executor.run()
    assert h.sends == 1 and h.ledger().entries()[-1]["state"] == state
    assert all(c.closed for c in h.connections)
    monkeypatch.setattr(core.AttemptLedger, "append", original)
    def measured(inspector, *, config, clock):
        value = h.measure(h.executor).canonical_payload()
        for key in ("evidence_store_root", "transport_identity", "runtime_mode"):
            value.pop(key)
        return core.RecoveryRuntimeProvenance(**value, recovery_mode="RECOVERY_ONLY")
    monkeypatch.setattr(core.LocalRuntimeProvenanceInspector, "inspect_recovery", measured)
    h.clock.value = NOW + timedelta(hours=1)
    recovery = integrated.IntegratedPilotRecovery(selection=SELECTION, config=h.config,
        repository_root=h.executor.repository_root, clock=h.clock)
    assert not hasattr(recovery, "transport") and not hasattr(recovery, "credential")
    assert recovery.recover().disposition == core.PilotDisposition.FAILED
    assert h.ledger().entries()[-1]["state"] == "SENT_UNKNOWN" and h.sends == 1
    core.verify_evidence_manifest(core.EvidenceStore(h.store, repository_root=ROOT), h.store / "evidence_manifest.json")
    with pytest.raises(core.AuthorizationError):
        h.executor.run()
