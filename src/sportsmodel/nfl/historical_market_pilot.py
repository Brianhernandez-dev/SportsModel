"""Offline-safe execution machinery for the frozen NFL provider pilot design.

The module deliberately contains no real HTTP implementation, environment-secret
lookup, database access, model access, or execution authorization.  A future run
must inject a transport, credential value, and separately reviewed single-use
authorization whose identities match the frozen design.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import gzip
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import time
from typing import Any, Protocol
import zlib


PROTOCOL_ID = "nfl_historical_market_research_0.2.5"
PROTOCOL_SHA256 = "09FB79F12FD9B555E4C6A362DA5E459D45F91295DB42F0582E8B1FA7E461DAA7"
PILOT_SPEC_ID = "nfl_historical_market_provider_pilot_spec_0.1.3"
PILOT_SPEC_SHA256 = "9D7DF04DF7076C3C0A397BCD1FB3719D37C7434508EA33FA9154A165EEA628E6"
SELECTION_ID = "nfl_historical_market_provider_pilot_selection_manifest_0.1.3"
SELECTION_SHA256 = "01E7D6B32BDE9965EBD7B149DB6B4C5E9085C631830E1F1701D3A31D70BE8530"
KICKOFF_PACKAGE_SHA256 = "2422D97F2A21D9171286AD6F62D5F7D1957993476872AAD936DC627474A2D971"
KICKOFF_LEDGER_SHA256 = "4A1C2962FF2526924FFA8AFC0275788B423B4848318043609BFF194C0049063D"
POPULATION_SHA256 = "38B71B797782DB67DDA9CB5770762618BB99CAAD29FD3E4607B275537052B39F"
IMPLEMENTATION_ID = "nfl_historical_market_provider_pilot_execution_0.1.4"
RUNTIME_MODE = "OFFLINE_ONLY"
RUNTIME_INSPECTOR_ID = "sportsmodel.local_runtime_provenance_inspector.v1"
CREDENTIAL_FINGERPRINT_DOMAIN = b"SPORTSMODEL_ODDS_CREDENTIAL_V1\0"

MAX_PRIMARY_CALLS = 20
MAX_RETRY_CALLS = 20
MAX_ATTEMPTS = 40
RESERVED_CREDITS_PER_ATTEMPT = 10
MAX_RESERVED_CREDITS = 400
EXPECTED_BOOKS = ("draftkings", "fanduel", "betmgm", "betrivers")
EXPECTED_SPORT = "americanfootball_nfl"
EXPECTED_MARKET = "h2h"

_SHA256 = re.compile(r"[0-9A-Fa-f]{64}")
_REVISION = re.compile(r"(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})"
)
_FORBIDDEN_RESPONSE_KEYS = frozenset(
    {
        "home_score",
        "away_score",
        "final_score",
        "winner",
        "settlement",
        "settled_side",
        "result",
        "model_probability",
        "model_probabilities",
        "prediction",
        "predictions",
        "edge",
        "wager",
        "wagers",
        "roi",
        "performance",
        "profit_loss",
        "training_data",
    }
)

TEAM_PROVIDER_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos",
    "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
    "LAC": "Los Angeles Chargers", "LA": "Los Angeles Rams",
    "LAR": "Los Angeles Rams", "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints",
    "NYG": "New York Giants", "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}


class PilotError(RuntimeError):
    """Base fail-closed pilot error with intentionally non-secret messages."""


class AuthorizationError(PilotError):
    pass


class EvidenceIntegrityError(PilotError):
    pass


class EvidenceCollisionError(EvidenceIntegrityError):
    pass


class EvidenceIOError(EvidenceIntegrityError):
    pass


class TerminalPilotError(PilotError):
    pass


class ProhibitedDataError(TerminalPilotError):
    pass


class QuotaIntegrityError(TerminalPilotError):
    pass


class IdentityError(TerminalPilotError):
    pass


class AttemptState(StrEnum):
    RESERVED = "RESERVED"
    PROVABLE_PRE_SEND_FAILURE = "PROVABLE_PRE_SEND_FAILURE"
    SENT = "SENT"
    RESPONSE_CAPTURED = "RESPONSE_CAPTURED"
    SENT_UNKNOWN = "SENT_UNKNOWN"
    TERMINAL_STOP = "TERMINAL_STOP"


class AttemptKind(StrEnum):
    PRIMARY = "PRIMARY"
    RETRY = "RETRY"


class QuotaAttributionMode(StrEnum):
    DEDICATED_CREDENTIAL = "DEDICATED_CREDENTIAL"
    QUIET_WINDOW = "QUIET_WINDOW"


class PilotDisposition(StrEnum):
    SUFFICIENT = "PILOT_PROVIDER_EVIDENCE_SUFFICIENT"
    REVISION_REQUIRED = "PILOT_PROVIDER_EVIDENCE_REVISION_REQUIRED"
    FAILED = "PILOT_PROVIDER_FEASIBILITY_FAILED"


class PreSendFailureKind(StrEnum):
    DNS = "DNS_PRE_SEND"
    CONNECT = "CONNECT_PRE_SEND"
    TLS = "TLS_PRE_SEND"


class ReceiveFailureKind(StrEnum):
    POSSIBLE_SEND = "POSSIBLE_SEND"
    RESET_AFTER_SEND = "RESET_AFTER_SEND"
    PARTIAL_RESPONSE = "PARTIAL_RESPONSE"


class CompleteResponseAction(StrEnum):
    CONTINUE = "CONTINUE"
    RETRY = "RETRY"
    TERMINAL = "TERMINAL"


class ProvablePreSendFailure(Exception):
    def __init__(self, kind: PreSendFailureKind):
        super().__init__(kind.value)
        self.kind = kind


class PossibleSendFailure(Exception):
    def __init__(self, kind: ReceiveFailureKind):
        super().__init__(kind.value)
        self.kind = kind


class LexicalNumber(str):
    """Original JSON numeric token retained without binary-float conversion."""


@dataclass(frozen=True)
class FrozenTarget:
    canonical_game_id: str
    home_team: str
    away_team: str
    kickoff_utc: str
    requested_date: str
    canonical_request: str
    canonical_request_sha256: str
    authority_version_chain: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class FrozenSelection:
    targets: tuple[FrozenTarget, ...]
    raw_sha256: str
    population_sha256: str

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(target.canonical_game_id for target in self.targets)


@dataclass(frozen=True)
class PilotExecutionConfig:
    evidence_store_root: str
    credential_identity: str
    credential_fingerprint: str
    quota_attribution_mode: QuotaAttributionMode
    implementation_revision: str
    implementation_sha256: str
    repository_head: str
    repository_clean: bool
    clock_identity: str
    monotonic_timer_identity: str
    transport_identity: str
    runtime_mode: str
    runtime_identity: str
    dependency_identity: str
    timezone_identity: str
    os_sync_source: str
    os_sync_status: str
    runtime_inspector_identity: str
    target_ids: tuple[str, ...]
    primary_ceiling: int = MAX_PRIMARY_CALLS
    retry_ceiling: int = MAX_RETRY_CALLS
    attempt_ceiling: int = MAX_ATTEMPTS
    credit_ceiling: int = MAX_RESERVED_CREDITS
    per_attempt_reservation: int = RESERVED_CREDITS_PER_ATTEMPT

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "attempt_ceiling": self.attempt_ceiling,
            "clock_identity": self.clock_identity,
            "credit_ceiling": self.credit_ceiling,
            "credential_identity": self.credential_identity,
            "credential_fingerprint": self.credential_fingerprint.upper(),
            "dependency_identity": self.dependency_identity,
            "evidence_store_root": str(Path(self.evidence_store_root).resolve()),
            "implementation_revision": self.implementation_revision,
            "implementation_sha256": self.implementation_sha256.upper(),
            "monotonic_timer_identity": self.monotonic_timer_identity,
            "os_sync_source": self.os_sync_source,
            "os_sync_status": self.os_sync_status,
            "per_attempt_reservation": self.per_attempt_reservation,
            "primary_ceiling": self.primary_ceiling,
            "quota_attribution_mode": self.quota_attribution_mode.value,
            "repository_clean": self.repository_clean,
            "repository_head": self.repository_head,
            "retry_ceiling": self.retry_ceiling,
            "runtime_identity": self.runtime_identity,
            "runtime_inspector_identity": self.runtime_inspector_identity,
            "runtime_mode": self.runtime_mode,
            "target_ids": list(self.target_ids),
            "timezone_identity": self.timezone_identity,
            "transport_identity": self.transport_identity,
        }

    @property
    def sha256(self) -> str:
        return _digest(_canonical_json_bytes(self.canonical_payload(), terminal_lf=False))


@dataclass(frozen=True)
class ExecutionAuthorization:
    source_path: Path
    raw_bytes: bytes
    sha256: str
    authorization_id: str
    authorizer_reference: str
    authorized_at: datetime
    window_start: datetime
    window_end: datetime
    configuration_sha256: str

    def validate_unchanged(self) -> None:
        try:
            current = self.source_path.read_bytes()
        except OSError as error:
            raise AuthorizationError("authorization artifact is unavailable") from error
        if _digest(current) != self.sha256 or current != self.raw_bytes:
            raise AuthorizationError("authorization artifact changed during execution")


@dataclass(frozen=True, repr=False)
class SecretCredential:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("credential value is empty")

    def __repr__(self) -> str:
        return "SecretCredential([REDACTED])"

    def __str__(self) -> str:
        return "[REDACTED]"

    @property
    def fingerprint(self) -> str:
        return _digest(CREDENTIAL_FINGERPRINT_DOMAIN + self.value.encode("utf-8"))


@dataclass(frozen=True)
class RuntimeProvenance:
    repository_root: str
    git_head: str
    git_clean: bool
    implementation_source_sha256: str
    configuration_sha256: str
    runtime_identity: str
    dependency_identity: str
    timezone_identity: str
    evidence_store_root: str
    os_sync_source: str
    os_sync_status: str
    phase_offset_evidence: str
    last_successful_sync_evidence: str
    monotonic_timer_identity: str
    transport_identity: str
    clock_identity: str
    runtime_mode: str
    runtime_inspector_identity: str

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "clock_identity": self.clock_identity,
            "configuration_sha256": self.configuration_sha256,
            "dependency_identity": self.dependency_identity,
            "evidence_store_root": self.evidence_store_root,
            "git_clean": self.git_clean,
            "git_head": self.git_head,
            "implementation_source_sha256": self.implementation_source_sha256,
            "monotonic_timer_identity": self.monotonic_timer_identity,
            "os_sync_source": self.os_sync_source,
            "os_sync_status": self.os_sync_status,
            "phase_offset_evidence": self.phase_offset_evidence,
            "last_successful_sync_evidence": self.last_successful_sync_evidence,
            "repository_root": self.repository_root,
            "runtime_identity": self.runtime_identity,
            "runtime_inspector_identity": self.runtime_inspector_identity,
            "runtime_mode": self.runtime_mode,
            "timezone_identity": self.timezone_identity,
            "transport_identity": self.transport_identity,
        }

    @property
    def sha256(self) -> str:
        return _digest(_canonical_json_bytes(self.canonical_payload(), terminal_lf=False))

    @property
    def artifact_sha256(self) -> str:
        return _digest(_canonical_json_bytes(self.canonical_payload()))


@dataclass(frozen=True)
class RecoveryRuntimeProvenance:
    repository_root: str
    git_head: str
    git_clean: bool
    implementation_source_sha256: str
    configuration_sha256: str
    runtime_identity: str
    dependency_identity: str
    timezone_identity: str
    os_sync_source: str
    os_sync_status: str
    phase_offset_evidence: str
    last_successful_sync_evidence: str
    monotonic_timer_identity: str
    clock_identity: str
    recovery_mode: str
    runtime_inspector_identity: str

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "clock_identity": self.clock_identity,
            "configuration_sha256": self.configuration_sha256,
            "dependency_identity": self.dependency_identity,
            "git_clean": self.git_clean,
            "git_head": self.git_head,
            "implementation_source_sha256": self.implementation_source_sha256,
            "monotonic_timer_identity": self.monotonic_timer_identity,
            "os_sync_source": self.os_sync_source,
            "os_sync_status": self.os_sync_status,
            "phase_offset_evidence": self.phase_offset_evidence,
            "last_successful_sync_evidence": self.last_successful_sync_evidence,
            "recovery_mode": self.recovery_mode,
            "repository_root": self.repository_root,
            "runtime_identity": self.runtime_identity,
            "runtime_inspector_identity": self.runtime_inspector_identity,
            "timezone_identity": self.timezone_identity,
        }

    @property
    def artifact_sha256(self) -> str:
        return _digest(_canonical_json_bytes(self.canonical_payload()))


@dataclass(frozen=True)
class ProviderRequest:
    target_id: str
    method: str
    path: str
    query: str
    canonical_bytes: bytes
    canonical_sha256: str

    @property
    def redacted_as_sent_url(self) -> str:
        return (
            f"https://api.the-odds-api.com{self.path}?{self.query}"
            "&apiKey=%5BREDACTED%5D"
        )


@dataclass(frozen=True)
class ProviderResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class ProviderExchange(Protocol):
    def receive(self) -> ProviderResponse: ...


class ProviderTransport(Protocol):
    @property
    def runtime_identity(self) -> str: ...

    def begin(
        self, request: ProviderRequest, credential: SecretCredential
    ) -> ProviderExchange: ...


class PilotClock(Protocol):
    @property
    def runtime_identity(self) -> str: ...

    @property
    def monotonic_identity(self) -> str: ...

    def now_utc(self) -> datetime: ...

    def monotonic_ns(self) -> int: ...

    def sleep(self, seconds: int) -> None: ...


@dataclass(frozen=True)
class FakeTransportStep:
    """One deterministic, in-memory transport outcome for offline tests."""

    response: ProviderResponse | None = None
    begin_failure: ProvablePreSendFailure | PossibleSendFailure | None = None
    receive_failure: PossibleSendFailure | None = None

    def __post_init__(self) -> None:
        populated = sum(
            item is not None
            for item in (self.response, self.begin_failure, self.receive_failure)
        )
        if populated != 1:
            raise ValueError("fake transport step requires exactly one outcome")


class _FakeExchange:
    def __init__(self, step: FakeTransportStep):
        self._step = step

    def receive(self) -> ProviderResponse:
        if self._step.receive_failure is not None:
            raise self._step.receive_failure
        if self._step.response is None:
            raise AssertionError("fake exchange has no response")
        return self._step.response


class DeterministicFakeTransport:
    """Offline-only scripted transport; it contains no socket or HTTP code."""

    def __init__(
        self,
        steps: Sequence[FakeTransportStep],
        *,
        before_begin: Callable[[ProviderRequest], None] | None = None,
    ):
        self._steps = list(steps)
        self._before_begin = before_begin
        self.requests: list[ProviderRequest] = []

    @property
    def runtime_identity(self) -> str:
        return "sportsmodel.deterministic_fake_transport.v1:OFFLINE_ONLY"

    def begin(
        self, request: ProviderRequest, credential: SecretCredential
    ) -> ProviderExchange:
        del credential
        if self._before_begin is not None:
            self._before_begin(request)
        if not self._steps:
            raise AssertionError("fake transport script is exhausted")
        self.requests.append(request)
        step = self._steps.pop(0)
        if step.begin_failure is not None:
            raise step.begin_failure
        return _FakeExchange(step)


class SystemPilotClock:
    @property
    def runtime_identity(self) -> str:
        return "python.datetime.now.utc.v1"

    @property
    def monotonic_identity(self) -> str:
        implementation = time.get_clock_info("monotonic").implementation
        return f"python.monotonic_ns.v1:{implementation}"

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def sleep(self, seconds: int) -> None:
        time.sleep(seconds)


def component_runtime_identity(component: object) -> str:
    component_type = type(component)
    declared = getattr(component, "runtime_identity", None)
    if not isinstance(declared, str) or not declared:
        raise AuthorizationError("runtime component identity is missing")
    return (
        f"{component_type.__module__}.{component_type.__qualname__}"
        f"|{declared}"
    )


_PHASE_OFFSET = re.compile(
    r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:s|ms|us|µs|ns)", re.IGNORECASE
)


def _validate_dynamic_clock_evidence(phase_offset: str, last_sync: str) -> None:
    if not isinstance(phase_offset, str) or not _PHASE_OFFSET.fullmatch(
        phase_offset.strip()
    ):
        raise AuthorizationError("Windows phase-offset evidence is invalid")
    if not isinstance(last_sync, str) or not last_sync.strip():
        raise AuthorizationError("Windows last-sync evidence is invalid")
    value = last_sync.strip()
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return
    except ValueError:
        pass
    for pattern in (
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M",
    ):
        try:
            datetime.strptime(value, pattern)
            return
        except ValueError:
            continue
    raise AuthorizationError("Windows last-sync evidence is invalid")


class LocalRuntimeProvenanceInspector:
    """Measure local runtime identity without network or provider access."""

    def __init__(self, repository_root: Path):
        self.repository_root = repository_root.resolve()

    def inspect(
        self,
        *,
        config: PilotExecutionConfig,
        transport: ProviderTransport,
        clock: PilotClock,
    ) -> RuntimeProvenance:
        git_root = self._git("rev-parse", "--show-toplevel")
        measured_root = Path(git_root).resolve()
        head = self._git("rev-parse", "HEAD")
        clean = not bool(self._git("status", "--porcelain", "--untracked-files=all"))
        implementation_path = Path(__file__).resolve()
        dependency_identity = self._dependency_identity(measured_root)
        try:
            tzdata_version = importlib.metadata.version("tzdata")
        except importlib.metadata.PackageNotFoundError as error:
            raise AuthorizationError("tzdata runtime identity is unavailable") from error
        sync_source, sync_status, phase_offset, last_sync = (
            self._windows_time_evidence()
        )
        runtime_identity = (
            f"{platform.python_implementation()}-{platform.python_version()}"
            f":{Path(sys.executable).resolve()}"
        )
        return RuntimeProvenance(
            repository_root=str(measured_root),
            git_head=head,
            git_clean=clean,
            implementation_source_sha256=_digest(implementation_path.read_bytes()),
            configuration_sha256=config.sha256,
            runtime_identity=runtime_identity,
            dependency_identity=dependency_identity,
            timezone_identity=f"tzdata:{tzdata_version}",
            evidence_store_root=str(Path(config.evidence_store_root).resolve()),
            os_sync_source=sync_source,
            os_sync_status=sync_status,
            phase_offset_evidence=phase_offset,
            last_successful_sync_evidence=last_sync,
            monotonic_timer_identity=clock.monotonic_identity,
            transport_identity=component_runtime_identity(transport),
            clock_identity=component_runtime_identity(clock),
            runtime_mode=RUNTIME_MODE,
            runtime_inspector_identity=RUNTIME_INSPECTOR_ID,
        )

    def inspect_recovery(
        self,
        *,
        config: PilotExecutionConfig,
        clock: PilotClock,
    ) -> RecoveryRuntimeProvenance:
        git_root = self._git("rev-parse", "--show-toplevel")
        measured_root = Path(git_root).resolve()
        head = self._git("rev-parse", "HEAD")
        clean = not bool(self._git("status", "--porcelain", "--untracked-files=all"))
        implementation_path = Path(__file__).resolve()
        dependency_identity = self._dependency_identity(measured_root)
        try:
            tzdata_version = importlib.metadata.version("tzdata")
        except importlib.metadata.PackageNotFoundError as error:
            raise AuthorizationError("tzdata runtime identity is unavailable") from error
        sync_source, sync_status, phase_offset, last_sync = (
            self._windows_time_evidence()
        )
        runtime_identity = (
            f"{platform.python_implementation()}-{platform.python_version()}"
            f":{Path(sys.executable).resolve()}"
        )
        return RecoveryRuntimeProvenance(
            repository_root=str(measured_root),
            git_head=head,
            git_clean=clean,
            implementation_source_sha256=_digest(implementation_path.read_bytes()),
            configuration_sha256=config.sha256,
            runtime_identity=runtime_identity,
            dependency_identity=dependency_identity,
            timezone_identity=f"tzdata:{tzdata_version}",
            os_sync_source=sync_source,
            os_sync_status=sync_status,
            phase_offset_evidence=phase_offset,
            last_successful_sync_evidence=last_sync,
            monotonic_timer_identity=clock.monotonic_identity,
            clock_identity=component_runtime_identity(clock),
            recovery_mode="RECOVERY_ONLY",
            runtime_inspector_identity=RUNTIME_INSPECTOR_ID,
        )

    def _git(self, *arguments: str) -> str:
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.repository_root), *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise AuthorizationError("local Git runtime inspection failed") from error
        if completed.returncode != 0:
            raise AuthorizationError("local Git runtime inspection failed")
        return completed.stdout.strip()

    @staticmethod
    def _dependency_identity(repository_root: Path) -> str:
        names = ("pyproject.toml", "uv.lock", "poetry.lock", "requirements.txt")
        records = []
        for name in names:
            path = repository_root / name
            if path.is_file():
                records.append({"path": name, "sha256": _digest(path.read_bytes())})
        if not records:
            raise AuthorizationError("dependency identity inputs are unavailable")
        return _digest(_canonical_json_bytes(records, terminal_lf=False))

    @staticmethod
    def _windows_time_evidence() -> tuple[str, str, str, str]:
        if os.name != "nt":
            raise AuthorizationError("OS clock synchronization evidence is unsupported")
        try:
            completed = subprocess.run(
                ["w32tm", "/query", "/status", "/verbose"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise AuthorizationError("Windows clock synchronization inspection failed") from error
        if completed.returncode != 0:
            raise AuthorizationError("Windows clock synchronization inspection failed")
        values = {}
        for line in completed.stdout.splitlines():
            if ":" in line:
                name, value = line.split(":", 1)
                values[name.strip().lower()] = value.strip()
        source = values.get("source")
        offset = values.get("phase offset")
        last_sync = values.get("last successful sync time")
        leap = values.get("leap indicator", "")
        if (
            not source
            or source.lower() in {"local cmos clock", "free-running system clock"}
            or not offset
            or not last_sync
            or leap.startswith("3")
        ):
            raise AuthorizationError("Windows clock synchronization is not proven")
        _validate_dynamic_clock_evidence(offset, last_sync)
        return source, "SYNCHRONIZED", offset, last_sync


@dataclass(frozen=True)
class MarketObservation:
    bookmaker_key: str
    bookmaker_last_update: str | None
    market_last_update: str | None
    classification: str
    timestamp_eligible: bool
    snapshot_age_ms: int | None
    market_minus_response_ms: int | None
    age_bin: str | None
    prices: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ResponseAnalysis:
    wrapper_timestamp: str
    previous_timestamp: str | None
    next_timestamp: str | None
    target_event_id: str | None
    target_found: bool
    observations: tuple[MarketObservation, ...]
    non_target_event_count: int
    empty_data: bool
    revision_required: bool
    response_snapshot_age_ms: int
    previous_interval_ms: int | None
    next_interval_ms: int | None


@dataclass(frozen=True)
class QuotaSnapshot:
    used: int
    remaining: int
    last: int


@dataclass(frozen=True)
class AttemptCounters:
    primary: int
    retries: int
    attempts: int
    reserved_credits: int


@dataclass(frozen=True)
class TargetExecutionResult:
    target_id: str
    terminal: bool
    retry_count: int
    analysis: ResponseAnalysis | None
    failure_reason: str | None


@dataclass(frozen=True)
class PilotReport:
    disposition: PilotDisposition
    target_results: tuple[TargetExecutionResult, ...]
    terminal_reason: str | None


def load_frozen_selection(path: Path) -> FrozenSelection:
    raw = path.read_bytes()
    if _digest(raw) != SELECTION_SHA256:
        raise EvidenceIntegrityError("frozen selection manifest SHA-256 mismatch")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceIntegrityError("frozen selection manifest is not valid JSON") from error
    if payload.get("manifest_id") != SELECTION_ID:
        raise EvidenceIntegrityError("frozen selection manifest identity mismatch")
    if payload.get("pilot_spec") != {
        "identity": PILOT_SPEC_ID,
        "sha256": PILOT_SPEC_SHA256,
    }:
        raise EvidenceIntegrityError("frozen pilot specification identity mismatch")
    protocol = payload.get("governing_protocol")
    if protocol != {"identity": PROTOCOL_ID, "sha256": PROTOCOL_SHA256}:
        raise EvidenceIntegrityError("frozen protocol identity mismatch")
    kickoff = payload.get("kickoff_authority", {})
    if (
        kickoff.get("package_zip_sha256") != KICKOFF_PACKAGE_SHA256
        or kickoff.get("authority_ledger_sha256") != KICKOFF_LEDGER_SHA256
    ):
        raise EvidenceIntegrityError("kickoff authority identity mismatch")
    population = payload.get("population", {})
    if (
        population.get("eligible_population_count") != 1359
        or population.get("source_population_count") != 1359
        or population.get("eligible_population_sha256") != POPULATION_SHA256
        or population.get("source_population_sha256") != POPULATION_SHA256
        or population.get("excluded_provenance_failure_game_ids") != []
    ):
        raise EvidenceIntegrityError("frozen population identity mismatch")
    raw_targets = payload.get("selected_targets")
    if (
        not isinstance(raw_targets, list)
        or len(raw_targets) != 20
        or payload.get("selected_target_count") != 20
        or payload.get("deduplicated_primary_request_count") != 20
    ):
        raise EvidenceIntegrityError("frozen target count mismatch")
    targets = []
    requests: set[str] = set()
    identifiers: set[str] = set()
    for item in raw_targets:
        request_text = item.get("canonical_provider_request")
        if not isinstance(request_text, str):
            raise EvidenceIntegrityError("canonical provider request is missing")
        request_bytes = request_text.encode("utf-8")
        request_hash = _digest(request_bytes)
        if request_hash != item.get("canonical_provider_request_sha256"):
            raise EvidenceIntegrityError("canonical provider request hash mismatch")
        _validate_canonical_request(request_text, item.get("requested_date"))
        target_id = item.get("canonical_game_id")
        if not isinstance(target_id, str) or target_id in identifiers:
            raise EvidenceIntegrityError("frozen target identity is invalid or duplicated")
        if item.get("requested_date") in requests:
            raise EvidenceIntegrityError("frozen request timestamp collision")
        identifiers.add(target_id)
        requests.add(item["requested_date"])
        targets.append(
            FrozenTarget(
                canonical_game_id=target_id,
                home_team=_required_text(item, "home_team"),
                away_team=_required_text(item, "away_team"),
                kickoff_utc=_required_text(item, "kickoff_utc"),
                requested_date=_required_text(item, "requested_date"),
                canonical_request=request_text,
                canonical_request_sha256=request_hash,
                authority_version_chain=tuple(item.get("authority_version_chain", ())),
            )
        )
    assertions = payload.get("assertions", {})
    if any(
        assertions.get(name) is not False
        for name in (
            "api_key_used", "market_data_queried", "provider_called",
            "scores_queried", "outcome_model_performance_data_used",
        )
    ):
        raise EvidenceIntegrityError("selection manifest outcome/provider assertions drifted")
    return FrozenSelection(tuple(targets), _digest(raw), POPULATION_SHA256)


def validate_runtime_config(config: PilotExecutionConfig, selection: FrozenSelection) -> None:
    if len(selection.targets) != 20 or len(set(selection.target_ids)) != 20:
        raise AuthorizationError("execution requires the exact 20-target selection")
    if config.target_ids != selection.target_ids:
        raise AuthorizationError("execution target identity mismatch")
    if (
        config.primary_ceiling != MAX_PRIMARY_CALLS
        or config.retry_ceiling != MAX_RETRY_CALLS
        or config.attempt_ceiling != MAX_ATTEMPTS
        or config.credit_ceiling != MAX_RESERVED_CREDITS
        or config.per_attempt_reservation != RESERVED_CREDITS_PER_ATTEMPT
    ):
        raise AuthorizationError("execution ceiling mismatch")
    if not config.repository_clean:
        raise AuthorizationError("execution repository must be clean")
    if config.repository_head != config.implementation_revision:
        raise AuthorizationError("repository and implementation revisions differ")
    if not _REVISION.fullmatch(config.repository_head):
        raise AuthorizationError("repository revision is invalid")
    if not _SHA256.fullmatch(config.implementation_sha256):
        raise AuthorizationError("implementation SHA-256 is invalid")
    if not _SHA256.fullmatch(config.credential_fingerprint):
        raise AuthorizationError("credential fingerprint is invalid")
    if not _SHA256.fullmatch(config.dependency_identity):
        raise AuthorizationError("dependency identity is invalid")
    if config.runtime_mode != RUNTIME_MODE:
        raise AuthorizationError("runtime mode must remain OFFLINE_ONLY")
    required_identities = (
        config.credential_identity,
        config.clock_identity,
        config.monotonic_timer_identity,
        config.transport_identity,
        config.runtime_identity,
        config.dependency_identity,
        config.timezone_identity,
        config.os_sync_source,
        config.os_sync_status,
        config.runtime_inspector_identity,
    )
    if not all(required_identities):
        raise AuthorizationError("credential or clock identity is missing")
    if config.runtime_inspector_identity != RUNTIME_INSPECTOR_ID:
        raise AuthorizationError("runtime provenance inspector identity mismatch")


def validate_measured_runtime(
    provenance: RuntimeProvenance,
    *,
    config: PilotExecutionConfig,
    repository_root: Path,
    transport: ProviderTransport,
    clock: PilotClock,
    credential: SecretCredential,
) -> None:
    if not isinstance(provenance, RuntimeProvenance):
        raise AuthorizationError("runtime provenance is missing or invalid")
    expected = {
        "repository_root": str(repository_root.resolve()),
        "git_head": config.repository_head,
        "git_clean": config.repository_clean,
        "implementation_source_sha256": config.implementation_sha256.upper(),
        "configuration_sha256": config.sha256,
        "runtime_identity": config.runtime_identity,
        "dependency_identity": config.dependency_identity,
        "timezone_identity": config.timezone_identity,
        "evidence_store_root": str(Path(config.evidence_store_root).resolve()),
        "os_sync_source": config.os_sync_source,
        "os_sync_status": config.os_sync_status,
        "monotonic_timer_identity": config.monotonic_timer_identity,
        "transport_identity": config.transport_identity,
        "clock_identity": config.clock_identity,
        "runtime_mode": RUNTIME_MODE,
        "runtime_inspector_identity": RUNTIME_INSPECTOR_ID,
    }
    actual = provenance.canonical_payload()
    phase_offset = actual.pop("phase_offset_evidence", None)
    last_sync = actual.pop("last_successful_sync_evidence", None)
    if actual != expected:
        raise AuthorizationError("measured runtime identity mismatch")
    _validate_dynamic_clock_evidence(phase_offset, last_sync)
    if provenance.os_sync_status != "SYNCHRONIZED":
        raise AuthorizationError("clock synchronization is not proven")
    if type(transport) is not DeterministicFakeTransport:
        raise AuthorizationError(
            "implementation 0.1.4 permits only the offline deterministic transport"
        )
    if component_runtime_identity(transport) != config.transport_identity:
        raise AuthorizationError("transport runtime identity mismatch")
    if component_runtime_identity(clock) != config.clock_identity:
        raise AuthorizationError("clock runtime identity mismatch")
    if clock.monotonic_identity != config.monotonic_timer_identity:
        raise AuthorizationError("monotonic timer identity mismatch")
    if credential.fingerprint != config.credential_fingerprint.upper():
        raise AuthorizationError("injected credential fingerprint mismatch")


def validate_recovery_runtime(
    provenance: RecoveryRuntimeProvenance,
    *,
    config: PilotExecutionConfig,
    repository_root: Path,
    clock: PilotClock,
) -> None:
    expected = {
        "repository_root": str(repository_root.resolve()),
        "git_head": config.repository_head,
        "git_clean": True,
        "implementation_source_sha256": config.implementation_sha256.upper(),
        "configuration_sha256": config.sha256,
        "runtime_identity": config.runtime_identity,
        "dependency_identity": config.dependency_identity,
        "timezone_identity": config.timezone_identity,
        "os_sync_source": config.os_sync_source,
        "os_sync_status": config.os_sync_status,
        "monotonic_timer_identity": config.monotonic_timer_identity,
        "clock_identity": config.clock_identity,
        "recovery_mode": "RECOVERY_ONLY",
        "runtime_inspector_identity": RUNTIME_INSPECTOR_ID,
    }
    actual = provenance.canonical_payload()
    phase_offset = actual.pop("phase_offset_evidence", None)
    last_sync = actual.pop("last_successful_sync_evidence", None)
    if actual != expected:
        raise AuthorizationError("measured recovery runtime identity mismatch")
    _validate_dynamic_clock_evidence(phase_offset, last_sync)
    if provenance.os_sync_status != "SYNCHRONIZED":
        raise AuthorizationError("recovery clock synchronization is not proven")
    if component_runtime_identity(clock) != config.clock_identity:
        raise AuthorizationError("recovery clock identity mismatch")
    if clock.monotonic_identity != config.monotonic_timer_identity:
        raise AuthorizationError("recovery monotonic timer identity mismatch")


def load_and_validate_authorization(
    path: Path,
    *,
    config: PilotExecutionConfig,
    selection: FrozenSelection,
    now: datetime,
    require_active_window: bool = True,
) -> ExecutionAuthorization:
    validate_runtime_config(config, selection)
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except FileNotFoundError as error:
        raise AuthorizationError("single-use authorization artifact is missing") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthorizationError("single-use authorization artifact is invalid") from error
    if not isinstance(payload, dict):
        raise AuthorizationError("single-use authorization must be a JSON object")
    expected = {
        "protocol": {"identity": PROTOCOL_ID, "sha256": PROTOCOL_SHA256},
        "pilot_spec": {"identity": PILOT_SPEC_ID, "sha256": PILOT_SPEC_SHA256},
        "selection_manifest": {"identity": SELECTION_ID, "sha256": SELECTION_SHA256},
        "kickoff_authority": {
            "package_zip_sha256": KICKOFF_PACKAGE_SHA256,
            "authority_ledger_sha256": KICKOFF_LEDGER_SHA256,
        },
    }
    for name, value in expected.items():
        if payload.get(name) != value:
            raise AuthorizationError(f"authorization {name} identity mismatch")
    if payload.get("configuration_sha256") != config.sha256:
        raise AuthorizationError("authorization configuration identity mismatch")
    if payload.get("implementation") != {
        "identity": IMPLEMENTATION_ID,
        "git_revision": config.implementation_revision,
        "sha256": config.implementation_sha256.upper(),
    }:
        raise AuthorizationError("authorization implementation identity mismatch")
    if payload.get("repository") != {
        "head": config.repository_head,
        "clean": True,
    }:
        raise AuthorizationError("authorization repository identity mismatch")
    if payload.get("credential") != {
        "identity": config.credential_identity,
        "fingerprint": config.credential_fingerprint.upper(),
        "quota_attribution_mode": config.quota_attribution_mode.value,
    }:
        raise AuthorizationError("authorization credential identity mismatch")
    if str(Path(payload.get("evidence_store_root", "")).resolve()) != str(
        Path(config.evidence_store_root).resolve()
    ):
        raise AuthorizationError("authorization evidence-store identity mismatch")
    if tuple(payload.get("target_ids", ())) != selection.target_ids:
        raise AuthorizationError("authorization target set mismatch")
    if payload.get("ceilings") != {
        "primary": MAX_PRIMARY_CALLS,
        "retries": MAX_RETRY_CALLS,
        "attempts": MAX_ATTEMPTS,
        "credits": MAX_RESERVED_CREDITS,
        "per_attempt_reservation": RESERVED_CREDITS_PER_ATTEMPT,
    }:
        raise AuthorizationError("authorization ceiling mismatch")
    if payload.get("clock_identity") != config.clock_identity:
        raise AuthorizationError("authorization clock identity mismatch")
    if payload.get("runtime_mode") != RUNTIME_MODE:
        raise AuthorizationError("authorization runtime mode mismatch")
    if payload.get("execution_policy") != {
        "mode": "INITIAL_ONLY_NO_CONTINUATION",
        "predecessor_evidence_manifest_sha256": None,
    }:
        raise AuthorizationError("continuation is unsupported by implementation 0.1.4")
    try:
        authorization_id = _required_text(payload, "authorization_id")
        authorizer = _required_text(payload, "authorizer_reference")
        authorized_at = _parse_timestamp(_required_text(payload, "authorized_at"))
        window_start = _parse_timestamp(_required_text(payload, "window_start"))
        window_end = _parse_timestamp(_required_text(payload, "window_end"))
    except ValueError as error:
        raise AuthorizationError("authorization metadata is invalid") from error
    _require_aware(now, "trusted current time")
    if not authorized_at <= window_start < window_end:
        raise AuthorizationError("authorization chronology is invalid")
    if require_active_window and not window_start <= now < window_end:
        raise AuthorizationError("authorization is outside its execution window")
    authorization = ExecutionAuthorization(
        source_path=path.resolve(),
        raw_bytes=raw,
        sha256=_digest(raw),
        authorization_id=authorization_id,
        authorizer_reference=authorizer,
        authorized_at=authorized_at,
        window_start=window_start,
        window_end=window_end,
        configuration_sha256=config.sha256,
    )
    authorization.validate_unchanged()
    return authorization


class PilotLease:
    def __init__(self, path: Path, descriptor: int):
        self.path = path
        self.descriptor = descriptor

    def close(self) -> None:
        if self.descriptor < 0:
            return
        _unlock_file_descriptor(self.descriptor)
        os.close(self.descriptor)
        self.descriptor = -1

    def __enter__(self) -> PilotLease:
        return self

    def __exit__(self, *_unused: object) -> None:
        self.close()


class EvidenceStore:
    def __init__(self, root: Path, *, repository_root: Path):
        self.root = root.resolve()
        repository = repository_root.resolve()
        if self.root == repository or repository in self.root.parents:
            raise ValueError("pilot evidence store must be outside the repository")

    def initialize_new(self) -> None:
        if self.root.exists():
            if not self.root.is_dir():
                raise EvidenceIntegrityError("evidence-store root is not a directory")
            try:
                if any(self.root.iterdir()):
                    raise EvidenceIntegrityError(
                        "initial evidence-store root is not dedicated and empty"
                    )
            except OSError as error:
                raise EvidenceIOError("evidence-store root inspection failed") from error
        else:
            try:
                self.root.mkdir(parents=True, exist_ok=False)
            except OSError as error:
                raise EvidenceIOError("evidence-store initialization failed") from error
            _fsync_directory(self.root.parent)

    def validate_recovery_root(self) -> None:
        if not self.root.is_dir():
            raise EvidenceIntegrityError("governed recovery store is missing")
        required = {
            "authorization.json",
            "authorization_claim.json",
            "run_identity.json",
            "runtime_provenance.json",
            "ledger",
        }
        names = {path.name for path in self.root.iterdir()}
        if not required.issubset(names):
            raise EvidenceIntegrityError("governed recovery store is incomplete")
        allowed = required | {
            ".pilot.lock",
            "attempts",
            "recovery",
            "reports",
            "evidence_manifest.json",
        }
        if names - allowed:
            raise EvidenceIntegrityError("recovery store contains unexpected artifacts")
        if (self.root / "evidence_manifest.json").exists():
            verify_evidence_manifest(self, self.root / "evidence_manifest.json")
            raise EvidenceIntegrityError(
                "completed or terminal manifested run cannot enter recovery"
            )
        reports = self.root / "reports"
        if reports.exists():
            report_names = {path.name for path in reports.iterdir() if path.is_file()}
            if report_names - {"pilot_report.json"}:
                raise EvidenceIntegrityError("recovery reports directory is not governed")

    def claim_authorization(self, authorization: ExecutionAuthorization) -> None:
        claim = {
            "authorization_id": authorization.authorization_id,
            "authorization_sha256": authorization.sha256,
        }
        _exclusive_write(
            self.root / "authorization_claim.json",
            _canonical_json_bytes(claim),
        )
        _exclusive_write(self.root / "authorization.json", authorization.raw_bytes)

    def write_runtime_provenance(self, provenance: RuntimeProvenance) -> None:
        _exclusive_write(
            self.root / "runtime_provenance.json",
            _canonical_json_bytes(provenance.canonical_payload()),
        )

    def write_recovery_runtime_provenance(
        self, provenance: RecoveryRuntimeProvenance
    ) -> Path:
        path = self.root / "recovery" / "runtime_provenance.json"
        _exclusive_write(path, _canonical_json_bytes(provenance.canonical_payload()))
        return path

    def write_run_identity(
        self, config: PilotExecutionConfig, provenance: RuntimeProvenance
    ) -> None:
        payload = {
            "configuration": config.canonical_payload(),
            "configuration_sha256": config.sha256,
            "implementation": {
                "identity": IMPLEMENTATION_ID,
                "revision": config.implementation_revision,
                "sha256": config.implementation_sha256.upper(),
            },
            "repository": {
                "clean": config.repository_clean,
                "head": config.repository_head,
            },
            "runtime_provenance_sha256": provenance.sha256,
            "runtime_provenance_artifact_sha256": provenance.artifact_sha256,
        }
        _exclusive_write(
            self.root / "run_identity.json", _canonical_json_bytes(payload)
        )

    def acquire_lease(self, authorization_id: str) -> PilotLease:
        path = self.root / ".pilot.lock"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            _lock_file_descriptor(descriptor)
            os.ftruncate(descriptor, 0)
            os.write(descriptor, authorization_id.encode("utf-8"))
            os.fsync(descriptor)
        except (OSError, BlockingIOError) as error:
            if "descriptor" in locals():
                os.close(descriptor)
            raise AuthorizationError("pilot single-flight lease is already held") from error
        _fsync_directory(path.parent)
        return PilotLease(path, descriptor)

    def write_attempt_request(
        self,
        attempt_id: str,
        *,
        authorization: ExecutionAuthorization,
        request: ProviderRequest,
        request_started_at: datetime,
        predecessor_attempt_id: str | None,
    ) -> None:
        value = {
            "attempt_id": attempt_id,
            "authorization_id": authorization.authorization_id,
            "authorization_sha256": authorization.sha256,
            "canonical_request": request.canonical_bytes.decode("utf-8"),
            "canonical_request_sha256": request.canonical_sha256,
            "predecessor_attempt_id": predecessor_attempt_id,
            "redacted_as_sent_url": request.redacted_as_sent_url,
            "request_started_at": _utc_text(request_started_at),
            "target_id": request.target_id,
        }
        _exclusive_write(
            self.root / "attempts" / attempt_id / "request.json",
            _canonical_json_bytes(value),
        )

    def write_response(
        self,
        attempt_id: str,
        *,
        response: ProviderResponse,
        decoded_body: bytes,
        received_at: datetime,
        secret_values: Sequence[str] = (),
    ) -> dict[str, Any]:
        directory = self.root / "attempts" / attempt_id
        _exclusive_write(directory / "raw_body.bin", decoded_body)
        headers = redact_headers(response.headers, secret_values=secret_values)
        metadata = {
            "body_bytes": len(decoded_body),
            "body_sha256": _digest(decoded_body),
            "content_encoding": _header(response.headers, "content-encoding"),
            "content_type": _header(response.headers, "content-type"),
            "headers": headers,
            "quota": {
                name: _header(response.headers, name)
                for name in (
                    "x-requests-used", "x-requests-remaining", "x-requests-last"
                )
            },
            "response_received_at": _utc_text(received_at),
            "server_date": _header(response.headers, "date"),
            "status_code": response.status_code,
        }
        _exclusive_write(directory / "response.json", _canonical_json_bytes(metadata))
        return metadata

    def write_secret_exposure_metadata(
        self,
        attempt_id: str,
        *,
        response: ProviderResponse,
        received_at: datetime,
    ) -> None:
        metadata = {
            "response_received_at": _utc_text(received_at),
            "status_code": response.status_code,
            "warning": "SECRET_EXPOSURE_RESPONSE_NOT_RETAINED",
        }
        _exclusive_write(
            self.root / "attempts" / attempt_id / "secret_exposure.json",
            _canonical_json_bytes(metadata),
        )

    def write_undecodable_response(
        self,
        attempt_id: str,
        *,
        response: ProviderResponse,
        received_at: datetime,
        secret_values: Sequence[str] = (),
    ) -> None:
        directory = self.root / "attempts" / attempt_id
        _exclusive_write(directory / "transport_body.bin", response.body)
        metadata = {
            "content_encoding": _header(response.headers, "content-encoding"),
            "headers": redact_headers(response.headers, secret_values=secret_values),
            "response_received_at": _utc_text(received_at),
            "status_code": response.status_code,
            "transport_body_bytes": len(response.body),
            "transport_body_sha256": _digest(response.body),
            "warning": "APPLICATION_VISIBLE_BODY_UNDECODABLE",
        }
        _exclusive_write(
            directory / "undecodable_response.json",
            _canonical_json_bytes(metadata),
        )

    def write_analysis(self, attempt_id: str, value: Mapping[str, Any]) -> None:
        _exclusive_write(
            self.root / "attempts" / attempt_id / "analysis.json",
            _canonical_json_bytes(value),
        )

    def write_integrity_failure(self, reason: str, observed_at: datetime) -> Path:
        path = self.root / "recovery" / "integrity_failure.json"
        _exclusive_write(
            path,
            _canonical_json_bytes(
                {
                    "continuation_supported": False,
                    "observed_at": _utc_text(observed_at),
                    "reason": reason,
                    "terminal": True,
                }
            ),
        )
        return path

    def write_recovery_record(
        self,
        *,
        recovered_attempt_ids: Sequence[str],
        counters: AttemptCounters,
        observed_at: datetime,
        original_runtime_provenance_sha256: str,
        recovery_runtime_provenance_sha256: str,
    ) -> Path:
        path = self.root / "recovery" / "recovery_record.json"
        _exclusive_write(
            path,
            _canonical_json_bytes(
                {
                    "continuation_supported": False,
                    "counters": {
                        "attempts": counters.attempts,
                        "primary": counters.primary,
                        "reserved_credits": counters.reserved_credits,
                        "retries": counters.retries,
                    },
                    "observed_at": _utc_text(observed_at),
                    "original_runtime_provenance_sha256": (
                        original_runtime_provenance_sha256
                    ),
                    "recovered_attempt_ids": list(recovered_attempt_ids),
                    "recovery_mode": "RECOVERY_ONLY",
                    "recovery_runtime_provenance_sha256": (
                        recovery_runtime_provenance_sha256
                    ),
                    "terminal_reason": "crash_recovery_no_continuation_supported",
                }
            ),
        )
        return path

    def write_report(
        self, report: PilotReport, *, filename: str = "pilot_report.json"
    ) -> Path:
        if filename not in {"pilot_report.json", "recovery_terminal_report.json"}:
            raise ValueError("unsupported pilot report filename")
        path = self.root / "reports" / filename
        payload = {
            "disposition": report.disposition.value,
            "terminal_reason": report.terminal_reason,
            "targets": [
                {
                    "failure_reason": item.failure_reason,
                    "retry_count": item.retry_count,
                    "target_id": item.target_id,
                    "terminal": item.terminal,
                }
                for item in report.target_results
            ],
        }
        _exclusive_write(path, _canonical_json_bytes(payload))
        return path


class AttemptLedger:
    _TRANSITIONS = {
        AttemptState.RESERVED: {
            AttemptState.PROVABLE_PRE_SEND_FAILURE,
            AttemptState.SENT,
            AttemptState.SENT_UNKNOWN,
            AttemptState.TERMINAL_STOP,
        },
        AttemptState.SENT: {
            AttemptState.RESPONSE_CAPTURED,
            AttemptState.SENT_UNKNOWN,
            AttemptState.TERMINAL_STOP,
        },
        AttemptState.RESPONSE_CAPTURED: {AttemptState.TERMINAL_STOP},
        AttemptState.PROVABLE_PRE_SEND_FAILURE: {AttemptState.TERMINAL_STOP},
    }

    def __init__(self, store: EvidenceStore):
        self.path = store.root / "ledger" / "attempts.jsonl"

    def entries(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        entries: list[dict[str, Any]] = []
        previous = "0" * 64
        try:
            lines = self.path.read_bytes().splitlines()
            for index, line in enumerate(lines, start=1):
                if not line:
                    raise EvidenceIntegrityError("attempt ledger contains an empty line")
                entry = json.loads(line)
                digest = entry.pop("entry_sha256", None)
                if entry.get("sequence") != index or entry.get("previous_entry_sha256") != previous:
                    raise EvidenceIntegrityError("attempt ledger sequence/hash chain mismatch")
                calculated = _digest(_canonical_json_bytes(entry, terminal_lf=False))
                if digest != calculated:
                    raise EvidenceIntegrityError("attempt ledger entry SHA-256 mismatch")
                entry["entry_sha256"] = digest
                entries.append(entry)
                previous = digest
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EvidenceIntegrityError("attempt ledger is undecodable") from error
        self._validate_transitions(entries)
        return tuple(entries)

    def counters(self) -> AttemptCounters:
        reservations = [
            entry for entry in self.entries()
            if entry["state"] == AttemptState.RESERVED.value
        ]
        primary = sum(entry["attempt_kind"] == AttemptKind.PRIMARY.value for entry in reservations)
        retries = sum(entry["attempt_kind"] == AttemptKind.RETRY.value for entry in reservations)
        return AttemptCounters(primary, retries, len(reservations), len(reservations) * 10)

    def current_states(self) -> dict[str, AttemptState]:
        states: dict[str, AttemptState] = {}
        for entry in self.entries():
            states[entry["attempt_id"]] = AttemptState(entry["state"])
        return states

    def reserve(
        self,
        *,
        attempt_id: str,
        target_id: str,
        kind: AttemptKind,
        request_sha256: str,
        observed_at: datetime,
        predecessor_attempt_id: str | None = None,
    ) -> None:
        entries = self.entries()
        counters = self.counters()
        if any(entry["attempt_id"] == attempt_id for entry in entries):
            raise EvidenceCollisionError("attempt ID already exists")
        if (
            counters.attempts >= MAX_ATTEMPTS
            or counters.reserved_credits + 10 > MAX_RESERVED_CREDITS
        ):
            raise TerminalPilotError("attempt or credit ceiling would be exceeded")
        if kind is AttemptKind.PRIMARY and counters.primary >= MAX_PRIMARY_CALLS:
            raise TerminalPilotError("primary-call ceiling would be exceeded")
        if kind is AttemptKind.RETRY and counters.retries >= MAX_RETRY_CALLS:
            raise TerminalPilotError("retry ceiling would be exceeded")
        same_target = [
            entry
            for entry in entries
            if entry["target_id"] == target_id and entry["state"] == "RESERVED"
        ]
        if kind is AttemptKind.PRIMARY and same_target:
            raise TerminalPilotError("target already has a primary attempt")
        if kind is AttemptKind.RETRY:
            retries = [e for e in same_target if e["attempt_kind"] == "RETRY"]
            if retries:
                raise TerminalPilotError("second retry is prohibited")
            if predecessor_attempt_id is None:
                raise TerminalPilotError("retry predecessor is required")
            predecessor_entries = [
                entry
                for entry in entries
                if entry["attempt_id"] == predecessor_attempt_id
            ]
            if not predecessor_entries:
                raise TerminalPilotError("retry predecessor does not exist")
            predecessor = predecessor_entries[-1]
            if (
                predecessor["target_id"] != target_id
                or predecessor["request_sha256"] != request_sha256
                or predecessor["state"]
                not in {
                    AttemptState.PROVABLE_PRE_SEND_FAILURE.value,
                    AttemptState.RESPONSE_CAPTURED.value,
                }
                or predecessor["details"].get("retry_permitted") is not True
            ):
                raise TerminalPilotError("retry predecessor is not eligible")
        self.append(
            attempt_id=attempt_id,
            target_id=target_id,
            state=AttemptState.RESERVED,
            observed_at=observed_at,
            attempt_kind=kind,
            request_sha256=request_sha256,
            predecessor_attempt_id=predecessor_attempt_id,
            details={"reserved_credits": RESERVED_CREDITS_PER_ATTEMPT},
        )

    def append(
        self,
        *,
        attempt_id: str,
        target_id: str,
        state: AttemptState,
        observed_at: datetime,
        attempt_kind: AttemptKind,
        request_sha256: str,
        predecessor_attempt_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        entries = self.entries()
        sequence = len(entries) + 1
        previous = entries[-1]["entry_sha256"] if entries else "0" * 64
        body = {
            "attempt_id": attempt_id,
            "attempt_kind": attempt_kind.value,
            "details": _safe_details(details or {}),
            "observed_at": _utc_text(observed_at),
            "predecessor_attempt_id": predecessor_attempt_id,
            "previous_entry_sha256": previous,
            "request_sha256": request_sha256,
            "sequence": sequence,
            "state": state.value,
            "target_id": target_id,
        }
        body["entry_sha256"] = _digest(_canonical_json_bytes(body, terminal_lf=False))
        line = _canonical_json_bytes(body)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise EvidenceIOError("attempt ledger durable append failed") from error
        _fsync_directory(self.path.parent)
        self.entries()

    def recover_incomplete(self, *, now: datetime) -> tuple[str, ...]:
        entries = self.entries()
        latest: dict[str, dict[str, Any]] = {}
        for entry in entries:
            latest[entry["attempt_id"]] = entry
        recovered = []
        for attempt_id, entry in latest.items():
            if entry["state"] in {AttemptState.RESERVED.value, AttemptState.SENT.value}:
                self.append(
                    attempt_id=attempt_id,
                    target_id=entry["target_id"],
                    state=AttemptState.SENT_UNKNOWN,
                    observed_at=now,
                    attempt_kind=AttemptKind(entry["attempt_kind"]),
                    request_sha256=entry["request_sha256"],
                    predecessor_attempt_id=entry["predecessor_attempt_id"],
                    details={"reason": "restart_cannot_prove_no_send"},
                )
                recovered.append(attempt_id)
        return tuple(sorted(recovered))

    def _validate_transitions(self, entries: Sequence[Mapping[str, Any]]) -> None:
        states: dict[str, AttemptState] = {}
        for entry in entries:
            attempt_id = entry.get("attempt_id")
            try:
                state = AttemptState(entry.get("state"))
                kind = AttemptKind(entry.get("attempt_kind"))
            except ValueError as error:
                raise EvidenceIntegrityError("attempt ledger state/kind is invalid") from error
            if not isinstance(attempt_id, str) or not attempt_id:
                raise EvidenceIntegrityError("attempt ledger attempt ID is invalid")
            prior = states.get(attempt_id)
            if prior is None:
                if state is not AttemptState.RESERVED:
                    raise EvidenceIntegrityError("attempt ledger must begin with RESERVED")
            elif state not in self._TRANSITIONS.get(prior, set()):
                raise EvidenceIntegrityError("attempt ledger contains an invalid transition")
            if kind is AttemptKind.RETRY and entry.get("predecessor_attempt_id") is None:
                raise EvidenceIntegrityError("retry ledger entry lacks predecessor")
            states[attempt_id] = state


class PilotRecovery:
    """Recovery-only closure for an interrupted governed evidence store.

    This lifecycle has no transport or credential and cannot resume execution.
    """

    def __init__(
        self,
        *,
        selection: FrozenSelection,
        config: PilotExecutionConfig,
        repository_root: Path,
        clock: PilotClock,
    ):
        self.selection = selection
        self.config = config
        self.repository_root = repository_root
        self.clock = clock

    def recover(self) -> PilotReport:
        validate_runtime_config(self.config, self.selection)
        recovery_provenance = LocalRuntimeProvenanceInspector(
            self.repository_root
        ).inspect_recovery(config=self.config, clock=self.clock)
        validate_recovery_runtime(
            recovery_provenance,
            config=self.config,
            repository_root=self.repository_root,
            clock=self.clock,
        )
        store = EvidenceStore(
            Path(self.config.evidence_store_root),
            repository_root=self.repository_root,
        )
        authorization, _ = self._validate_recoverable_store(store)
        with store.acquire_lease(authorization.authorization_id):
            authorization, ledger = self._validate_recoverable_store(store)
            original_provenance_sha256 = _digest(
                (store.root / "runtime_provenance.json").read_bytes()
            )
            recovery_provenance_path = store.write_recovery_runtime_provenance(
                recovery_provenance
            )
            recovery_provenance_sha256 = _digest(
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
                TargetExecutionResult(
                    target_id,
                    True,
                    0,
                    None,
                    "crash_recovery_no_continuation_supported",
                )
                for target_id in recovered
            )
            report = PilotReport(
                PilotDisposition.FAILED,
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
            verify_evidence_manifest(store, manifest_path)
        return report

    def _validate_recoverable_store(
        self, store: EvidenceStore
    ) -> tuple[ExecutionAuthorization, AttemptLedger]:
        store.validate_recovery_root()
        authorization = load_and_validate_authorization(
            store.root / "authorization.json",
            config=self.config,
            selection=self.selection,
            now=self.clock.now_utc(),
            require_active_window=False,
        )
        self._validate_governed_identities(store, authorization)
        ledger = AttemptLedger(store)
        ledger.entries()
        return authorization, ledger

    def _validate_governed_identities(
        self, store: EvidenceStore, authorization: ExecutionAuthorization
    ) -> None:
        claim = _read_json_object(store.root / "authorization_claim.json")
        if claim != {
            "authorization_id": authorization.authorization_id,
            "authorization_sha256": authorization.sha256,
        }:
            raise EvidenceIntegrityError("authorization claim identity mismatch")
        provenance_payload = _read_json_object(store.root / "runtime_provenance.json")
        try:
            provenance = RuntimeProvenance(**provenance_payload)
        except TypeError as error:
            raise EvidenceIntegrityError("runtime provenance schema mismatch") from error
        run_identity = _read_json_object(store.root / "run_identity.json")
        if (
            run_identity.get("configuration_sha256") != self.config.sha256
            or run_identity.get("runtime_provenance_sha256") != provenance.sha256
            or run_identity.get("runtime_provenance_artifact_sha256")
            != provenance.artifact_sha256
            or provenance.configuration_sha256 != self.config.sha256
            or provenance.evidence_store_root != str(store.root)
        ):
            raise EvidenceIntegrityError("governed run identity mismatch")
        if run_identity.get("implementation") != {
            "identity": IMPLEMENTATION_ID,
            "revision": self.config.implementation_revision,
            "sha256": self.config.implementation_sha256.upper(),
        }:
            raise EvidenceIntegrityError("governed implementation identity mismatch")


class PilotExecutor:
    """Gated sequential executor with an injected transport and trusted clock.

    The class has no concrete network transport and no ambient credential lookup.
    Calling ``run`` with the deterministic fake transport is therefore offline.
    """

    def __init__(
        self,
        *,
        selection: FrozenSelection,
        config: PilotExecutionConfig,
        authorization_path: Path,
        transport: ProviderTransport,
        credential: SecretCredential,
        repository_root: Path,
        clock: PilotClock,
    ):
        self.selection = selection
        self.config = config
        self.authorization_path = authorization_path
        self.transport = transport
        self.credential = credential
        self.repository_root = repository_root
        self.clock = clock

    def run(self) -> PilotReport:
        provenance = LocalRuntimeProvenanceInspector(self.repository_root).inspect(
            config=self.config,
            transport=self.transport,
            clock=self.clock,
        )
        validate_runtime_config(self.config, self.selection)
        validate_measured_runtime(
            provenance,
            config=self.config,
            repository_root=self.repository_root,
            transport=self.transport,
            clock=self.clock,
            credential=self.credential,
        )
        now = self.clock.now_utc()
        authorization = load_and_validate_authorization(
            self.authorization_path,
            config=self.config,
            selection=self.selection,
            now=now,
        )
        store = EvidenceStore(
            Path(self.config.evidence_store_root),
            repository_root=self.repository_root,
        )
        store.initialize_new()
        store.claim_authorization(authorization)
        store.write_runtime_provenance(provenance)
        store.write_run_identity(self.config, provenance)
        ledger = AttemptLedger(store)
        results: list[TargetExecutionResult] = []
        quota: QuotaSnapshot | None = None
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
                except PilotError as error:
                    result = TargetExecutionResult(
                        target.canonical_game_id,
                        True,
                        0,
                        None,
                        _pilot_error_reason(error),
                    )
                results.append(result)
                if result.terminal:
                    break
            try:
                authorization.validate_unchanged()
            except AuthorizationError:
                results.append(
                    TargetExecutionResult(
                        self.selection.targets[-1].canonical_game_id,
                        True,
                        0,
                        None,
                        "authorization_failure_before_report",
                    )
                )
            report = build_report(results)
            report_path = store.write_report(report)
            try:
                authorization.validate_unchanged()
            except AuthorizationError:
                store.write_integrity_failure(
                    "authorization_failure_before_manifest",
                    self.clock.now_utc(),
                )
                return PilotReport(
                    PilotDisposition.FAILED,
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
                verify_evidence_manifest(store, manifest_path)
                authorization.validate_unchanged()
            except (AuthorizationError, EvidenceIntegrityError):
                store.write_integrity_failure(
                    "authorization_or_manifest_failure_before_acceptance",
                    self.clock.now_utc(),
                )
                return PilotReport(
                    PilotDisposition.FAILED,
                    report.target_results,
                    "authorization_or_manifest_failure_before_acceptance",
                )
        return report

    def _execute_target(
        self,
        *,
        target: FrozenTarget,
        authorization: ExecutionAuthorization,
        store: EvidenceStore,
        ledger: AttemptLedger,
        previous_quota: QuotaSnapshot | None,
    ) -> tuple[TargetExecutionResult, QuotaSnapshot | None]:
        request = provider_request(target)
        predecessor: str | None = None
        for attempt_number in (1, 2):
            kind = AttemptKind.PRIMARY if attempt_number == 1 else AttemptKind.RETRY
            attempt_id = f"{target.canonical_game_id}.{kind.value.lower()}"
            now = self._validate_live_gate(authorization)
            ledger.reserve(
                attempt_id=attempt_id,
                target_id=target.canonical_game_id,
                kind=kind,
                request_sha256=request.canonical_sha256,
                observed_at=now,
                predecessor_attempt_id=predecessor,
            )
            try:
                store.write_attempt_request(
                    attempt_id,
                    authorization=authorization,
                    request=request,
                    request_started_at=now,
                    predecessor_attempt_id=predecessor,
                )
            except PilotError:
                self._terminal(
                    ledger, attempt_id, target, kind, request,
                    predecessor, "request_evidence_failure",
                )
                return (
                    self._failure(target, attempt_number, "request_evidence_failure"),
                    previous_quota,
                )

            try:
                self._validate_live_gate(authorization)
            except AuthorizationError:
                self._terminal(
                    ledger, attempt_id, target, kind, request,
                    predecessor, "authorization_failure_before_provider_boundary",
                )
                return self._failure(
                    target,
                    attempt_number,
                    "authorization_failure_before_provider_boundary",
                ), previous_quota

            try:
                exchange = self.transport.begin(request, self.credential)
            except ProvablePreSendFailure as error:
                try:
                    authorization.validate_unchanged()
                except AuthorizationError:
                    ledger.append(
                        attempt_id=attempt_id,
                        target_id=target.canonical_game_id,
                        state=AttemptState.SENT_UNKNOWN,
                        observed_at=self.clock.now_utc(),
                        attempt_kind=kind,
                        request_sha256=request.canonical_sha256,
                        predecessor_attempt_id=predecessor,
                        details={"reason": "authorization_changed_at_boundary"},
                    )
                    return self._failure(
                        target, attempt_number, "authorization_changed_at_boundary"
                    ), previous_quota
                retry_permitted = attempt_number == 1 and self._inside_window(authorization)
                ledger.append(
                    attempt_id=attempt_id,
                    target_id=target.canonical_game_id,
                    state=AttemptState.PROVABLE_PRE_SEND_FAILURE,
                    observed_at=self.clock.now_utc(),
                    attempt_kind=kind,
                    request_sha256=request.canonical_sha256,
                    predecessor_attempt_id=predecessor,
                    details={
                        "reason": error.kind.value,
                        "retry_permitted": retry_permitted,
                    },
                )
                if retry_permitted:
                    predecessor = attempt_id
                    continue
                self._terminal(
                    ledger, attempt_id, target, kind, request,
                    predecessor, "pre_send_failure_retry_unavailable",
                )
                return self._failure(
                    target, attempt_number, "pre_send_failure_retry_unavailable"
                ), previous_quota
            except PossibleSendFailure as error:
                try:
                    authorization.validate_unchanged()
                except AuthorizationError:
                    error = PossibleSendFailure(ReceiveFailureKind.POSSIBLE_SEND)
                ledger.append(
                    attempt_id=attempt_id,
                    target_id=target.canonical_game_id,
                    state=AttemptState.SENT_UNKNOWN,
                    observed_at=self.clock.now_utc(),
                    attempt_kind=kind,
                    request_sha256=request.canonical_sha256,
                    predecessor_attempt_id=predecessor,
                    details={"reason": error.kind.value},
                )
                return self._failure(target, attempt_number, error.kind.value), previous_quota
            except Exception:
                ledger.append(
                    attempt_id=attempt_id,
                    target_id=target.canonical_game_id,
                    state=AttemptState.SENT_UNKNOWN,
                    observed_at=self.clock.now_utc(),
                    attempt_kind=kind,
                    request_sha256=request.canonical_sha256,
                    predecessor_attempt_id=predecessor,
                    details={"reason": "unclassified_transport_boundary_failure"},
                )
                return self._failure(
                    target, attempt_number, "unclassified_transport_boundary_failure"
                ), previous_quota

            ledger.append(
                attempt_id=attempt_id,
                target_id=target.canonical_game_id,
                state=AttemptState.SENT,
                observed_at=self.clock.now_utc(),
                attempt_kind=kind,
                request_sha256=request.canonical_sha256,
                predecessor_attempt_id=predecessor,
            )
            try:
                authorization.validate_unchanged()
            except AuthorizationError:
                ledger.append(
                    attempt_id=attempt_id,
                    target_id=target.canonical_game_id,
                    state=AttemptState.SENT_UNKNOWN,
                    observed_at=self.clock.now_utc(),
                    attempt_kind=kind,
                    request_sha256=request.canonical_sha256,
                    predecessor_attempt_id=predecessor,
                    details={"reason": "authorization_changed_after_send_boundary"},
                )
                return self._failure(
                    target, attempt_number, "authorization_changed_after_send_boundary"
                ), previous_quota
            try:
                response = exchange.receive()
            except PossibleSendFailure as error:
                ledger.append(
                    attempt_id=attempt_id,
                    target_id=target.canonical_game_id,
                    state=AttemptState.SENT_UNKNOWN,
                    observed_at=self.clock.now_utc(),
                    attempt_kind=kind,
                    request_sha256=request.canonical_sha256,
                    predecessor_attempt_id=predecessor,
                    details={"reason": error.kind.value},
                )
                return self._failure(target, attempt_number, error.kind.value), previous_quota
            except Exception:
                ledger.append(
                    attempt_id=attempt_id,
                    target_id=target.canonical_game_id,
                    state=AttemptState.SENT_UNKNOWN,
                    observed_at=self.clock.now_utc(),
                    attempt_kind=kind,
                    request_sha256=request.canonical_sha256,
                    predecessor_attempt_id=predecessor,
                    details={"reason": "unclassified_receive_failure"},
                )
                return self._failure(
                    target, attempt_number, "unclassified_receive_failure"
                ), previous_quota

            try:
                authorization.validate_unchanged()
            except AuthorizationError:
                ledger.append(
                    attempt_id=attempt_id,
                    target_id=target.canonical_game_id,
                    state=AttemptState.SENT_UNKNOWN,
                    observed_at=self.clock.now_utc(),
                    attempt_kind=kind,
                    request_sha256=request.canonical_sha256,
                    predecessor_attempt_id=predecessor,
                    details={"reason": "authorization_changed_after_provider_boundary"},
                )
                return self._failure(
                    target,
                    attempt_number,
                    "authorization_changed_after_provider_boundary",
                ), previous_quota

            received_at = self.clock.now_utc()
            if 100 <= response.status_code < 200:
                try:
                    decoded = decode_application_body(response)
                    if _response_contains_secret(response, decoded, self.credential):
                        store.write_secret_exposure_metadata(
                            attempt_id, response=response, received_at=received_at
                        )
                    else:
                        store.write_response(
                            attempt_id,
                            response=response,
                            decoded_body=decoded,
                            received_at=received_at,
                            secret_values=(self.credential.value,),
                        )
                except PilotError:
                    if _response_contains_secret(
                        response, response.body, self.credential
                    ):
                        store.write_secret_exposure_metadata(
                            attempt_id, response=response, received_at=received_at
                        )
                    else:
                        store.write_undecodable_response(
                            attempt_id,
                            response=response,
                            received_at=received_at,
                            secret_values=(self.credential.value,),
                        )
                ledger.append(
                    attempt_id=attempt_id,
                    target_id=target.canonical_game_id,
                    state=AttemptState.SENT_UNKNOWN,
                    observed_at=received_at,
                    attempt_kind=kind,
                    request_sha256=request.canonical_sha256,
                    predecessor_attempt_id=predecessor,
                    details={"reason": "incomplete_1xx_response"},
                )
                return self._failure(
                    target, attempt_number, "incomplete_1xx_response"
                ), previous_quota

            try:
                decoded = decode_application_body(response)
            except TerminalPilotError:
                if _response_contains_secret(response, response.body, self.credential):
                    store.write_secret_exposure_metadata(
                        attempt_id, response=response, received_at=received_at
                    )
                else:
                    store.write_undecodable_response(
                        attempt_id,
                        response=response,
                        received_at=received_at,
                        secret_values=(self.credential.value,),
                    )
                self._terminal(
                    ledger, attempt_id, target, kind, request,
                    predecessor, "undecodable_content_encoding",
                )
                return self._failure(
                    target, attempt_number, "undecodable_content_encoding"
                ), previous_quota

            if _response_contains_secret(response, decoded, self.credential):
                store.write_secret_exposure_metadata(
                    attempt_id, response=response, received_at=received_at
                )
                self._terminal(
                    ledger, attempt_id, target, kind, request,
                    predecessor, "secret_exposure",
                )
                return self._failure(
                    target, attempt_number, "secret_exposure"
                ), previous_quota

            try:
                metadata = store.write_response(
                    attempt_id,
                    response=response,
                    decoded_body=decoded,
                    received_at=received_at,
                    secret_values=(self.credential.value,),
                )
            except (EvidenceIOError, EvidenceCollisionError):
                ledger.append(
                    attempt_id=attempt_id,
                    target_id=target.canonical_game_id,
                    state=AttemptState.SENT_UNKNOWN,
                    observed_at=self.clock.now_utc(),
                    attempt_kind=kind,
                    request_sha256=request.canonical_sha256,
                    predecessor_attempt_id=predecessor,
                    details={"reason": "response_evidence_io_failure"},
                )
                return self._failure(
                    target, attempt_number, "response_evidence_io_failure"
                ), previous_quota
            analysis: ResponseAnalysis | None = None
            try:
                if response.status_code == 200:
                    analysis = parse_success_response(decoded, target=target)
                    store.write_analysis(attempt_id, analysis_payload(analysis))
                snapshot = reconcile_quota(
                    response.headers,
                    previous=previous_quota,
                    empty_data=analysis.empty_data if analysis is not None else False,
                )
                action, delay, reason = classify_complete_response(
                    response.status_code, response.headers
                )
            except PilotError as error:
                ledger.append(
                    attempt_id=attempt_id,
                    target_id=target.canonical_game_id,
                    state=AttemptState.RESPONSE_CAPTURED,
                    observed_at=received_at,
                    attempt_kind=kind,
                    request_sha256=request.canonical_sha256,
                    predecessor_attempt_id=predecessor,
                    details={
                        "body_bytes": metadata["body_bytes"],
                        "body_sha256": metadata["body_sha256"],
                        "retry_permitted": False,
                        "status_code": response.status_code,
                    },
                )
                safe_reason = _pilot_error_reason(error)
                self._terminal(
                    ledger, attempt_id, target, kind, request,
                    predecessor, safe_reason,
                )
                return self._failure(target, attempt_number, safe_reason), previous_quota

            retry_permitted = (
                action is CompleteResponseAction.RETRY
                and attempt_number == 1
                and self._retry_fits_window(authorization, delay)
            )
            ledger.append(
                attempt_id=attempt_id,
                target_id=target.canonical_game_id,
                state=AttemptState.RESPONSE_CAPTURED,
                observed_at=received_at,
                attempt_kind=kind,
                request_sha256=request.canonical_sha256,
                predecessor_attempt_id=predecessor,
                details={
                    "body_bytes": metadata["body_bytes"],
                    "body_sha256": metadata["body_sha256"],
                    "retry_after_seconds": delay,
                    "retry_permitted": retry_permitted,
                    "status_code": response.status_code,
                },
            )
            previous_quota = snapshot
            if action is CompleteResponseAction.CONTINUE:
                return (
                    TargetExecutionResult(
                        target.canonical_game_id,
                        False,
                        attempt_number - 1,
                        analysis,
                        None,
                    ),
                    previous_quota,
                )
            if retry_permitted:
                self.clock.sleep(delay)
                try:
                    self._validate_live_gate(authorization)
                except AuthorizationError:
                    self._terminal(
                        ledger, attempt_id, target, kind, request,
                        predecessor, "retry_window_expired",
                    )
                    return self._failure(
                        target, attempt_number, "retry_window_expired"
                    ), previous_quota
                predecessor = attempt_id
                continue
            terminal_reason = (
                "retry_window_or_count_exhausted"
                if action is CompleteResponseAction.RETRY
                else reason
            )
            self._terminal(
                ledger, attempt_id, target, kind, request,
                predecessor, terminal_reason,
            )
            return self._failure(
                target, attempt_number, terminal_reason
            ), previous_quota
        raise AssertionError("attempt loop exhausted without a result")

    def _validate_live_gate(
        self, authorization: ExecutionAuthorization
    ) -> datetime:
        authorization.validate_unchanged()
        now = self.clock.now_utc()
        _require_aware(now, "trusted current time")
        if not authorization.window_start <= now < authorization.window_end:
            raise AuthorizationError("authorization execution window expired")
        return now

    def _inside_window(self, authorization: ExecutionAuthorization) -> bool:
        now = self.clock.now_utc()
        _require_aware(now, "trusted current time")
        return authorization.window_start <= now < authorization.window_end

    def _retry_fits_window(
        self, authorization: ExecutionAuthorization, delay_seconds: int
    ) -> bool:
        now = self.clock.now_utc()
        _require_aware(now, "trusted current time")
        return now + timedelta(seconds=delay_seconds) < authorization.window_end

    def _terminal(
        self,
        ledger: AttemptLedger,
        attempt_id: str,
        target: FrozenTarget,
        kind: AttemptKind,
        request: ProviderRequest,
        predecessor: str | None,
        reason: str,
    ) -> None:
        ledger.append(
            attempt_id=attempt_id,
            target_id=target.canonical_game_id,
            state=AttemptState.TERMINAL_STOP,
            observed_at=self.clock.now_utc(),
            attempt_kind=kind,
            request_sha256=request.canonical_sha256,
            predecessor_attempt_id=predecessor,
            details={"reason": reason},
        )

    @staticmethod
    def _failure(
        target: FrozenTarget, attempt_number: int, reason: str
    ) -> TargetExecutionResult:
        return TargetExecutionResult(
            target.canonical_game_id,
            True,
            attempt_number - 1,
            None,
            reason,
        )


def provider_request(target: FrozenTarget) -> ProviderRequest:
    lines = target.canonical_request.split("\n")
    if len(lines) != 3:
        raise EvidenceIntegrityError("canonical request shape mismatch")
    method, path, query = lines
    request_bytes = target.canonical_request.encode("utf-8")
    if _digest(request_bytes) != target.canonical_request_sha256:
        raise EvidenceIntegrityError("canonical request changed after manifest load")
    return ProviderRequest(
        target.canonical_game_id,
        method,
        path,
        query,
        request_bytes,
        target.canonical_request_sha256,
    )


def decode_application_body(response: ProviderResponse) -> bytes:
    encoding = (_header(response.headers, "content-encoding") or "identity").lower()
    try:
        if encoding in {"", "identity"}:
            return response.body
        if encoding == "gzip":
            return gzip.decompress(response.body)
        if encoding == "deflate":
            return zlib.decompress(response.body)
    except (OSError, EOFError, zlib.error) as error:
        raise TerminalPilotError("response body Content-Encoding is undecodable") from error
    raise TerminalPilotError("response Content-Encoding is unsupported")


def parse_success_response(
    body: bytes, *, target: FrozenTarget
) -> ResponseAnalysis:
    try:
        payload = json.loads(
            body.decode("utf-8"),
            parse_float=LexicalNumber,
            parse_int=LexicalNumber,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TerminalPilotError("required top-level JSON is unparsable") from error
    if not isinstance(payload, dict):
        raise TerminalPilotError("required top-level JSON must be an object")
    _assert_no_prohibited_data(payload)
    wrapper = _required_timestamp(payload, "timestamp")
    previous = _optional_timestamp(payload, "previous_timestamp")
    following = _optional_timestamp(payload, "next_timestamp")
    requested = _parse_timestamp(target.requested_date)
    if wrapper > requested:
        raise TerminalPilotError("response timestamp is after requested_date")
    if previous is not None and not previous < wrapper:
        raise TerminalPilotError("previous/current wrapper ordering failure")
    if following is not None and not requested < following:
        raise TerminalPilotError("requested/next wrapper ordering failure")
    response_age_ms = _milliseconds(requested - wrapper)
    previous_interval_ms = (
        _milliseconds(wrapper - previous) if previous is not None else None
    )
    next_interval_ms = (
        _milliseconds(following - wrapper) if following is not None else None
    )
    events = payload.get("data")
    if not isinstance(events, list):
        raise TerminalPilotError("wrapper data must be an array")
    try:
        matches = [event for event in events if _event_matches_target(event, target)]
    except ValueError as error:
        raise TerminalPilotError("required event identity is invalid") from error
    if len(matches) > 1:
        raise IdentityError("multiple provider events match the frozen target")
    non_target_count = len(events) - len(matches)
    if not matches:
        return ResponseAnalysis(
            _utc_text(wrapper),
            _utc_text(previous) if previous else None,
            _utc_text(following) if following else None,
            None,
            False,
            (),
            non_target_count,
            len(events) == 0,
            False,
            response_age_ms,
            previous_interval_ms,
            next_interval_ms,
        )
    event = matches[0]
    try:
        event_id = _required_text(event, "id")
    except ValueError as error:
        raise TerminalPilotError("required event identity is invalid") from error
    observations = _market_observations(event, wrapper, requested)
    return ResponseAnalysis(
        _utc_text(wrapper),
        _utc_text(previous) if previous else None,
        _utc_text(following) if following else None,
        event_id,
        True,
        tuple(observations),
        non_target_count,
        False,
        any(not observation.timestamp_eligible for observation in observations),
        response_age_ms,
        previous_interval_ms,
        next_interval_ms,
    )


def reconcile_quota(
    headers: Mapping[str, str],
    *,
    previous: QuotaSnapshot | None,
    empty_data: bool,
) -> QuotaSnapshot:
    values = {}
    for name in ("x-requests-used", "x-requests-remaining", "x-requests-last"):
        raw = _header(headers, name)
        if raw is None:
            raise QuotaIntegrityError("required quota evidence is missing")
        try:
            value = int(raw)
        except ValueError as error:
            raise QuotaIntegrityError("quota evidence is not an integer") from error
        if value < 0:
            raise QuotaIntegrityError("quota evidence is negative")
        values[name] = value
    snapshot = QuotaSnapshot(
        values["x-requests-used"],
        values["x-requests-remaining"],
        values["x-requests-last"],
    )
    if snapshot.last > RESERVED_CREDITS_PER_ATTEMPT:
        raise QuotaIntegrityError("provider charge exceeds conservative reservation")
    if snapshot.last == 0 and not empty_data:
        raise QuotaIntegrityError("zero-credit response is not empty/no-data")
    if previous is not None:
        if snapshot.used - previous.used != snapshot.last:
            raise QuotaIntegrityError("used-request quota delta is inconsistent")
        if previous.remaining - snapshot.remaining != snapshot.last:
            raise QuotaIntegrityError("remaining-request quota delta is inconsistent")
    return snapshot


def retry_delay_seconds(status_code: int, headers: Mapping[str, str]) -> int:
    if status_code != 429:
        value = _header(headers, "retry-after")
        if value is None:
            return 0
    else:
        value = _header(headers, "retry-after")
        if value is None:
            raise TerminalPilotError("429 response lacks Retry-After")
    try:
        seconds = int(value)
    except (TypeError, ValueError) as error:
        raise TerminalPilotError("Retry-After is invalid") from error
    if seconds < 0:
        raise TerminalPilotError("Retry-After is invalid")
    return seconds


def classify_complete_response(
    status_code: int, headers: Mapping[str, str]
) -> tuple[CompleteResponseAction, int, str]:
    if status_code == 200:
        return CompleteResponseAction.CONTINUE, 0, "complete_200"
    if status_code in {408, 429} or 500 <= status_code < 600:
        return (
            CompleteResponseAction.RETRY,
            retry_delay_seconds(status_code, headers),
            "transient_http_response",
        )
    if 300 <= status_code < 400:
        return CompleteResponseAction.TERMINAL, 0, "redirect_prohibited"
    if status_code == 204:
        return CompleteResponseAction.TERMINAL, 0, "empty_success_schema_failure"
    if 400 <= status_code < 500:
        return CompleteResponseAction.TERMINAL, 0, "non_transient_client_error"
    return CompleteResponseAction.TERMINAL, 0, "unexpected_http_status"


def build_report(results: Iterable[TargetExecutionResult]) -> PilotReport:
    ordered = tuple(results)
    terminal = next((item for item in ordered if item.terminal), None)
    if terminal is not None:
        return PilotReport(PilotDisposition.FAILED, ordered, terminal.failure_reason)
    if any(
        item.analysis is not None and item.analysis.revision_required
        for item in ordered
    ):
        return PilotReport(PilotDisposition.REVISION_REQUIRED, ordered, None)
    return PilotReport(PilotDisposition.SUFFICIENT, ordered, None)


def create_evidence_manifest(
    store: EvidenceStore,
    *,
    authorization: ExecutionAuthorization,
    config: PilotExecutionConfig,
    report_path: Path,
    recovery_provenance: RecoveryRuntimeProvenance | None = None,
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
        records.append({"bytes": len(data), "path": relative, "sha256": _digest(data)})
    if len({item["path"] for item in records}) != len(records):
        raise EvidenceIntegrityError("duplicate evidence artifact path")
    payload = {
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
        "protocol": {"identity": PROTOCOL_ID, "sha256": PROTOCOL_SHA256},
        "pilot_spec": {"identity": PILOT_SPEC_ID, "sha256": PILOT_SPEC_SHA256},
        "report": report_path.relative_to(store.root).as_posix(),
        "runtime_attribution": {
            "original_execution": {
                "implementation_identity": IMPLEMENTATION_ID,
                "runtime_provenance_path": "runtime_provenance.json",
                "runtime_provenance_sha256": _digest(
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
        "selection_manifest": {"identity": SELECTION_ID, "sha256": SELECTION_SHA256},
    }
    _exclusive_write(manifest_path, _canonical_json_bytes(payload))
    return manifest_path


def verify_evidence_manifest(store: EvidenceStore, manifest_path: Path) -> None:
    try:
        payload = json.loads(manifest_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceIntegrityError("evidence manifest is invalid") from error
    files = payload.get("files")
    if not isinstance(files, list):
        raise EvidenceIntegrityError("evidence manifest file inventory is invalid")
    paths = [item.get("path") for item in files if isinstance(item, dict)]
    if len(paths) != len(files) or len(paths) != len(set(paths)):
        raise EvidenceIntegrityError("evidence manifest contains duplicate/invalid paths")
    for relative in paths:
        if (
            not isinstance(relative, str)
            or "\\" in relative
            or PurePosixPath(relative).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts)
        ):
            raise EvidenceIntegrityError("evidence manifest path is unsafe")
    expected = set(paths)
    actual = {
        path.relative_to(store.root).as_posix()
        for path in store.root.rglob("*")
        if path.is_file()
        and path != manifest_path
        and path.name != ".pilot.lock"
    }
    if actual != expected:
        raise EvidenceIntegrityError("evidence manifest has missing or extra artifacts")
    for item in files:
        path = (store.root / item["path"]).resolve()
        if store.root not in path.parents:
            raise EvidenceIntegrityError("evidence manifest path escapes store")
        data = path.read_bytes()
        if len(data) != item.get("bytes") or _digest(data) != item.get("sha256"):
            raise EvidenceIntegrityError("evidence artifact size/SHA-256 mismatch")


def redact_headers(
    headers: Mapping[str, str], *, secret_values: Sequence[str] = ()
) -> dict[str, str]:
    result = {}
    for name, value in headers.items():
        normalized = str(name).lower()
        if normalized in {"authorization", "proxy-authorization", "x-api-key", "api-key"}:
            result[normalized] = "[REDACTED]"
        else:
            redacted = str(value)
            for secret in secret_values:
                if secret:
                    redacted = redacted.replace(secret, "[REDACTED]")
            result[normalized] = redacted
    return dict(sorted(result.items()))


def analysis_payload(analysis: ResponseAnalysis) -> dict[str, Any]:
    return {
        "empty_data": analysis.empty_data,
        "next_timestamp": analysis.next_timestamp,
        "non_target_event_count": analysis.non_target_event_count,
        "observations": [
            {
                "age_bin": item.age_bin,
                "bookmaker_key": item.bookmaker_key,
                "bookmaker_last_update": item.bookmaker_last_update,
                "classification": item.classification,
                "market_last_update": item.market_last_update,
                "prices": [[name, token] for name, token in item.prices],
                "market_minus_response_ms": item.market_minus_response_ms,
                "snapshot_age_ms": item.snapshot_age_ms,
                "timestamp_eligible": item.timestamp_eligible,
            }
            for item in analysis.observations
        ],
        "previous_timestamp": analysis.previous_timestamp,
        "revision_required": analysis.revision_required,
        "response_snapshot_age_ms": analysis.response_snapshot_age_ms,
        "target_event_id": analysis.target_event_id,
        "target_found": analysis.target_found,
        "next_interval_ms": analysis.next_interval_ms,
        "previous_interval_ms": analysis.previous_interval_ms,
        "wrapper_timestamp": analysis.wrapper_timestamp,
    }


def _market_observations(
    event: Mapping[str, Any], wrapper: datetime, requested: datetime
) -> list[MarketObservation]:
    bookmakers = event.get("bookmakers")
    if not isinstance(bookmakers, list):
        raise TerminalPilotError("event bookmakers must be an array")
    observations = []
    for bookmaker in bookmakers:
        if not isinstance(bookmaker, dict):
            raise TerminalPilotError("bookmaker must be an object")
        try:
            key = _required_text(bookmaker, "key")
        except ValueError as error:
            raise TerminalPilotError("bookmaker key is missing or invalid") from error
        markets = bookmaker.get("markets")
        if not isinstance(markets, list):
            raise TerminalPilotError("bookmaker markets must be an array")
        if key not in EXPECTED_BOOKS:
            continue
        bookmaker_last = bookmaker.get("last_update")
        bookmaker_context = bookmaker_last if isinstance(bookmaker_last, str) else None
        for market in markets:
            if not isinstance(market, dict):
                raise TerminalPilotError("market must be an object")
            if market.get("key") != EXPECTED_MARKET:
                continue
            prices = _outcome_prices(market.get("outcomes"))
            raw_last = market.get("last_update")
            try:
                market_time = (
                    _parse_timestamp(raw_last)
                    if isinstance(raw_last, str) and raw_last
                    else None
                )
            except ValueError:
                market_time = None
            if market_time is None:
                observations.append(
                    MarketObservation(
                        key,
                        bookmaker_context,
                        raw_last if isinstance(raw_last, str) else None,
                        "MARKET_TIMESTAMP_FIELD_MISSING_OR_INVALID",
                        False,
                        None,
                        None,
                        None,
                        prices,
                    )
                )
                continue
            if market_time > requested:
                raise TerminalPilotError("market last_update is after requested_date")
            if market_time > wrapper:
                raise TerminalPilotError("market last_update is after response timestamp")
            age_ms = _milliseconds(requested - market_time)
            observations.append(
                MarketObservation(
                    key,
                    bookmaker_context,
                    _utc_text(market_time),
                    "TIMESTAMP_ELIGIBLE",
                    True,
                    age_ms,
                    _milliseconds(market_time - wrapper),
                    _age_bin(age_ms),
                    prices,
                )
            )
    return observations


def _outcome_prices(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise TerminalPilotError("market outcomes must be an array")
    prices = []
    for outcome in value:
        if not isinstance(outcome, dict):
            raise TerminalPilotError("market outcome must be an object")
        try:
            name = _required_text(outcome, "name")
        except ValueError as error:
            raise TerminalPilotError("outcome name is missing or invalid") from error
        token = outcome.get("price")
        if not isinstance(token, LexicalNumber):
            raise TerminalPilotError("market price must be a lexical JSON number")
        try:
            if Decimal(str(token)) <= 1:
                raise TerminalPilotError("decimal price must be greater than one")
        except InvalidOperation as error:
            raise TerminalPilotError("market price token is invalid") from error
        prices.append((name, str(token)))
    if len(prices) != 2 or len({name for name, _ in prices}) != 2:
        raise TerminalPilotError("h2h market must contain two distinct outcomes")
    return tuple(prices)


def _event_matches_target(event: Any, target: FrozenTarget) -> bool:
    if not isinstance(event, dict):
        raise TerminalPilotError("provider event must be an object")
    for name in ("id", "sport_key", "commence_time", "home_team", "away_team"):
        _required_text(event, name)
    if not isinstance(event.get("bookmakers"), list):
        raise TerminalPilotError("event bookmakers must be an array")
    if event["sport_key"] != EXPECTED_SPORT:
        return False
    home_names = {target.home_team, TEAM_PROVIDER_NAMES.get(target.home_team, target.home_team)}
    away_names = {target.away_team, TEAM_PROVIDER_NAMES.get(target.away_team, target.away_team)}
    if event["home_team"] not in home_names or event["away_team"] not in away_names:
        return False
    commence = _parse_timestamp(event["commence_time"])
    retained_text = {
        item.get("scheduled_kickoff_utc")
        for item in target.authority_version_chain
        if item.get("scheduled_kickoff_utc") is not None
    }
    retained_text.add(target.kickoff_utc)
    try:
        retained = {_parse_timestamp(item) for item in retained_text}
    except ValueError as error:
        raise IdentityError("retained kickoff authority is invalid") from error
    if commence not in retained:
        raise IdentityError("target commence_time conflicts with retained kickoff versions")
    return True


def _assert_no_prohibited_data(value: Any) -> None:
    if isinstance(value, Mapping):
        conflicts = _FORBIDDEN_RESPONSE_KEYS.intersection(str(key).lower() for key in value)
        if conflicts:
            raise ProhibitedDataError("provider response contains prohibited data fields")
        for item in value.values():
            _assert_no_prohibited_data(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _assert_no_prohibited_data(item)


def _validate_canonical_request(request: str, requested_date: Any) -> None:
    expected = (
        "GET\n/v4/historical/sports/americanfootball_nfl/odds\n"
        "bookmakers=draftkings%2Cfanduel%2Cbetmgm%2Cbetrivers"
        f"&date={requested_date}&markets=h2h&oddsFormat=decimal"
    )
    if request != expected or "apiKey" in request or "apikey" in request.lower():
        raise EvidenceIntegrityError("canonical provider request contract mismatch")


def _required_text(value: Mapping[str, Any], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result:
        raise ValueError(f"required field {name} is missing or invalid")
    return result


def _required_timestamp(value: Mapping[str, Any], name: str) -> datetime:
    try:
        return _parse_timestamp(_required_text(value, name))
    except ValueError as error:
        raise TerminalPilotError(f"required wrapper field {name} is invalid") from error


def _optional_timestamp(value: Mapping[str, Any], name: str) -> datetime | None:
    if name not in value:
        raise TerminalPilotError(f"optional wrapper field {name} is missing")
    raw = value.get(name)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TerminalPilotError(f"optional wrapper field {name} has invalid type")
    try:
        return _parse_timestamp(raw)
    except ValueError as error:
        raise TerminalPilotError(f"optional wrapper field {name} is invalid") from error


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError("timestamp must be strict timezone-aware RFC3339")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    _require_aware(parsed, "timestamp")
    return parsed.astimezone(timezone.utc)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "timestamp")
    milliseconds = value.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return milliseconds.replace("+00:00", "Z")


def _milliseconds(value: timedelta) -> int:
    return value.days * 86_400_000 + value.seconds * 1000 + value.microseconds // 1000


def _age_bin(milliseconds: int) -> str:
    minute = 60_000
    for maximum, label in (
        (5 * minute, "[0,5m]"),
        (10 * minute, "(5m,10m]"),
        (15 * minute, "(10m,15m]"),
        (30 * minute, "(15m,30m]"),
        (60 * minute, "(30m,60m]"),
        (180 * minute, "(60m,180m]"),
    ):
        if milliseconds <= maximum:
            return label
    return "(180m,+infinity)"


def _header(headers: Mapping[str, str], name: str) -> str | None:
    sought = name.lower()
    for key, value in headers.items():
        if str(key).lower() == sought:
            return str(value)
    return None


def _response_contains_secret(
    response: ProviderResponse,
    body: bytes,
    credential: SecretCredential,
) -> bool:
    token = credential.value
    if token.encode("utf-8") in body:
        return True
    return any(token in str(value) for value in response.headers.values())


def _safe_details(details: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "reason", "reserved_credits", "status_code", "retry_permitted",
        "retry_after_seconds", "body_sha256", "body_bytes",
    }
    if set(details) - allowed:
        raise ValueError("ledger details contain a non-allowlisted field")
    return {str(key): details[key] for key in sorted(details)}


def _pilot_error_reason(error: PilotError) -> str:
    if isinstance(error, ProhibitedDataError):
        return "prohibited_data_exposure"
    if isinstance(error, QuotaIntegrityError):
        return "quota_integrity_failure"
    if isinstance(error, IdentityError):
        return "target_identity_failure"
    if isinstance(error, TerminalPilotError):
        return "response_schema_or_timestamp_failure"
    if isinstance(error, EvidenceIntegrityError):
        return "evidence_integrity_failure"
    if isinstance(error, AuthorizationError):
        return "authorization_failure"
    return "pilot_integrity_failure"


def _canonical_json_bytes(value: Any, *, terminal_lf: bool = True) -> bytes:
    text = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return (text + ("\n" if terminal_lf else "")).encode("utf-8")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceIntegrityError("governed JSON artifact is invalid") from error
    if not isinstance(value, dict):
        raise EvidenceIntegrityError("governed JSON artifact must be an object")
    return value


def _digest(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _exclusive_write(path: Path, value: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise EvidenceCollisionError("immutable evidence artifact already exists") from error
    except OSError as error:
        raise EvidenceIOError("immutable evidence artifact write failed") from error
    _fsync_directory(path.parent)


def _lock_file_descriptor(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise BlockingIOError("file lease is held") from error
        return
    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        raise BlockingIOError("file lease is held") from error


def _unlock_file_descriptor(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        except OSError:
            return
        return
    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        return


def _fsync_directory(path: Path) -> None:
    """Best-effort directory metadata flush, including a Windows handle path."""

    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return
    try:
        import ctypes
        from ctypes import wintypes

        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(path), 0x40000000, 0x00000007, None, 3, 0x02000000, None
        )
        if handle not in (0, -1):
            try:
                ctypes.windll.kernel32.FlushFileBuffers(handle)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return
