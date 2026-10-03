"""Candidate 0.2.0: closed admission of the two frozen pilot components.

No CLI, credential discovery, authorization builder, or production wiring.
The private legacy bridge exists only to reuse the frozen attempt state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import json
from pathlib import Path

from . import historical_market_pilot as core
from . import historical_market_odds_api_transport as network

IMPLEMENTATION_ID = "nfl_historical_market_provider_pilot_execution_0.2.0"
RUNTIME_MODE = "REAL_TRANSPORT_GATED"
EXECUTOR_SHA256 = "E199D0290E45EE611F5D1FBC1C837925343E73528BCA72E7F77A85E2B8313267"
TRANSPORT_SHA256 = "2F7885CFFA02FA4EB72C9C408A76F4A9A742DC705A391A782FFCD02F2789264A"


@dataclass(frozen=True)
class IntegratedConfig(core.PilotExecutionConfig):
    timeouts: network.TransportTimeouts = network.TransportTimeouts()

    def component_bundle(self) -> dict:
        transport = network.OddsApiHistoricalTransport(timeouts=self.timeouts)
        return {
            "integration": {"identity": IMPLEMENTATION_ID,
                            "sha256": self.implementation_sha256.upper()},
            "executor": {"identity": core.IMPLEMENTATION_ID, "sha256": EXECUTOR_SHA256},
            "transport": {"identity": network.TRANSPORT_IMPLEMENTATION_ID,
                          "sha256": TRANSPORT_SHA256,
                          "runtime_identity": self.transport_identity,
                          "payload": transport.identity_payload},
        }

    def canonical_payload(self) -> dict:
        return {**super().canonical_payload(), "components": self.component_bundle()}


def validate_runtime_config(config: IntegratedConfig, selection: core.FrozenSelection) -> None:
    if type(config) is not IntegratedConfig or type(config.timeouts) is not network.TransportTimeouts:
        raise core.AuthorizationError("exact integrated configuration is required")
    core.validate_runtime_config(replace(config, runtime_mode=core.RUNTIME_MODE), selection)
    if config.runtime_mode != RUNTIME_MODE:
        raise core.AuthorizationError("successor runtime mode mismatch")
    identities = ((Path(core.__file__), EXECUTOR_SHA256),
                  (Path(network.__file__), TRANSPORT_SHA256),
                  (Path(__file__), config.implementation_sha256.upper()))
    for path, expected in identities:
        if core._digest(path.read_bytes()) != expected:
            raise core.AuthorizationError("frozen component or integration source mismatch")
    if core.component_runtime_identity(network.OddsApiHistoricalTransport(timeouts=config.timeouts)) != config.transport_identity:
        raise core.AuthorizationError("reviewed transport runtime identity mismatch")


def _inspect_runtime(executor) -> core.RuntimeProvenance:
    measured = core.LocalRuntimeProvenanceInspector(executor.repository_root).inspect(
        config=executor.config, transport=executor._network, clock=executor.clock)
    return replace(measured, implementation_source_sha256=core._digest(Path(__file__).read_bytes()),
                   runtime_mode=RUNTIME_MODE)


def _validate_runtime(executor, measured: core.RuntimeProvenance) -> None:
    config = executor.config
    expected = {
        "repository_root": str(executor.repository_root.resolve()),
        "git_head": config.repository_head, "git_clean": True,
        "implementation_source_sha256": config.implementation_sha256.upper(),
        "configuration_sha256": config.sha256, "runtime_identity": config.runtime_identity,
        "dependency_identity": config.dependency_identity, "timezone_identity": config.timezone_identity,
        "evidence_store_root": str(Path(config.evidence_store_root).resolve()),
        "os_sync_source": config.os_sync_source, "os_sync_status": config.os_sync_status,
        "monotonic_timer_identity": config.monotonic_timer_identity,
        "transport_identity": config.transport_identity, "clock_identity": config.clock_identity,
        "runtime_mode": RUNTIME_MODE, "runtime_inspector_identity": core.RUNTIME_INSPECTOR_ID,
    }
    actual = measured.canonical_payload()
    phase = actual.pop("phase_offset_evidence", None)
    sync = actual.pop("last_successful_sync_evidence", None)
    if actual != expected or measured.os_sync_status != "SYNCHRONIZED":
        raise core.AuthorizationError("measured integrated runtime identity mismatch")
    core._validate_dynamic_clock_evidence(phase, sync)
    if (type(executor._network) is not network.OddsApiHistoricalTransport
        or core.component_runtime_identity(executor._network) != config.transport_identity
        or core.component_runtime_identity(executor.clock) != config.clock_identity
        or executor.clock.monotonic_identity != config.monotonic_timer_identity
        or executor.credential.fingerprint != config.credential_fingerprint.upper()):
        raise core.AuthorizationError("component or credential identity mismatch")


class _IntegratedStore(core.EvidenceStore):
    def write_response(self, attempt_id, *, response, decoded_body, received_at, secret_values=()):
        self.retain_transport(attempt_id, response, self._config, received_at)
        return super().write_response(attempt_id, response=response, decoded_body=decoded_body,
                                    received_at=received_at, secret_values=secret_values)

    def write_undecodable_response(self, attempt_id, *, response, received_at, secret_values=()):
        self.retain_transport(attempt_id, response, self._config, received_at)
        return super().write_undecodable_response(attempt_id, response=response,
                                                received_at=received_at, secret_values=secret_values)

    def write_run_identity(self, config, provenance):
        core._exclusive_write(self.root / "run_identity.json", core._canonical_json_bytes({
            "configuration": config.canonical_payload(), "configuration_sha256": config.sha256,
            "implementation": {"identity": IMPLEMENTATION_ID, "revision": config.implementation_revision,
                               "sha256": config.implementation_sha256.upper()},
            "components": config.component_bundle(),
            "runtime_provenance_sha256": provenance.sha256,
            "runtime_provenance_artifact_sha256": provenance.artifact_sha256,
        }))

    def retain_transport(self, attempt_id, response, config, received_at):
        if core._response_contains_secret(response, response.body, self._credential):
            return
        directory = self.root / "attempts" / attempt_id
        core._exclusive_write(directory / "transport_entity.bin", response.body)
        core._exclusive_write(directory / "transport_response.json", core._canonical_json_bytes({
            "status_code": response.status_code,
            "raw_headers": [[name, value.replace(self._credential.value, "[REDACTED]")]
                            for name, value in response.headers.raw_items],
            "transfer_decoding": response.transfer_decoding,
            "content_decoding": response.content_decoding,
            "entity_sha256": core._digest(response.body),
            "received_at": core._utc_text(received_at), "components": config.component_bundle(),
        }))


class _OwnedExchange:
    def __init__(self, exchange, bridge, request):
        self.exchange, self.bridge, self.request = exchange, bridge, request

    def close(self):
        self.exchange.close()

    def receive(self):
        try:
            response = self.exchange.receive()
            if any(self.bridge.executor.credential.value in name
                   for name, _ in response.headers.raw_items):
                # Frozen value/body checks do not cover newly retained raw header names.
                raise core.PossibleSendFailure(core.ReceiveFailureKind.POSSIBLE_SEND)
            return response
        finally:
            self.close()


class _AttemptBridge:
    """Private compatibility with core._execute_target; never caller selectable."""
    def __init__(self, executor, authorization, store, ledger):
        self.executor, self.authorization = executor, authorization
        self.store, self.ledger = store, ledger
        self.exchange = None

    def begin(self, request, credential):
        self.exchange = None
        latest = self.ledger.entries()[-1]
        self.attempt_id = latest["attempt_id"]
        if latest["state"] != "RESERVED" or not (self.store.root / "attempts" / self.attempt_id / "request.json").exists():
            raise core.EvidenceIntegrityError("durable reservation and request must precede preparation")
        self.executor._validate_live_gate(self.authorization)
        prepared = self.executor._network.prepare()
        try:
            self.executor._validate_live_gate(self.authorization)
            try:
                network._validate_request(request)
            except (TypeError, ValueError):
                raise core.ProvablePreSendFailure(core.PreSendFailureKind.CONNECT) from None
            exchange = prepared.send(request, credential)
            self.exchange = _OwnedExchange(exchange, self, request)
            return self.exchange
        finally:
            prepared.close()
            if self.exchange is None:
                # Frozen send consumes its prepared handle before buffering. Its
                # public close cannot cover an unclassified exception thereafter.
                network._close_quietly(prepared._PreparedOddsApiConnection__connection)


class IntegratedPilotExecutor(core.PilotExecutor):
    def __init__(self, *, selection, config, authorization_path, credential, repository_root, clock):
        if type(config) is not IntegratedConfig or type(credential) is not core.SecretCredential:
            raise core.AuthorizationError("exact configuration and credential types required")
        self.selection, self.config = selection, config
        self.authorization_path, self.credential = authorization_path, credential
        self.repository_root, self.clock = Path(repository_root), clock
        self._network = network.OddsApiHistoricalTransport(timeouts=config.timeouts)

    def _validate_live_gate(self, authorization):
        now = super()._validate_live_gate(authorization)
        validate_runtime_config(self.config, self.selection)
        _validate_runtime(self, _inspect_runtime(self))
        return now

    def _execute_target(self, *, target, authorization, store, ledger, previous_quota):
        bridge = _AttemptBridge(self, authorization, store, ledger)
        self.transport = bridge
        try:
            return super()._execute_target(target=target, authorization=authorization,
                store=store, ledger=ledger, previous_quota=previous_quota)
        finally:
            if bridge.exchange is not None:
                bridge.exchange.close()
                latest = ledger.entries()[-1]
                if latest["state"] in {"RESERVED", "SENT"}:
                    ledger.append(attempt_id=latest["attempt_id"], target_id=latest["target_id"],
                        state=core.AttemptState.SENT_UNKNOWN, observed_at=self.clock.now_utc(),
                        attempt_kind=core.AttemptKind(latest["attempt_kind"]),
                        request_sha256=latest["request_sha256"],
                        predecessor_attempt_id=latest["predecessor_attempt_id"],
                        details={"reason": "send_or_evidence_durability_unknown"})

    def run(self) -> core.PilotReport:
        provenance = _inspect_runtime(self)
        validate_runtime_config(self.config, self.selection)
        _validate_runtime(self, provenance)
        now = self.clock.now_utc()
        authorization = load_and_validate_authorization(
            self.authorization_path,
            config=self.config,
            selection=self.selection,
            now=now,
        )
        store = _IntegratedStore(
            Path(self.config.evidence_store_root),
            repository_root=self.repository_root,
        )
        store._credential = self.credential
        store._config = self.config
        store.initialize_new()
        store.claim_authorization(authorization)
        store.write_runtime_provenance(provenance)
        store.write_run_identity(self.config, provenance)
        ledger = core.AttemptLedger(store)
        results: list[core.TargetExecutionResult] = []
        quota: core.QuotaSnapshot | None = None
        with store.acquire_lease(authorization.authorization_id):
            for target in self.selection.targets:
                try:
                    result, quota = self._execute_target(
                        target=target,
                        authorization=authorization,
                        store=store,
                        ledger=ledger,
                        previous_quota=quota,
                    )
                except core.PilotError as error:
                    if isinstance(error, (core.EvidenceIOError, core.EvidenceIntegrityError)):
                        # Unresolved durability is a hard failure, not a normal report.
                        if any(state in {core.AttemptState.RESERVED, core.AttemptState.SENT}
                               for state in ledger.current_states().values()):
                            raise
                    result = core.TargetExecutionResult(
                        target.canonical_game_id,
                        True,
                        0,
                        None,
                        core._pilot_error_reason(error),
                    )
                results.append(result)
                if result.terminal:
                    break
            try:
                authorization.validate_unchanged()
            except core.AuthorizationError:
                results.append(
                    core.TargetExecutionResult(
                        self.selection.targets[-1].canonical_game_id,
                        True,
                        0,
                        None,
                        "authorization_failure_before_report",
                    )
                )
            report = core.build_report(results)
            report_path = store.write_report(report)
            try:
                authorization.validate_unchanged()
            except core.AuthorizationError:
                store.write_integrity_failure(
                    "authorization_failure_before_manifest",
                    self.clock.now_utc(),
                )
                return core.PilotReport(
                    core.PilotDisposition.FAILED,
                    report.target_results,
                    "authorization_failure_before_manifest",
                )
            manifest_path = create_evidence_manifest(
                store,
                authorization=authorization,
                config=self.config,
                report_path=report_path,
            )
            try:
                authorization.validate_unchanged()
                core.verify_evidence_manifest(store, manifest_path)
                authorization.validate_unchanged()
            except (core.AuthorizationError, core.EvidenceIntegrityError):
                store.write_integrity_failure(
                    "authorization_or_manifest_failure_before_acceptance",
                    self.clock.now_utc(),
                )
                return core.PilotReport(
                    core.PilotDisposition.FAILED,
                    report.target_results,
                    "authorization_or_manifest_failure_before_acceptance",
                )
        return report



def load_and_validate_authorization(
    path: Path,
    *,
    config: core.PilotExecutionConfig,
    selection: core.FrozenSelection,
    now: datetime,
    require_active_window: bool = True,
) -> core.ExecutionAuthorization:
    validate_runtime_config(config, selection)
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except FileNotFoundError as error:
        raise core.AuthorizationError("single-use authorization artifact is missing") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise core.AuthorizationError("single-use authorization artifact is invalid") from error
    if not isinstance(payload, dict):
        raise core.AuthorizationError("single-use authorization must be a JSON object")
    if payload.get("components") != config.component_bundle():
        raise core.AuthorizationError("authorization component bundle mismatch")
    expected = {
        "protocol": {"identity": core.PROTOCOL_ID, "sha256": core.PROTOCOL_SHA256},
        "pilot_spec": {"identity": core.PILOT_SPEC_ID, "sha256": core.PILOT_SPEC_SHA256},
        "selection_manifest": {"identity": core.SELECTION_ID, "sha256": core.SELECTION_SHA256},
        "kickoff_authority": {
            "package_zip_sha256": core.KICKOFF_PACKAGE_SHA256,
            "authority_ledger_sha256": core.KICKOFF_LEDGER_SHA256,
        },
    }
    for name, value in expected.items():
        if payload.get(name) != value:
            raise core.AuthorizationError(f"authorization {name} identity mismatch")
    if payload.get("configuration_sha256") != config.sha256:
        raise core.AuthorizationError("authorization configuration identity mismatch")
    if payload.get("implementation") != {
        "identity": IMPLEMENTATION_ID,
        "git_revision": config.implementation_revision,
        "sha256": config.implementation_sha256.upper(),
    }:
        raise core.AuthorizationError("authorization implementation identity mismatch")
    if payload.get("repository") != {
        "head": config.repository_head,
        "clean": True,
    }:
        raise core.AuthorizationError("authorization repository identity mismatch")
    if payload.get("credential") != {
        "identity": config.credential_identity,
        "fingerprint": config.credential_fingerprint.upper(),
        "quota_attribution_mode": config.quota_attribution_mode.value,
    }:
        raise core.AuthorizationError("authorization credential identity mismatch")
    if str(Path(payload.get("evidence_store_root", "")).resolve()) != str(
        Path(config.evidence_store_root).resolve()
    ):
        raise core.AuthorizationError("authorization evidence-store identity mismatch")
    if tuple(payload.get("target_ids", ())) != selection.target_ids:
        raise core.AuthorizationError("authorization target set mismatch")
    if payload.get("ceilings") != {
        "primary": core.MAX_PRIMARY_CALLS,
        "retries": core.MAX_RETRY_CALLS,
        "attempts": core.MAX_ATTEMPTS,
        "credits": core.MAX_RESERVED_CREDITS,
        "per_attempt_reservation": core.RESERVED_CREDITS_PER_ATTEMPT,
    }:
        raise core.AuthorizationError("authorization ceiling mismatch")
    if payload.get("clock_identity") != config.clock_identity:
        raise core.AuthorizationError("authorization clock identity mismatch")
    if payload.get("runtime_mode") != RUNTIME_MODE:
        raise core.AuthorizationError("authorization runtime mode mismatch")
    if payload.get("execution_policy") != {
        "mode": "INITIAL_ONLY_NO_CONTINUATION",
        "predecessor_evidence_manifest_sha256": None,
    }:
        raise core.AuthorizationError("continuation is unsupported by implementation 0.1.4")
    try:
        authorization_id = core._required_text(payload, "authorization_id")
        authorizer = core._required_text(payload, "authorizer_reference")
        authorized_at = core._parse_timestamp(core._required_text(payload, "authorized_at"))
        window_start = core._parse_timestamp(core._required_text(payload, "window_start"))
        window_end = core._parse_timestamp(core._required_text(payload, "window_end"))
    except ValueError as error:
        raise core.AuthorizationError("authorization metadata is invalid") from error
    core._require_aware(now, "trusted current time")
    if not authorized_at <= window_start < window_end:
        raise core.AuthorizationError("authorization chronology is invalid")
    if require_active_window and not window_start <= now < window_end:
        raise core.AuthorizationError("authorization is outside its execution window")
    authorization = core.ExecutionAuthorization(
        source_path=path.resolve(),
        raw_bytes=raw,
        sha256=core._digest(raw),
        authorization_id=authorization_id,
        authorizer_reference=authorizer,
        authorized_at=authorized_at,
        window_start=window_start,
        window_end=window_end,
        configuration_sha256=config.sha256,
    )
    authorization.validate_unchanged()
    return authorization




def create_evidence_manifest(
    store: core.EvidenceStore,
    *,
    authorization: core.ExecutionAuthorization,
    config: core.PilotExecutionConfig,
    report_path: Path,
    recovery_provenance: core.RecoveryRuntimeProvenance | None = None,
) -> Path:
    records = []
    manifest_path = store.root / "evidence_manifest.json"
    for path in sorted(
        (item for item in store.root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(store.root).as_posix(),
    ):
        relative = path.relative_to(store.root).as_posix()
        if relative in {".pilot.lock", "evidence_manifest.json"}:
            continue
        data = path.read_bytes()
        records.append({"bytes": len(data), "path": relative, "sha256": core._digest(data)})
    if len({item["path"] for item in records}) != len(records):
        raise core.EvidenceIntegrityError("duplicate evidence artifact path")
    payload = {
        "components": config.component_bundle(),
        "authorization": {
            "id": authorization.authorization_id,
            "sha256": authorization.sha256,
        },
        "configuration_sha256": config.sha256,
        "files": records,
        "implementation": {
            "identity": IMPLEMENTATION_ID,
            "revision": config.implementation_revision,
            "sha256": config.implementation_sha256.upper(),
        },
        "protocol": {"identity": core.PROTOCOL_ID, "sha256": core.PROTOCOL_SHA256},
        "pilot_spec": {"identity": core.PILOT_SPEC_ID, "sha256": core.PILOT_SPEC_SHA256},
        "report": report_path.relative_to(store.root).as_posix(),
        "runtime_attribution": {
            "original_execution": {
                "implementation_identity": IMPLEMENTATION_ID,
                "runtime_provenance_path": "runtime_provenance.json",
                "runtime_provenance_sha256": core._digest(
                    (store.root / "runtime_provenance.json").read_bytes()
                ),
            },
            "recovery": (
                {
                    "implementation_identity": IMPLEMENTATION_ID,
                    "runtime_provenance_path": "recovery/runtime_provenance.json",
                    "runtime_provenance_sha256": recovery_provenance.artifact_sha256,
                }
                if recovery_provenance is not None
                else None
            ),
        },
        "selection_manifest": {"identity": core.SELECTION_ID, "sha256": core.SELECTION_SHA256},
    }
    core._exclusive_write(manifest_path, core._canonical_json_bytes(payload))
    return manifest_path




class IntegratedPilotRecovery(core.PilotRecovery):
    """Recovery-only closure for an interrupted governed evidence store.

    This lifecycle has no transport or credential and cannot resume execution.
    """

    def __init__(
        self,
        *,
        selection: core.FrozenSelection,
        config: core.PilotExecutionConfig,
        repository_root: Path,
        clock: core.PilotClock,
    ):
        self.selection = selection
        self.config = config
        self.repository_root = repository_root
        self.clock = clock

    def recover(self) -> core.PilotReport:
        validate_runtime_config(self.config, self.selection)
        recovery_provenance = core.LocalRuntimeProvenanceInspector(
            self.repository_root
        ).inspect_recovery(config=self.config, clock=self.clock)
        recovery_provenance = replace(recovery_provenance,
            implementation_source_sha256=core._digest(Path(__file__).read_bytes()))
        core.validate_recovery_runtime(
            recovery_provenance,
            config=self.config,
            repository_root=self.repository_root,
            clock=self.clock,
        )
        store = core.EvidenceStore(
            Path(self.config.evidence_store_root),
            repository_root=self.repository_root,
        )
        authorization, _ = self._validate_recoverable_store(store)
        with store.acquire_lease(authorization.authorization_id):
            authorization, ledger = self._validate_recoverable_store(store)
            original_provenance_sha256 = core._digest(
                (store.root / "runtime_provenance.json").read_bytes()
            )
            recovery_provenance_path = store.write_recovery_runtime_provenance(
                recovery_provenance
            )
            recovery_provenance_sha256 = core._digest(
                recovery_provenance_path.read_bytes()
            )
            recovered = ledger.recover_incomplete(now=self.clock.now_utc())
            counters = ledger.counters()
            store.write_recovery_record(
                recovered_attempt_ids=recovered,
                counters=counters,
                observed_at=self.clock.now_utc(),
                original_runtime_provenance_sha256=original_provenance_sha256,
                recovery_runtime_provenance_sha256=recovery_provenance_sha256,
            )
            results = tuple(
                core.TargetExecutionResult(
                    target_id,
                    True,
                    0,
                    None,
                    "crash_recovery_no_continuation_supported",
                )
                for target_id in recovered
            )
            report = core.PilotReport(
                core.PilotDisposition.FAILED,
                results,
                "crash_recovery_no_continuation_supported",
            )
            report_path = store.write_report(
                report, filename="recovery_terminal_report.json"
            )
            manifest_path = create_evidence_manifest(
                store,
                authorization=authorization,
                config=self.config,
                report_path=report_path,
                recovery_provenance=recovery_provenance,
            )
            core.verify_evidence_manifest(store, manifest_path)
        return report

    def _validate_recoverable_store(
        self, store: core.EvidenceStore
    ) -> tuple[core.ExecutionAuthorization, core.AttemptLedger]:
        store.validate_recovery_root()
        authorization = load_and_validate_authorization(
            store.root / "authorization.json",
            config=self.config,
            selection=self.selection,
            now=self.clock.now_utc(),
            require_active_window=False,
        )
        self._validate_governed_identities(store, authorization)
        ledger = core.AttemptLedger(store)
        ledger.entries()
        return authorization, ledger

    def _validate_governed_identities(
        self, store: core.EvidenceStore, authorization: core.ExecutionAuthorization
    ) -> None:
        claim = core._read_json_object(store.root / "authorization_claim.json")
        if claim != {
            "authorization_id": authorization.authorization_id,
            "authorization_sha256": authorization.sha256,
        }:
            raise core.EvidenceIntegrityError("authorization claim identity mismatch")
        provenance_payload = core._read_json_object(store.root / "runtime_provenance.json")
        try:
            provenance = core.RuntimeProvenance(**provenance_payload)
        except TypeError as error:
            raise core.EvidenceIntegrityError("runtime provenance schema mismatch") from error
        run_identity = core._read_json_object(store.root / "run_identity.json")
        if (
            run_identity.get("configuration_sha256") != self.config.sha256
            or run_identity.get("runtime_provenance_sha256") != provenance.sha256
            or run_identity.get("runtime_provenance_artifact_sha256")
            != provenance.artifact_sha256
            or provenance.configuration_sha256 != self.config.sha256
            or provenance.evidence_store_root != str(store.root)
        ):
            raise core.EvidenceIntegrityError("governed run identity mismatch")
        if run_identity.get("implementation") != {
            "identity": IMPLEMENTATION_ID,
            "revision": self.config.implementation_revision,
            "sha256": self.config.implementation_sha256.upper(),
        }:
            raise core.EvidenceIntegrityError("governed implementation identity mismatch")
        if run_identity.get("components") != self.config.component_bundle():
            raise core.EvidenceIntegrityError("governed component bundle mismatch")
