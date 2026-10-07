"""Synthetic sentinel only; candidates omit all activation authority everywhere."""
from dataclasses import asdict, replace
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import ast
import getpass
import http.client
import json
from pathlib import Path
import socket
import traceback
import zipfile

import pytest

from sportsmodel.nfl import historical_market_pilot as core
from sportsmodel.nfl import historical_market_pilot_integrated as integrated
from sportsmodel.nfl import historical_market_odds_api_transport as transport
from sportsmodel.nfl import historical_market_pilot_authorization as boundary

ROOT = Path(__file__).resolve().parents[2]
SECRET = "TEST_KEY_DO_NOT_SEND"
NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)  # Expired relative to task date.
LABEL = "nfl-historical-market-pilot:dedicated-20k:test-only"
ID = "b5efc8bb-d240-4c70-bd7a-645ea2b8afbb"
HEAD = "729b1cfa23fdb1494fae9420834601b7b92b8ca1"
SELECTION = core.load_frozen_selection(ROOT /
    "docs/architecture/nfl_historical_market_provider_pilot_selection_manifest_0.1.3.json")
FROZEN_VERIFIER = boundary._verify_frozen


def prohibited(*args, **kwargs):
    raise AssertionError("REAL NETWORK/DB/SECRET DISCOVERY PROHIBITED")


@pytest.fixture(autouse=True)
def isolation(monkeypatch):
    import dotenv
    import psycopg2
    import requests
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, prohibited)
    monkeypatch.setattr(http.client, "HTTPSConnection", prohibited)
    monkeypatch.setattr(transport.OddsApiHistoricalTransport, "prepare", prohibited)
    monkeypatch.setattr(integrated.IntegratedPilotExecutor, "run", prohibited)
    monkeypatch.setattr(integrated.IntegratedPilotExecutor, "__init__", prohibited)
    monkeypatch.setattr(requests.sessions.Session, "request", prohibited)
    monkeypatch.setattr(psycopg2, "connect", prohibited)
    monkeypatch.setattr(dotenv, "load_dotenv", prohibited)
    monkeypatch.setattr(dotenv, "dotenv_values", prohibited)
    monkeypatch.setattr(getpass, "getpass", prohibited)
    # Test only names of trust-store overrides, never read inherited values.
    monkeypatch.setattr(boundary.os, "environ", {})


@pytest.fixture
def case(tmp_path, monkeypatch):
    directory = tmp_path / boundary.STORAGE_NAMESPACE
    directory.mkdir()
    credential = directory / "credential-test-only.json"
    credential.write_bytes(core._canonical_json_bytes(boundary._identity_payload(
        LABEL, "TEST_ONLY_OWNER_ACCOUNT_VERIFICATION", core.SecretCredential(SECRET).fingerprint)))
    policy = boundary.ClockPolicy("TEST_ONLY_POLICY", 100, 300, 10, 250)
    request = boundary.CandidateRequest(
        candidate_id=ID, approved_head=HEAD,
        runtime_identity="TEST_ONLY_RUNTIME", dependency_identity="D"*64,
        timezone_identity="tzdata:2026.2", clock_identity=core.component_runtime_identity(core.SystemPilotClock()),
        monotonic_timer_identity=core.SystemPilotClock().monotonic_identity,
        evidence_store_root=directory / "evidence" / ID,
        kickoff_package_path=directory / "NFL_Kickoff_Authority_Reconciliation_0.2.0.zip",
        connect_timeout_seconds=10.0, read_timeout_seconds=30.0, clock_policy=policy)
    output = directory / ("candidate-"+ID+".json")
    monkeypatch.setattr(core.SystemPilotClock, "now_utc", lambda self: NOW)

    def frozen(root, kickoff):
        # Real repository bytes/selection, synthetic retained-ZIP boundary.
        for path, digest in boundary._FROZEN.items():
            assert core._digest((root / path).read_bytes()) == digest
        return SELECTION

    def inspect(context):
        c = context.config
        return core.RuntimeProvenance(
            repository_root=str(ROOT.resolve()), git_head=HEAD, git_clean=True,
            implementation_source_sha256=boundary.INTEGRATION_SHA, configuration_sha256=c.sha256,
            runtime_identity=request.runtime_identity, dependency_identity=request.dependency_identity,
            timezone_identity=request.timezone_identity, evidence_store_root=c.evidence_store_root,
            os_sync_source=boundary.ACCEPTED_TIME_SOURCE, os_sync_status="SYNCHRONIZED",
            phase_offset_evidence="0.002s", last_successful_sync_evidence="2026-10-01T11:59:00Z",
            clock_identity=request.clock_identity, monotonic_timer_identity=request.monotonic_timer_identity,
            transport_identity=c.transport_identity, runtime_mode=integrated.RUNTIME_MODE,
            runtime_inspector_identity=core.RUNTIME_INSPECTOR_ID)

    monkeypatch.setattr(boundary, "_verify_frozen", frozen)
    monkeypatch.setattr(integrated, "_inspect_runtime", inspect)
    return request, credential, output, inspect


def build(case, **changes):
    request, credential, output, _ = case
    return boundary.build_candidate(request=replace(request, **changes), credential_artifact=credential,
                                    output=output, repository_root=ROOT)


def test_interactive_establishment_derives_frozen_fingerprint(case, monkeypatch, capsys):
    _, _, output, _ = case
    path = output.parent / "new-credential.json"
    prompts = []
    monkeypatch.setattr(getpass, "getpass", lambda prompt: prompts.append(prompt) or SECRET)
    sha = boundary.establish_credential_identity(output=path, repository_root=ROOT, label=LABEL,
                                                verification_reference="TEST_ONLY_ACCOUNT")
    raw, payload = boundary.load_credential_identity(path, ROOT)
    assert sha == core._digest(raw)
    assert payload["fingerprint"] == core.SecretCredential(SECRET).fingerprint
    assert payload["quota_attribution_mode"] == "DEDICATED_CREDENTIAL"
    assert len(prompts) == 1
    assert SECRET not in raw.decode() + repr(payload) + str(payload) + capsys.readouterr().out
    assert set(payload) == {"schema", "identity", "fingerprint", "quota_attribution_mode", "provider",
                            "subscription", "independent_credit_meter", "historical_entitlement_confirmed",
                            "verification_reference"}


def test_wrong_reentered_credential(case, monkeypatch):
    _, credential, _, _ = case
    monkeypatch.setattr(getpass, "getpass", lambda prompt: SECRET + "_WRONG")
    with pytest.raises(boundary.BoundaryError, match="fingerprint mismatch"):
        boundary.verify_credential_interactively(credential, ROOT)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: SECRET)
    assert boundary.verify_credential_interactively(credential, ROOT) is None


@pytest.mark.parametrize("mode", ["empty", "warning", "exception", "interrupt", "label-echo"])
def test_secure_prompt_failure_has_no_secret_context(case, monkeypatch, mode):
    _, _, output, _ = case
    def prompt(_):
        if mode == "empty":
            return ""
        if mode == "warning":
            import warnings
            warnings.warn("no secure console", getpass.GetPassWarning)
            pytest.fail("getpass fallback reached input")
        if mode == "exception":
            raise ValueError(SECRET)
        if mode == "interrupt":
            raise KeyboardInterrupt(SECRET)
        return SECRET
    monkeypatch.setattr(getpass, "getpass", prompt)
    target = output.parent / "failed-credential.json"
    ref = SECRET if mode == "label-echo" else "TEST_ONLY_ACCOUNT"
    with pytest.raises(boundary.BoundaryError) as caught:
        boundary.establish_credential_identity(output=target, repository_root=ROOT, label=LABEL,
                                                verification_reference=ref)
    assert caught.value.__context__ is None
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert not target.exists()


def test_existing_credential_not_overwritten_or_prompted(case):
    _, credential, _, _ = case
    original = credential.read_bytes()
    with pytest.raises(boundary.BoundaryError, match="already exists"):
        boundary.establish_credential_identity(output=credential, repository_root=ROOT,
                                                label=LABEL, verification_reference="TEST_ONLY_ACCOUNT")
    assert credential.read_bytes() == original


@pytest.mark.parametrize("patch", [{"key": SECRET}, {"quota_attribution_mode": "QUIET_WINDOW"},
                                    {"historical_entitlement_confirmed": 1},
                                    {"independent_credit_meter": 20000.0}, {"identity": "MLB_PRODUCTION"},
                                    {"fingerprint": "not-a-hash"}])
def test_artifact_is_strict_and_dedicated(case, patch):
    _, path, _, _ = case
    payload = json.loads(path.read_bytes())
    payload.update(patch)
    path.write_bytes(core._canonical_json_bytes(payload))
    with pytest.raises(boundary.BoundaryError):
        boundary.load_credential_identity(path, ROOT)


def test_env_path_rejected_before_read(monkeypatch):
    monkeypatch.setattr(Path, "read_bytes", prohibited)
    with pytest.raises(boundary.BoundaryError):
        boundary.load_credential_identity(ROOT / ".env", ROOT)
    with pytest.raises(boundary.BoundaryError):
        boundary.load_credential_identity(ROOT / "credential.json", ROOT)


def test_candidate_shape_binding_and_frozen_admission_rejection(case):
    request, credential, output, _ = case
    sha = build(case)
    raw = output.read_bytes()
    result = json.loads(raw)
    assert sha == core._digest(raw)
    assert raw == core._canonical_json_bytes(result)
    assert result["execution_authorized"] is False
    assert result["status"] == "CANDIDATE ONLY — NOT EXECUTION AUTHORITY"
    assert result["credential_artifact_sha256"] == core._digest(credential.read_bytes())
    assert result["clock_policy"] == asdict(request.clock_policy)
    fields = result["reviewed_bindings"]
    assert "authorization_candidate" not in result
    assert result["candidate_id"] == ID
    assert result["activation_requirements"]["omitted_loader_fields"] == sorted(boundary.ACTIVATION_ONLY_FIELDS)
    assert fields["target_ids"] == list(SELECTION.target_ids)
    assert fields["ceilings"] == {"primary":20,"retries":20,"attempts":40,"credits":400,"per_attempt_reservation":10}
    assert fields["components"]["integration"]["sha256"] == boundary.INTEGRATION_SHA
    assert fields["protocol"]["sha256"] == core.PROTOCOL_SHA256
    assert fields["pilot_spec"]["sha256"] == core.PILOT_SPEC_SHA256
    assert fields["selection_manifest"]["sha256"] == core.SELECTION_SHA256
    assert result["population_sha256"] == core.POPULATION_SHA256
    assert fields["credential"]["quota_attribution_mode"] == "DEDICATED_CREDENTIAL"
    assert fields["execution_policy"]["mode"] == "INITIAL_ONLY_NO_CONTINUATION"
    assert fields["evidence_store_root"] == str(request.evidence_store_root)
    assert SECRET.encode() not in raw
    assert not request.evidence_store_root.exists()
    config = boundary._request_config(request, json.loads(credential.read_bytes()), SELECTION, output)
    # Outer candidate fails even when passed an in-window test time.
    with pytest.raises(core.AuthorizationError, match="component bundle mismatch"):
        integrated.load_and_validate_authorization(output, config=config, selection=SELECTION, now=NOW)


def test_candidate_determinism_with_identical_measured_inputs(case):
    _, _, output, _ = case
    build(case)
    first = output.read_bytes()
    # Test-only reset of this synthetic file; not a production overwrite route.
    output.unlink()
    build(case)
    assert output.read_bytes() == first


def test_candidate_overwrite_refused(case):
    _, _, output, _ = case
    build(case)
    original = output.read_bytes()
    with pytest.raises(boundary.BoundaryError, match="non-existing"):
        build(case)
    assert output.read_bytes() == original


@pytest.mark.parametrize("field,value", [("git_clean",False),("git_head","b"*40),
    ("runtime_identity","OTHER"),("dependency_identity","F"*64),("timezone_identity","OTHER"),
    ("clock_identity","OTHER"),("monotonic_timer_identity","OTHER"),
    ("transport_identity","OTHER"),("os_sync_source","time.windows.com"),
    ("os_sync_status","UNSYNCHRONIZED"),("runtime_inspector_identity","OTHER"),
    ("configuration_sha256","F"*64),("implementation_source_sha256","F"*64)])
def test_measured_identity_mismatch_rejected(case, monkeypatch, field, value):
    _, _, output, inspect = case
    monkeypatch.setattr(integrated, "_inspect_runtime", lambda c: replace(inspect(c), **{field:value}))
    with pytest.raises(boundary.BoundaryError, match="identity mismatch"):
        build(case)
    assert not output.exists()


@pytest.mark.parametrize("change", [{"approved_head":"b"*40},{"runtime_identity":"OTHER"},
    {"clock_identity":"OTHER"},{"connect_timeout_seconds":True},
    {"read_timeout_seconds":float("nan")}, {"candidate_id":"not-unique"}])
def test_request_rejections(case, change):
    with pytest.raises((boundary.BoundaryError,ValueError)):
        build(case, **change)
    assert not case[2].exists()


@pytest.mark.parametrize("phase,sync", [("1s","2026-10-01T11:59:00Z"),
    ("0s","2026-10-01T11:00:00Z"),("0s","2026-10-01T12:00:01Z"),
    ("NaNs","2026-10-01T11:59:00Z"),("0s","not-a-date")])
def test_clock_plausibility_freshness_failures(case, monkeypatch, phase, sync):
    _, _, output, inspect = case
    monkeypatch.setattr(integrated, "_inspect_runtime", lambda c: replace(inspect(c),
        phase_offset_evidence=phase,last_successful_sync_evidence=sync))
    with pytest.raises((boundary.BoundaryError,core.AuthorizationError)):
        build(case)
    assert not output.exists()


@pytest.mark.parametrize("phase", ["0.1s", "100ms", "100000us", "100000µs", "100000000ns", "-100ms"])
def test_clock_units_and_inclusive_limits(case, phase):
    request, credential, output, inspect = case
    c = boundary._request_config(request,json.loads(credential.read_bytes()),SELECTION,output)
    boundary.validate_clock(replace(inspect(type("Context",(),{"config":c})()), phase_offset_evidence=phase,
        last_successful_sync_evidence="2026-10-01T11:55:00Z"), NOW, request.clock_policy)


@pytest.mark.parametrize("value", [True,0,-1,float("nan"),100.0])
def test_clock_policy_requires_explicit_positive_integers(value):
    with pytest.raises(boundary.BoundaryError):
        boundary.ClockPolicy("TEST_ONLY_POLICY",value,300,10,250)


def test_windows_local_timezone_and_dst_fail_closed(monkeypatch):
    monkeypatch.setattr(boundary,"_windows_timezone_identity",lambda:"Pacific Standard Time")
    assert boundary._sync_utc("10/1/2026 4:59:00 AM") == NOW-timedelta(minutes=1)
    for stamp in ("11/1/2026 1:30:00 AM","3/8/2026 2:30:00 AM"):
        with pytest.raises(boundary.BoundaryError):
            boundary._sync_utc(stamp)
    monkeypatch.setattr(boundary,"_windows_timezone_identity",lambda:"OTHER")
    with pytest.raises(boundary.BoundaryError):
        boundary._sync_utc("10/1/2026 4:59:00 AM")


@pytest.mark.parametrize("name", ["SSL_CERT_FILE","SSL_CERT_DIR"])
def test_trust_store_override_rejected_by_name_only(case, monkeypatch, name):
    class NamesOnly(Mapping):
        def __iter__(self):
            return iter((name,))
        def __len__(self):
            return 1
        def __getitem__(self,key):
            prohibited()
    # Restrict the read-denying Mapping to the call, not pytest's own reporter.
    with monkeypatch.context() as scoped:
        scoped.setattr(boundary.os,"environ",NamesOnly())
        with pytest.raises(boundary.BoundaryError,match="trust-store"):
            build(case)


def test_remeasurement_failure_creates_no_candidate(case, monkeypatch):
    _, _, output, inspect = case
    count = 0
    def changed(context):
        nonlocal count
        count += 1
        return replace(inspect(context),git_clean=count==1)
    monkeypatch.setattr(integrated,"_inspect_runtime",changed)
    with pytest.raises(boundary.BoundaryError):
        build(case)
    assert count == 2 and not output.exists()


def test_frozen_verifier_checks_zip_ledger_and_repository(case, monkeypatch):
    request, _, _, _ = case
    # Real verifier, synthetic ZIP and hashes solely in this isolated test.
    data = b"TEST_ONLY_SYNTHETIC_PUBLIC_KICKOFF_LEDGER\n"
    with zipfile.ZipFile(request.kickoff_package_path,"w") as archive:
        archive.writestr("nfl_kickoff_authority_ledger_0.2.0.jsonl",data)
    monkeypatch.setattr(core,"KICKOFF_PACKAGE_SHA256",core._digest(request.kickoff_package_path.read_bytes()))
    monkeypatch.setattr(core,"KICKOFF_LEDGER_SHA256",core._digest(data))
    monkeypatch.setattr(core,"load_frozen_selection",lambda path:SELECTION)
    assert FROZEN_VERIFIER(ROOT,request.kickoff_package_path) == SELECTION
    monkeypatch.setattr(core,"KICKOFF_LEDGER_SHA256","F"*64)
    with pytest.raises(boundary.BoundaryError,match="ledger"):
        FROZEN_VERIFIER(ROOT,request.kickoff_package_path)


def test_no_key_argv_or_live_command(case,capsys):
    with pytest.raises(SystemExit):
        boundary.main(["execute","--api-key",SECRET])
    output=capsys.readouterr()
    assert SECRET not in output.out+output.err


def test_source_has_no_credential_discovery_or_execution_calls():
    tree=ast.parse(Path(boundary.__file__).read_text())
    forbidden={"getenv","load_dotenv","dotenv_values","prepare","send","run",
               "getaddrinfo","create_connection","IntegratedPilotExecutor","connect"}
    for node in ast.walk(tree):
        if isinstance(node,ast.Call):
            name=getattr(node.func,"attr",getattr(node.func,"id",None))
            # Local subprocess.run is only tzutil /g, not an executor run.
            if name=="run" and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name):
                assert node.func.value.id=="subprocess"
            else:
                assert name not in forbidden


def test_builder_never_reads_ambient_credential_values(case, monkeypatch):
    class NamesOnly(dict):
        def __getitem__(self, key):
            prohibited()
        def get(self, *args):
            prohibited()
    monkeypatch.setattr(boundary.os, "environ", NamesOnly({
        "ODDS_API_KEY": SECRET, "SPORTSMODEL_ENV_FILE": "TEST_ONLY_UNREAD"}))
    build(case)


def test_measurement_deadline_and_wall_clock_step(case, monkeypatch):
    monotonic = iter([0, 20_000_000_000])
    monkeypatch.setattr(core.SystemPilotClock, "monotonic_ns", lambda self: next(monotonic))
    with pytest.raises(boundary.BoundaryError, match="measurement duration"):
        build(case)
    assert not case[2].exists()


def test_wall_clock_discontinuity(case, monkeypatch):
    times = iter([NOW, NOW + timedelta(seconds=1)])
    monkeypatch.setattr(core.SystemPilotClock, "now_utc", lambda self: next(times))
    with pytest.raises(boundary.BoundaryError, match="wall clock step"):
        build(case)
    assert not case[2].exists()


def test_candidate_readonly_revalidation(case):
    request, credential, output, _ = case
    expected = build(case)
    original = output.read_bytes()
    assert boundary.validate_candidate(request=request, credential_artifact=credential,
        candidate=output, repository_root=ROOT) == expected
    assert output.read_bytes() == original and not request.evidence_store_root.exists()


@pytest.mark.parametrize("field", ["ceilings", "targets", "components", "fingerprint", "policy",
                                    "authority", "extra", "runtime-type"])
def test_candidate_tampering_rejected(case, field):
    request, credential, output, _ = case
    build(case)
    payload = json.loads(output.read_bytes())
    if field == "ceilings":
        payload["reviewed_bindings"]["ceilings"]["credits"] = 401
    elif field == "targets":
        payload["reviewed_bindings"]["target_ids"] = []
    elif field == "components":
        payload["reviewed_bindings"]["components"]["executor"]["sha256"] = "F"*64
    elif field == "fingerprint":
        payload["reviewed_bindings"]["credential"]["fingerprint"] = "F"*64
    elif field == "policy":
        payload["clock_policy"]["max_sync_age_seconds"] = 99999
    elif field == "authority":
        payload["execution_authorized"] = True
    elif field == "runtime-type":
        payload["initial_provenance"]["git_clean"] = 1
    else:
        payload["extra"] = "UNAPPROVED"
    output.write_bytes(core._canonical_json_bytes(payload))
    with pytest.raises(boundary.BoundaryError):
        boundary.validate_candidate(request=request, credential_artifact=credential,
                                    candidate=output, repository_root=ROOT)


def test_explicit_builder_cli_and_request_schema(case, capsys):
    request, credential, output, _ = case
    payload = asdict(request)
    for key in ("evidence_store_root", "kickoff_package_path"):
        payload[key] = str(payload[key])
    path = output.parent / "request-test-only.json"
    path.write_bytes(core._canonical_json_bytes(payload))
    args = ["--request", str(path), "--credential-artifact", str(credential),
            "--repository-root", str(ROOT)]
    assert boundary.main(["build-candidate", *args, "--output", str(output)]) == 0
    built_output = capsys.readouterr()
    assert str(output) in built_output.out
    assert core._digest(output.read_bytes()) in built_output.out
    assert SECRET not in built_output.out + built_output.err
    assert boundary.main(["validate-candidate", *args, "--candidate", str(output)]) == 0
    validated_output = capsys.readouterr()
    assert str(output) in validated_output.out
    assert core._digest(output.read_bytes()) in validated_output.out
    assert SECRET not in validated_output.out + validated_output.err
    payload["actual_api_key"] = SECRET
    path.write_bytes(core._canonical_json_bytes(payload))
    assert boundary.main(["validate-candidate", *args, "--candidate", str(output)]) == 1
    assert SECRET not in capsys.readouterr().out


@pytest.mark.parametrize("field", sorted(boundary.ACTIVATION_ONLY_FIELDS))
def test_request_schema_rejects_activation_fields(case, field):
    request, _, output, _ = case
    payload = asdict(request)
    for key in ("evidence_store_root", "kickoff_package_path"):
        payload[key] = str(payload[key])
    payload[field] = None
    path = output.parent / "request-with-authority.json"
    path.write_bytes(core._canonical_json_bytes(payload))
    with pytest.raises(boundary.BoundaryError):
        boundary._load_request(path, ROOT)


def test_actual_frozen_inspector_path_rejects_dirty_repository(case, monkeypatch):
    # Restore the actual frozen integrated helper; mock only OS evidence inputs.
    def actual(context):
        measured = core.LocalRuntimeProvenanceInspector(context.repository_root).inspect(
            config=context.config, transport=context._network, clock=context.clock)
        return replace(measured, implementation_source_sha256=boundary.INTEGRATION_SHA,
                       runtime_mode=integrated.RUNTIME_MODE)
    def git(self, *args):
        if args == ("rev-parse", "--show-toplevel"):
            return str(ROOT)
        if args == ("rev-parse", "HEAD"):
            return HEAD
        return "?? TEST_ONLY_DIRTY_FILE"
    monkeypatch.setattr(core.LocalRuntimeProvenanceInspector, "_git", git)
    monkeypatch.setattr(core.LocalRuntimeProvenanceInspector, "_windows_time_evidence",
        staticmethod(lambda: (boundary.ACCEPTED_TIME_SOURCE,"SYNCHRONIZED","0s","2026-10-01T11:59:00Z")))
    monkeypatch.setattr(integrated, "_inspect_runtime", actual)
    with pytest.raises(boundary.BoundaryError, match="identity mismatch"):
        build(case)
    assert not case[2].exists()


def test_network_share_rejected_before_path_resolution(monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "resolve", prohibited)
        with pytest.raises(boundary.BoundaryError, match="local fixed-drive"):
            boundary.load_credential_identity(Path("//api.the-odds-api.com/share/NFL_Historical_Market_Pilot/key.json"), ROOT)


def test_mapped_network_drive_rejected_before_file_access(case, monkeypatch):
    if boundary.os.name != "nt":
        return  # Windows-specific guard, remaining tests are platform-independent.
    class RemoteDrive:
        def __call__(self, path):
            return 4
    with monkeypatch.context() as scoped:
        scoped.setattr(boundary.ctypes.windll.kernel32, "GetDriveTypeW", RemoteDrive())
        scoped.setattr(Path, "resolve", prohibited)
        with pytest.raises(boundary.BoundaryError, match="non-fixed storage"):
            boundary.load_credential_identity(case[1], ROOT)


def _nested_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _nested_objects(child)
    elif isinstance(value, list):
        yield value
        for child in value:
            yield from _nested_objects(child)


def test_review_exploit_direct_nested_extraction_rejected(case):
    request, credential, candidate, _ = case
    build(case)
    payload = json.loads(candidate.read_bytes())
    extracted = payload["reviewed_bindings"]
    assert set(extracted) == boundary.FROZEN_INTEGRATED_AUTHORIZATION_FIELDS - boundary.ACTIVATION_ONLY_FIELDS
    config = boundary._request_config(request, json.loads(credential.read_bytes()), SELECTION, candidate)
    path = candidate.parent / "direct-extraction-not-authority.json"
    path.write_bytes(core._canonical_json_bytes(extracted))
    # All identity/binding checks pass; missing actual authority blocks admission.
    for active in (True, False):
        with pytest.raises(core.AuthorizationError, match="authorization metadata is invalid"):
            integrated.load_and_validate_authorization(path, config=config, selection=SELECTION,
                                                      now=NOW, require_active_window=active)
    assert all(field not in extracted for field in boundary.ACTIVATION_ONLY_FIELDS)


def test_every_recursive_object_is_incomplete_and_rejected_by_both_loaders(case):
    request, credential, candidate, _ = case
    build(case)
    payload = json.loads(candidate.read_bytes())
    config = boundary._request_config(request, json.loads(credential.read_bytes()), SELECTION, candidate)
    offline_config = replace(config, runtime_mode=core.RUNTIME_MODE)
    nodes = list(_nested_objects(payload))
    assert len(nodes) > 20  # Includes configuration, components, provenance, bindings and lists.
    for index, node in enumerate(nodes):
        if isinstance(node, dict):
            assert not set(node) & boundary.ACTIVATION_ONLY_FIELDS
            assert not boundary.FROZEN_CORE_AUTHORIZATION_FIELDS <= set(node)
            assert not boundary.FROZEN_INTEGRATED_AUTHORIZATION_FIELDS <= set(node)
        path = candidate.parent / ("nested-extraction-" + str(index) + ".json")
        raw = core._canonical_json_bytes(node)
        assert SECRET.encode() not in raw
        path.write_bytes(raw)
        for loader, settings in ((integrated.load_and_validate_authorization, config),
                                 (core.load_and_validate_authorization, offline_config)):
            with pytest.raises(core.AuthorizationError):
                loader(path, config=settings, selection=SELECTION, now=NOW,
                       require_active_window=False)


@pytest.mark.parametrize("field", sorted(boundary.ACTIVATION_ONLY_FIELDS))
@pytest.mark.parametrize("nested", [False, True])
def test_activation_fields_forbidden_even_null_and_deeply_nested(case, field, nested):
    request, credential, candidate, _ = case
    build(case)
    payload = json.loads(candidate.read_bytes())
    if nested:
        payload["configuration"]["hidden"] = [{"more": {field: None}}]
    else:
        payload[field] = None
    candidate.write_bytes(core._canonical_json_bytes(payload))
    with pytest.raises(boundary.BoundaryError, match="activation-only authority"):
        boundary.validate_candidate(request=request, credential_artifact=credential,
                                    candidate=candidate, repository_root=ROOT)


def test_completeness_field_sets_match_exact_frozen_loader_sources():
    for module, required in ((core, boundary.FROZEN_CORE_AUTHORIZATION_FIELDS),
                             (integrated, boundary.FROZEN_INTEGRATED_AUTHORIZATION_FIELDS)):
        tree = ast.parse(Path(module.__file__).read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "load_and_validate_authorization")
        observed = set()
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "payload" and isinstance(node.args[0], ast.Constant)):
                    observed.add(node.args[0].value)
                if node.func.attr == "_required_text" and isinstance(node.args[1], ast.Constant):
                    observed.add(node.args[1].value)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "_required_text" and isinstance(node.args[1], ast.Constant):
                    observed.add(node.args[1].value)
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "expected"
                    for t in node.targets) and isinstance(node.value, ast.Dict)):
                observed.update(k.value for k in node.value.keys)
        assert required == observed


def test_establishment_cli_reports_public_path_and_artifact_hash(case, monkeypatch, capsys):
    _, _, candidate, _ = case
    output = candidate.parent / "cli-credential-test-only.json"
    monkeypatch.setattr(getpass, "getpass", lambda prompt: SECRET)
    assert boundary.main(["establish-credential", "--label", LABEL,
        "--verification-reference", "TEST_ONLY_ACCOUNT", "--output", str(output),
        "--repository-root", str(ROOT)]) == 0
    captured = capsys.readouterr()
    assert "Artifact path: " + str(output) in captured.out
    assert "Artifact SHA-256: " + core._digest(output.read_bytes()) in captured.out
    assert SECRET not in captured.out + captured.err
