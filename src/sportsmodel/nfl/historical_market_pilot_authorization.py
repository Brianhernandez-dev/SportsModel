"""Non-executing credential establishment and authorization CANDIDATE boundary.

No provider, database, dotenv, ambient credential, or executor-run entry point.
Candidate envelopes are intentionally incompatible with frozen admission.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import getpass
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from urllib.parse import quote
import uuid
import warnings
import zipfile
from zoneinfo import ZoneInfo

from . import historical_market_pilot as core
from . import historical_market_pilot_integrated as integrated
from . import historical_market_odds_api_transport as transport

BUILDER_ID = "nfl_historical_market_pilot_authorization_builder_0.1.1"
CREDENTIAL_SCHEMA = "nfl_pilot_dedicated_credential_identity_0.1.0"
CANDIDATE_SCHEMA = "nfl_pilot_pre_authorization_candidate_0.1.1"
ACTIVATION_ONLY_FIELDS = frozenset({
    "authorization_id", "authorizer_reference", "authorized_at", "window_start", "window_end",
})
# Exact top-level contracts of the two source-pinned frozen loaders.
FROZEN_CORE_AUTHORIZATION_FIELDS = ACTIVATION_ONLY_FIELDS | frozenset({
    "protocol", "pilot_spec", "selection_manifest", "kickoff_authority", "configuration_sha256",
    "implementation", "repository", "credential", "evidence_store_root", "target_ids",
    "ceilings", "clock_identity", "runtime_mode", "execution_policy",
})
FROZEN_INTEGRATED_AUTHORIZATION_FIELDS = FROZEN_CORE_AUTHORIZATION_FIELDS | {"components"}
ACCEPTED_TIME_SOURCE = "time.windows.com,0x9"
INTEGRATION_SHA = "DCC9DE3F0A8182373FF512D08350B4B99BFED5DC1973AAA2B172C8B0CA2D9FA7"
STORAGE_NAMESPACE = "NFL_Historical_Market_Pilot"
_LABEL = re.compile(r"nfl-historical-market-pilot:dedicated-20k:[a-z][a-z0-9_-]{0,31}")
_REFERENCE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}")
_SHA = re.compile(r"[0-9A-F]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_FROZEN = {
    "src/sportsmodel/nfl/historical_market_pilot.py": integrated.EXECUTOR_SHA256,
    "src/sportsmodel/nfl/historical_market_odds_api_transport.py": integrated.TRANSPORT_SHA256,
    "src/sportsmodel/nfl/historical_market_pilot_integrated.py": INTEGRATION_SHA,
    "docs/architecture/nfl_historical_market_research_protocol_0.2.5.md": core.PROTOCOL_SHA256,
    "docs/architecture/nfl_historical_market_provider_pilot_spec_0.1.3.md": core.PILOT_SPEC_SHA256,
    "docs/architecture/nfl_historical_market_provider_pilot_selection_manifest_0.1.3.json": core.SELECTION_SHA256,
    "docs/architecture/nfl_historical_market_pilot_operational_readiness_0.1.0.md": "3F0496CC3A12DBD7D0116FDC3CF7A78944218D436352AE746A8E3CBFC515253E",
    "docs/architecture/nfl_historical_market_pilot_operational_readiness_0.1.0_claude_review.md": "D95CB4EE863173E4787C8876FBAAC23724E66F7FD8EF829ADB27D55F1D0F5080",
    "docs/architecture/nfl_historical_market_pilot_operational_readiness_0.1.0_freeze_record.md": "A3E92069DC1AFA41E079220F8BEB4ABAF5A9C7730F83B680FAFC477E2D4B2F50",
}


class BoundaryError(ValueError):
    """Messages are static; never include supplied secret/input/error values."""


def _reference(value: str) -> None:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise BoundaryError("explicit non-secret review reference is required")


def _local_path(path: Path) -> Path:
    """Reject network/device paths before resolution or file access."""
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise BoundaryError("absolute local fixed-drive paths are required")
    if os.name == "nt":
        drive_type = ctypes.windll.kernel32.GetDriveTypeW
        drive_type.argtypes = [ctypes.c_wchar_p]
        drive_type.restype = ctypes.c_uint
        if drive_type(path.anchor) != 3:  # DRIVE_FIXED; mapped network drives refused.
            raise BoundaryError("network or non-fixed storage is prohibited")
    # Walk root-first; never resolve/traverse an ancestor's linked target.
    for component in (*reversed(path.parents), path):
        if component.is_symlink() or component.is_junction():
            raise BoundaryError("linked storage paths are prohibited")
    return path.resolve()


def _trust_store_override_present() -> bool:
    # _Environ membership can fetch a value; set intersection iterates NAMES only.
    return bool({"SSL_CERT_FILE", "SSL_CERT_DIR"}.intersection(os.environ))


def _artifact_path(path: Path, repository_root: Path) -> Path:
    """Own namespace only; refuse .env/repo paths before reading any bytes."""
    path = Path(path)
    if not path.is_absolute() or path.suffix != ".json":
        raise BoundaryError("absolute dedicated JSON artifact path is required")
    resolved = _local_path(path)
    if (resolved.parent.name != STORAGE_NAMESPACE
            or resolved.is_relative_to(_local_path(repository_root))
            or not re.fullmatch(r"[A-Za-z0-9_-]+\.json", path.name)):
        raise BoundaryError("artifact must use separate non-linked pilot storage")
    return resolved


def _read_json(path: Path) -> tuple[bytes, dict]:
    # Inputs are specifically designated public JSON, never credential sources.
    result = None
    try:
        raw = path.read_bytes()
        if len(raw) <= 65536:
            value = json.loads(raw)
            if isinstance(value, dict) and raw == core._canonical_json_bytes(value):
                result = (raw, value)
    except (OSError, ValueError, UnicodeError):
        pass
    if result is None:
        raise BoundaryError("public artifact is unavailable or non-canonical")
    return result


def _fingerprint_interactively(public_bytes: bytes) -> str:
    """No injected/env/config key path; fallback echo is an error before input."""
    value = credential = fingerprint = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass("Dedicated NFL pilot key (hidden; never MLB): ")
        if (not isinstance(value, str) or not value or value.strip() != value
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError
        credential = core.SecretCredential(value)
        # Do not retain a key accidentally pasted into a label/reference.
        if value.encode() in public_bytes or quote(value, safe="").encode() in public_bytes:
            raise ValueError
        fingerprint = credential.fingerprint
    except (Exception, KeyboardInterrupt):
        pass
    finally:
        value = credential = None
    # Raised outside except: no key-bearing original exception/context attached.
    if fingerprint is None:
        raise BoundaryError("secure interactive credential entry failed")
    return fingerprint


def _identity_payload(label: str, reference: str, fingerprint: str) -> dict:
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise BoundaryError("dedicated NFL 20K identity label is required")
    _reference(reference)
    if not isinstance(fingerprint, str) or not _SHA.fullmatch(fingerprint):
        raise BoundaryError("frozen credential fingerprint is invalid")
    return {
        "schema": CREDENTIAL_SCHEMA, "identity": label, "fingerprint": fingerprint,
        "quota_attribution_mode": "DEDICATED_CREDENTIAL",
        "provider": "The Odds API", "subscription": "20K",
        "independent_credit_meter": 20000, "historical_entitlement_confirmed": True,
        "verification_reference": reference,
    }


def establish_credential_identity(*, output: Path, repository_root: Path,
                                  label: str, verification_reference: str) -> str:
    """Explicit interactive action; returns only SHA of secret-free artifact."""
    output = _artifact_path(output, repository_root)
    if output.exists():
        raise BoundaryError("credential identity artifact already exists")
    payload = _identity_payload(label, verification_reference, "0" * 64)
    fingerprint = _fingerprint_interactively(core._canonical_json_bytes(payload) + str(output).encode())
    payload["fingerprint"] = fingerprint
    raw = core._canonical_json_bytes(payload)
    core._exclusive_write(output, raw)
    return core._digest(raw)


def load_credential_identity(path: Path, repository_root: Path) -> tuple[bytes, dict]:
    raw, payload = _read_json(_artifact_path(path, repository_root))
    try:
        expected = _identity_payload(payload["identity"], payload["verification_reference"],
                                     payload["fingerprint"])
    except (KeyError, TypeError):
        raise BoundaryError("credential identity artifact is invalid") from None
    if raw != core._canonical_json_bytes(expected):
        raise BoundaryError("credential artifact must contain only dedicated public identity")
    return raw, payload


def verify_credential_interactively(path: Path, repository_root: Path) -> None:
    """Non-executing future re-entry check; never returns a credential object."""
    raw, identity = load_credential_identity(path, repository_root)
    measured = _fingerprint_interactively(raw)
    if not hmac.compare_digest(measured, identity["fingerprint"]):
        raise BoundaryError("dedicated credential fingerprint mismatch")


@dataclass(frozen=True)
class ClockPolicy:
    # Explicit prospective parameters: no assumed approved numeric thresholds.
    approval_reference: str
    max_phase_offset_ms: int
    max_sync_age_seconds: int
    max_measurement_seconds: int
    max_wall_clock_step_ms: int

    def __post_init__(self):
        _reference(self.approval_reference)
        for value in (self.max_phase_offset_ms, self.max_sync_age_seconds,
                      self.max_measurement_seconds, self.max_wall_clock_step_ms):
            if type(value) is not int or value <= 0:
                raise BoundaryError("prospectively approved positive clock limits are required")


@dataclass(frozen=True)
class CandidateRequest:
    candidate_id: str
    approved_head: str
    runtime_identity: str
    dependency_identity: str
    timezone_identity: str
    clock_identity: str
    monotonic_timer_identity: str
    evidence_store_root: Path
    kickoff_package_path: Path
    connect_timeout_seconds: float
    read_timeout_seconds: float
    clock_policy: ClockPolicy


def _windows_timezone_identity() -> str:
    try:
        result = subprocess.run(["tzutil", "/g"], capture_output=True, text=True,
                                timeout=10, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError, AttributeError):
        raise BoundaryError("local Windows timezone could not be verified") from None


def _sync_utc(text: str) -> datetime:
    parsed = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for pattern in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S",
                        "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        raise BoundaryError("last synchronization timestamp is invalid")
    if parsed.tzinfo is None:
        if _windows_timezone_identity() != "Pacific Standard Time":
            raise BoundaryError("naive Windows sync timestamp timezone is not pinned")
        zone = ZoneInfo("America/Los_Angeles")
        first, second = parsed.replace(tzinfo=zone, fold=0), parsed.replace(tzinfo=zone, fold=1)
        if (first.utcoffset() != second.utcoffset()
                or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != parsed):
            raise BoundaryError("ambiguous or nonexistent local synchronization time")
        parsed = first
    return parsed.astimezone(timezone.utc)


def validate_clock(measured: core.RuntimeProvenance, now: datetime,
                   policy: ClockPolicy) -> None:
    core._require_aware(now, "clock validation time")
    core._validate_dynamic_clock_evidence(measured.phase_offset_evidence,
                                         measured.last_successful_sync_evidence)
    if measured.os_sync_source != ACCEPTED_TIME_SOURCE or measured.os_sync_status != "SYNCHRONIZED":
        raise BoundaryError("Windows synchronization source/status mismatch")
    match = re.fullmatch(r"([+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+))(s|ms|us|µs|ns)",
                         measured.phase_offset_evidence.strip(), re.IGNORECASE)
    if match is None:
        raise BoundaryError("phase offset cannot be quantified")
    factors = {"s": Decimal(1000), "ms": Decimal(1), "us": Decimal(".001"),
               "µs": Decimal(".001"), "ns": Decimal(".000001")}
    offset = abs(Decimal(match[1]) * factors[match[2].lower()])
    age = (now - _sync_utc(measured.last_successful_sync_evidence.strip())).total_seconds()
    if offset > policy.max_phase_offset_ms or not 0 <= age <= policy.max_sync_age_seconds:
        raise BoundaryError("clock offset or synchronization freshness exceeds policy")


def _verify_frozen(repository_root: Path, kickoff_package: Path) -> core.FrozenSelection:
    repository_root, kickoff_package = _local_path(repository_root), _local_path(kickoff_package)
    for name, expected in _FROZEN.items():
        if core._digest((repository_root / name).read_bytes()) != expected:
            raise BoundaryError("frozen source or design artifact changed")
    if (not kickoff_package.is_absolute()
            or kickoff_package.name != "NFL_Kickoff_Authority_Reconciliation_0.2.0.zip"
            or core._digest(kickoff_package.read_bytes()) != core.KICKOFF_PACKAGE_SHA256):
        raise BoundaryError("frozen kickoff package identity mismatch")
    with zipfile.ZipFile(kickoff_package) as archive:
        name = "nfl_kickoff_authority_ledger_0.2.0.jsonl"
        if (archive.namelist().count(name) != 1
                or core._digest(archive.read(name)) != core.KICKOFF_LEDGER_SHA256):
            raise BoundaryError("frozen kickoff ledger identity mismatch")
    return core.load_frozen_selection(repository_root /
        "docs/architecture/nfl_historical_market_provider_pilot_selection_manifest_0.1.3.json")


def _request_config(request: CandidateRequest, identity: dict,
                    selection: core.FrozenSelection, output: Path) -> integrated.IntegratedConfig:
    if (str(uuid.UUID(request.candidate_id)) != request.candidate_id
            or uuid.UUID(request.candidate_id).version != 4
            or not _REVISION.fullmatch(request.approved_head)):
        raise BoundaryError("explicit unique candidate ID and approved HEAD are required")
    if not _SHA.fullmatch(request.dependency_identity):
        raise BoundaryError("approved dependency identity is invalid")
    for value in (request.runtime_identity, request.timezone_identity,
                  request.clock_identity, request.monotonic_timer_identity):
        if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
            raise BoundaryError("approved runtime identity is required")
    for timeout in (request.connect_timeout_seconds, request.read_timeout_seconds):
        if type(timeout) not in (int, float) or not 0 < timeout <= 120:
            raise BoundaryError("explicit reviewed transport timeouts are required")
    store = _local_path(request.evidence_store_root)
    if (not store.is_absolute() or store.resolve() != output.parent / "evidence" / request.candidate_id
            or store.exists() or store.is_symlink() or (output.parent / "evidence").is_symlink()
            or (output.parent / "evidence").is_junction()):
        raise BoundaryError("new dedicated candidate evidence-store identity is required")
    timeouts = transport.TransportTimeouts(request.connect_timeout_seconds, request.read_timeout_seconds)
    network = transport.OddsApiHistoricalTransport(timeouts=timeouts)  # identity only, never prepare
    return integrated.IntegratedConfig(
        evidence_store_root=str(store.resolve()), credential_identity=identity["identity"],
        credential_fingerprint=identity["fingerprint"],
        quota_attribution_mode=core.QuotaAttributionMode.DEDICATED_CREDENTIAL,
        implementation_revision=request.approved_head, implementation_sha256=INTEGRATION_SHA,
        repository_head=request.approved_head, repository_clean=True,
        clock_identity=request.clock_identity, monotonic_timer_identity=request.monotonic_timer_identity,
        transport_identity=core.component_runtime_identity(network), runtime_mode=integrated.RUNTIME_MODE,
        runtime_identity=request.runtime_identity, dependency_identity=request.dependency_identity,
        timezone_identity=request.timezone_identity, os_sync_source=ACCEPTED_TIME_SOURCE,
        os_sync_status="SYNCHRONIZED", runtime_inspector_identity=core.RUNTIME_INSPECTOR_ID,
        target_ids=selection.target_ids, timeouts=timeouts,
    )


def _measure(config: integrated.IntegratedConfig, repository_root: Path,
             policy: ClockPolicy) -> tuple[core.RuntimeProvenance, datetime]:
    clock = core.SystemPilotClock()
    start, monotonic = clock.now_utc(), clock.monotonic_ns()
    context = SimpleNamespace(config=config, repository_root=repository_root, clock=clock,
                              _network=transport.OddsApiHistoricalTransport(timeouts=config.timeouts))
    measured = integrated._inspect_runtime(context)
    now = clock.now_utc()
    elapsed = (clock.monotonic_ns() - monotonic) / 1_000_000_000
    if (not 0 <= elapsed <= policy.max_measurement_seconds
            or abs((now - start).total_seconds() - elapsed) * 1000 > policy.max_wall_clock_step_ms):
        raise BoundaryError("provenance measurement duration or wall clock step exceeds policy")
    expected = {
        "repository_root": str(repository_root.resolve()), "git_head": config.repository_head,
        "git_clean": True, "implementation_source_sha256": INTEGRATION_SHA,
        "configuration_sha256": config.sha256, "runtime_identity": config.runtime_identity,
        "dependency_identity": config.dependency_identity, "timezone_identity": config.timezone_identity,
        "evidence_store_root": config.evidence_store_root, "os_sync_source": config.os_sync_source,
        "os_sync_status": config.os_sync_status, "clock_identity": config.clock_identity,
        "monotonic_timer_identity": config.monotonic_timer_identity,
        "transport_identity": config.transport_identity, "runtime_mode": integrated.RUNTIME_MODE,
        "runtime_inspector_identity": core.RUNTIME_INSPECTOR_ID,
    }
    actual = measured.canonical_payload()
    actual.pop("phase_offset_evidence", None)
    actual.pop("last_successful_sync_evidence", None)
    if (actual != expected or core.component_runtime_identity(clock) != config.clock_identity
            or clock.monotonic_identity != config.monotonic_timer_identity):
        raise BoundaryError("measured repository/runtime/clock identity mismatch")
    validate_clock(measured, now, policy)
    return measured, now


def _reviewed_bindings(config: integrated.IntegratedConfig) -> dict:
    """Pre-authorization bindings, deliberately without ANY activation metadata."""
    return {
        "protocol": {"identity": core.PROTOCOL_ID, "sha256": core.PROTOCOL_SHA256},
        "pilot_spec": {"identity": core.PILOT_SPEC_ID, "sha256": core.PILOT_SPEC_SHA256},
        "selection_manifest": {"identity": core.SELECTION_ID, "sha256": core.SELECTION_SHA256},
        "kickoff_authority": {"package_zip_sha256": core.KICKOFF_PACKAGE_SHA256,
                              "authority_ledger_sha256": core.KICKOFF_LEDGER_SHA256},
        "implementation": {"identity": integrated.IMPLEMENTATION_ID,
                           "git_revision": config.implementation_revision, "sha256": INTEGRATION_SHA},
        "components": config.component_bundle(), "configuration_sha256": config.sha256,
        "repository": {"head": config.repository_head, "clean": True},
        "credential": {"identity": config.credential_identity, "fingerprint": config.credential_fingerprint,
                       "quota_attribution_mode": "DEDICATED_CREDENTIAL"},
        "evidence_store_root": config.evidence_store_root, "clock_identity": config.clock_identity,
        "runtime_mode": integrated.RUNTIME_MODE, "target_ids": list(config.target_ids),
        "ceilings": {"primary": 20, "retries": 20, "attempts": 40,
                     "per_attempt_reservation": 10, "credits": 400},
        "execution_policy": {"mode": "INITIAL_ONLY_NO_CONTINUATION",
                             "predecessor_evidence_manifest_sha256": None},
    }


def _assert_pre_authorization(value) -> None:
    """Every JSON object must be activation-free and admission-incomplete."""
    if isinstance(value, dict):
        keys = set(value)
        if keys & ACTIVATION_ONLY_FIELDS:
            raise BoundaryError("activation-only authority fields are forbidden in candidates")
        if (FROZEN_CORE_AUTHORIZATION_FIELDS <= keys
                or FROZEN_INTEGRATED_AUTHORIZATION_FIELDS <= keys):
            raise BoundaryError("admission-complete objects are forbidden in candidates")
        for child in value.values():
            _assert_pre_authorization(child)
    elif isinstance(value, list):
        for child in value:
            _assert_pre_authorization(child)


def _activation_requirements() -> dict:
    # Names only, never placeholder values or a future active window.
    return {"separate_review_and_authorization_required": True,
            "activation_implemented": False,
            "omitted_loader_fields": sorted(ACTIVATION_ONLY_FIELDS)}


def build_candidate(*, request: CandidateRequest, credential_artifact: Path,
                    output: Path, repository_root: Path) -> str:
    """Explicit candidate write only. Does not instantiate an executor or key."""
    repository_root = _local_path(repository_root)
    output = _artifact_path(output, repository_root)
    if output.name != "candidate-" + request.candidate_id + ".json" or output.exists():
        raise BoundaryError("unique non-existing candidate path is required")
    # Name-only launch-policy checks: never read values or mutate MLB/process env.
    if _trust_store_override_present():
        raise BoundaryError("ambient trust-store overrides require separate launch-policy review")
    raw, identity = load_credential_identity(credential_artifact, repository_root)
    if credential_artifact.resolve().parent != output.parent:
        raise BoundaryError("candidate and identity require the same dedicated storage namespace")
    selection = _verify_frozen(repository_root, request.kickoff_package_path)
    config = _request_config(request, identity, selection, output)
    integrated.validate_runtime_config(config, selection)
    measured, initial_time = _measure(config, repository_root, request.clock_policy)
    # Recheck governed files and credential bytes, then remeasure immediately before write.
    _verify_frozen(repository_root, request.kickoff_package_path)
    repeated, _ = load_credential_identity(credential_artifact, repository_root)
    if repeated != raw:
        raise BoundaryError("credential identity changed during construction")
    final, now = _measure(config, repository_root, request.clock_policy)
    _artifact_path(output, repository_root)
    _request_config(request, identity, selection, output)
    if now < initial_time or _trust_store_override_present():
        raise BoundaryError("candidate observation chronology or launch policy changed")
    envelope = {
        "schema": CANDIDATE_SCHEMA, "status": "CANDIDATE ONLY — NOT EXECUTION AUTHORITY",
        "candidate_id": request.candidate_id,
        "execution_authorized": False, "builder_identity": BUILDER_ID,
        "builder_source_sha256": core._digest(Path(__file__).read_bytes()),
        "credential_artifact_sha256": core._digest(raw), "population_sha256": selection.population_sha256,
        "configuration": config.canonical_payload(), "clock_policy": asdict(request.clock_policy),
        "accepted_time_source": ACCEPTED_TIME_SOURCE, "local_timezone_policy": "Pacific Standard Time/America/Los_Angeles",
        "trust_store_policy": "NO_AMBIENT_SSL_CERT_FILE_OR_SSL_CERT_DIR",
        "initial_provenance": measured.canonical_payload(), "final_provenance": final.canonical_payload(),
        "measured_at": core._utc_text(now),
        "reviewed_bindings": _reviewed_bindings(config),
        "activation_requirements": _activation_requirements(),
    }
    _assert_pre_authorization(envelope)
    encoded = core._canonical_json_bytes(envelope)
    core._exclusive_write(output, encoded)
    return core._digest(encoded)


def validate_candidate(*, request: CandidateRequest, credential_artifact: Path,
                       candidate: Path, repository_root: Path) -> str:
    """Read-only revalidation and fresh host gates; never execution admission."""
    candidate = _artifact_path(candidate, repository_root)
    if candidate.name != "candidate-" + request.candidate_id + ".json":
        raise BoundaryError("candidate path identity mismatch")
    raw, envelope = _read_json(candidate)
    _assert_pre_authorization(envelope)
    credential_raw, identity = load_credential_identity(credential_artifact, repository_root)
    if credential_artifact.resolve().parent != candidate.parent:
        raise BoundaryError("credential and candidate storage mismatch")
    selection = _verify_frozen(repository_root, request.kickoff_package_path)
    config = _request_config(request, identity, selection, candidate)
    integrated.validate_runtime_config(config, selection)
    fresh, now = _measure(config, repository_root, request.clock_policy)
    expected = {
        "schema": CANDIDATE_SCHEMA, "status": "CANDIDATE ONLY — NOT EXECUTION AUTHORITY",
        "candidate_id": request.candidate_id,
        "execution_authorized": False, "builder_identity": BUILDER_ID,
        "builder_source_sha256": core._digest(Path(__file__).read_bytes()),
        "credential_artifact_sha256": core._digest(credential_raw), "population_sha256": selection.population_sha256,
        "configuration": config.canonical_payload(), "clock_policy": asdict(request.clock_policy),
        "accepted_time_source": ACCEPTED_TIME_SOURCE, "local_timezone_policy": "Pacific Standard Time/America/Los_Angeles",
        "trust_store_policy": "NO_AMBIENT_SSL_CERT_FILE_OR_SSL_CERT_DIR",
        "reviewed_bindings": _reviewed_bindings(config),
        "activation_requirements": _activation_requirements(),
    }
    retained_keys = {"measured_at", "initial_provenance", "final_provenance"}
    if set(envelope) != set(expected) | retained_keys:
        raise BoundaryError("candidate schema has missing or unexpected fields")
    stable = {name: envelope[name] for name in expected}
    if core._canonical_json_bytes(stable) != core._canonical_json_bytes(expected):
        raise BoundaryError("candidate frozen/configuration/credential/policy binding mismatch")
    created = core._parse_timestamp(envelope["measured_at"])
    if created > now:
        raise BoundaryError("candidate observation chronology is implausible")
    for name in ("initial_provenance", "final_provenance"):
        retained = envelope[name].copy()
        dynamic = ("phase_offset_evidence", "last_successful_sync_evidence")
        current = fresh.canonical_payload()
        if (set(retained) != set(current)
                or core._canonical_json_bytes({k: v for k, v in retained.items() if k not in dynamic})
                != core._canonical_json_bytes({k: v for k, v in current.items() if k not in dynamic})):
            raise BoundaryError("retained candidate runtime binding mismatch")
        validate_clock(core.RuntimeProvenance(**retained), created, request.clock_policy)
    if _trust_store_override_present():
        raise BoundaryError("ambient trust-store overrides require separate launch-policy review")
    repeated, _ = load_credential_identity(credential_artifact, repository_root)
    if repeated != credential_raw or candidate.read_bytes() != raw:
        raise BoundaryError("candidate or credential artifact changed during validation")
    return core._digest(raw)


def _load_request(path: Path, repository_root: Path) -> CandidateRequest:
    _, value = _read_json(_artifact_path(path, repository_root))
    try:
        value["clock_policy"] = ClockPolicy(**value["clock_policy"])
        for key in ("evidence_store_root", "kickoff_package_path"):
            value[key] = Path(value[key])
        return CandidateRequest(**value)
    except (KeyError, TypeError, ValueError):
        raise BoundaryError("explicit secret-free candidate request is invalid") from None


class _PublicArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes rejected argv values; never do so here.
        self.exit(2, "Invalid non-secret NFL pilot command arguments.\n")


def main(argv: list[str] | None = None) -> int:
    parser = _PublicArgumentParser(description="NFL pilot non-executing identity/candidate tools")
    commands = parser.add_subparsers(dest="action", required=True)
    establish = commands.add_parser("establish-credential")
    establish.add_argument("--label", required=True)
    establish.add_argument("--verification-reference", required=True)
    establish.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify-credential")
    verify.add_argument("--credential-artifact", type=Path, required=True)
    build = commands.add_parser("build-candidate")
    build.add_argument("--request", type=Path, required=True)
    build.add_argument("--credential-artifact", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate-candidate")
    validate.add_argument("--request", type=Path, required=True)
    validate.add_argument("--credential-artifact", type=Path, required=True)
    validate.add_argument("--candidate", type=Path, required=True)
    for command in (establish, verify, build, validate):
        command.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "establish-credential":
            artifact_sha = establish_credential_identity(output=args.output, repository_root=args.repository_root,
                                          label=args.label, verification_reference=args.verification_reference)
            artifact_path = args.output
        elif args.action == "verify-credential":
            verify_credential_interactively(args.credential_artifact, args.repository_root)
        elif args.action == "build-candidate":
            artifact_sha = build_candidate(request=_load_request(args.request, args.repository_root),
                            credential_artifact=args.credential_artifact, output=args.output,
                            repository_root=args.repository_root)
            artifact_path = args.output
        else:
            artifact_sha = validate_candidate(request=_load_request(args.request, args.repository_root),
                               credential_artifact=args.credential_artifact, candidate=args.candidate,
                               repository_root=args.repository_root)
            artifact_path = args.candidate
        if args.action != "verify-credential":
            report_path = str(_artifact_path(artifact_path, args.repository_root))
    except (Exception, KeyboardInterrupt):
        print("NFL pilot non-executing action refused; no provider execution authorized.")
        return 1
    print("NFL pilot public artifact/check complete; NOT EXECUTION AUTHORITY.")
    if args.action != "verify-credential":
        print("Artifact path: " + report_path)
        print("Artifact SHA-256: " + artifact_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
