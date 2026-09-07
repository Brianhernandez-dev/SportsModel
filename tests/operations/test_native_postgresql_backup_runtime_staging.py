from __future__ import annotations

from pathlib import Path
import hashlib
import json
import shutil
import subprocess

import pytest


REPOSITORY_ROOT = Path(__file__).parents[2]
SCRIPT_PATH = (
    REPOSITORY_ROOT
    / "scripts"
    / "stage_native_postgresql_backup_runtime.ps1"
)


def _powershell() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("Windows PowerShell is required for staging tests.")
    return executable


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT_PATH),
            *arguments,
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _set_runtime_parent_acl(parent: Path, *, unsafe_write: bool = False) -> None:
    script = r'''& {
param([string]$Path, [int]$UnsafeWrite)
$ErrorActionPreference = "Stop"
$admins = [Security.Principal.SecurityIdentifier]"S-1-5-32-544"
$system = [Security.Principal.SecurityIdentifier]"S-1-5-18"
$everyone = [Security.Principal.SecurityIdentifier]"S-1-1-0"
$authenticated = [Security.Principal.SecurityIdentifier]"S-1-5-11"
$inheritance = (
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
    [Security.AccessControl.InheritanceFlags]::ObjectInherit
)
$none = [Security.AccessControl.PropagationFlags]::None
$allow = [Security.AccessControl.AccessControlType]::Allow
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($admins)
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $everyone,
    [Security.AccessControl.FileSystemRights]::ReadAndExecute,
    $inheritance,
    $none,
    $allow
))
foreach ($sid in @($system, $admins)) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $sid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        $none,
        $allow
    ))
}
if ($UnsafeWrite -eq 1) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $authenticated,
        [Security.AccessControl.FileSystemRights]::Modify,
        $inheritance,
        $none,
        $allow
    ))
}
[IO.Directory]::SetAccessControl($Path, $acl)
}'''
    result = subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-Command",
            script,
            str(parent),
            "1" if unsafe_write else "0",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _acl_evidence(path: Path) -> dict[str, object]:
    script = r'''& {
param([string]$Path)
$item = Get-Item -LiteralPath $Path -Force
if ($item.PSIsContainer) {
    $acl = [IO.Directory]::GetAccessControl($Path)
} else {
    $acl = [IO.File]::GetAccessControl($Path)
}
[pscustomobject]@{
    Owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    Protected = $acl.AreAccessRulesProtected
    Rules = @($acl.GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    ) | ForEach-Object {
        [pscustomobject]@{
            Sid = $_.IdentityReference.Value
            Rights = [long]$_.FileSystemRights
            Inherited = $_.IsInherited
            Inheritance = [int]$_.InheritanceFlags
            Propagation = [int]$_.PropagationFlags
            Type = $_.AccessControlType.ToString()
        }
    })
} | ConvertTo-Json -Depth 4 -Compress
}'''
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-Command", script, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _set_owner_to_administrators(path: Path) -> None:
    script = r'''& {
param([string]$Path)
$acl = [IO.Directory]::GetAccessControl($Path)
$acl.SetOwner([Security.Principal.SecurityIdentifier]"S-1-5-32-544")
[IO.Directory]::SetAccessControl($Path, $acl)
}'''
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-Command", script, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _assert_protected_acl(path: Path, *, directory: bool) -> None:
    evidence = _acl_evidence(path)
    current_sid_script = (
        "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value"
    )
    current = subprocess.run(
        [_powershell(), "-NoProfile", "-Command", current_sid_script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert current.returncode == 0, current.stderr
    expected = {
        current.stdout.strip(): 1179817,
        "S-1-5-18": 2032127,
        "S-1-5-32-544": 2032127,
    }
    assert evidence["Owner"] == "S-1-5-32-544"
    assert evidence["Protected"] is True
    rules = evidence["Rules"]
    assert isinstance(rules, list)
    assert len(rules) == 3
    assert {rule["Sid"]: rule["Rights"] for rule in rules} == expected
    assert all(rule["Inherited"] is False for rule in rules)
    assert all(rule["Type"] == "Allow" for rule in rules)
    assert all(rule["Inheritance"] == (3 if directory else 0) for rule in rules)
    assert all(rule["Propagation"] == 0 for rule in rules)


def test_default_action_is_non_mutating_plan(tmp_path: Path) -> None:
    target = tmp_path / "runtime"

    result = _run("-RuntimeDirectory", str(target))

    assert result.returncode == 0, result.stderr
    assert "PLAN ONLY" in result.stdout
    assert not target.exists()


def test_stage_requires_exact_explicit_approval(tmp_path: Path) -> None:
    target = tmp_path / "runtime"

    result = _run("-Action", "Stage", "-RuntimeDirectory", str(target))

    assert result.returncode != 0
    assert "-ApproveProtectedRuntimeStage" in result.stdout + result.stderr
    assert not target.exists()


def test_approved_stage_builds_exact_manifested_runtime_without_credential(
    tmp_path: Path,
) -> None:
    grandparent = tmp_path / "safe-grandparent"
    grandparent.mkdir()
    _set_runtime_parent_acl(grandparent)
    parent = grandparent / "safe-parent"
    parent.mkdir()
    _set_owner_to_administrators(parent)
    parent_evidence = _acl_evidence(parent)
    assert parent_evidence["Protected"] is False
    assert any(rule["Inherited"] is True for rule in parent_evidence["Rules"])
    target = parent / "runtime"

    result = _run(
        "-Action",
        "Stage",
        "-RuntimeDirectory",
        str(target),
        "-ApproveProtectedRuntimeStage",
    )

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in target.iterdir()) == [
        "config",
        "invoke_native_postgresql_backup_restore_acceptance.ps1",
        "run_native_postgresql_backup.ps1",
        "runtime-manifest.json",
        "wait_for_sportsmodel_database.ps1",
    ]
    assert not (target / "config" / "backup.env").exists()
    manifest = json.loads((target / "runtime-manifest.json").read_text("utf-8-sig"))
    assert manifest["FormatVersion"] == 1
    assert [entry["Name"] for entry in manifest["Files"]] == [
        "run_native_postgresql_backup.ps1",
        "invoke_native_postgresql_backup_restore_acceptance.ps1",
        "wait_for_sportsmodel_database.ps1",
    ]
    for entry in manifest["Files"]:
        assert entry["Sha256"] == hashlib.sha256(
            (target / entry["Name"]).read_bytes()
        ).hexdigest().upper()
    _assert_protected_acl(target, directory=True)
    _assert_protected_acl(target / "config", directory=True)
    for name in [entry["Name"] for entry in manifest["Files"]]:
        _assert_protected_acl(target / name, directory=False)
    _assert_protected_acl(target / "runtime-manifest.json", directory=False)


def test_stage_refuses_missing_immediate_parent(tmp_path: Path) -> None:
    target = tmp_path / "missing-parent" / "runtime"

    result = _run(
        "-Action",
        "Stage",
        "-RuntimeDirectory",
        str(target),
        "-ApproveProtectedRuntimeStage",
    )

    assert result.returncode != 0
    assert "immediate runtime parent must already exist" in result.stderr
    assert not target.parent.exists()


def test_stage_refuses_parent_with_authenticated_users_modify(
    tmp_path: Path,
) -> None:
    grandparent = tmp_path / "unsafe-grandparent"
    grandparent.mkdir()
    _set_runtime_parent_acl(grandparent, unsafe_write=True)
    parent = grandparent / "unsafe-parent"
    parent.mkdir()
    _set_owner_to_administrators(parent)
    parent_evidence = _acl_evidence(parent)
    assert any(
        rule["Sid"] == "S-1-5-11" and rule["Inherited"] is True
        for rule in parent_evidence["Rules"]
    )
    target = parent / "runtime"

    result = _run(
        "-Action",
        "Stage",
        "-RuntimeDirectory",
        str(target),
        "-ApproveProtectedRuntimeStage",
    )

    assert result.returncode != 0
    assert "grants an unapproved identity" in result.stderr
    assert not target.exists()


def test_trust_boundary_and_file_acl_validation_precede_manifest_hashing() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    stage_start = script.index("# Establish and verify the trust boundary")
    runtime_acl = script.index("[IO.Directory]::SetAccessControl", stage_start)
    copy = script.index("Copy-Item", runtime_acl)
    file_acl = script.index("[IO.File]::SetAccessControl", copy)
    validation = script.index("# Validate every final file ACL", file_acl)
    file_hash = script.index("Get-FileHash", validation)
    manifest_write = script.index("Set-Content -LiteralPath $ManifestPath", file_hash)
    manifest_acl = script.index("[IO.File]::SetAccessControl", manifest_write)

    assert runtime_acl < copy < file_acl < validation < file_hash
    assert file_hash < manifest_write < manifest_acl


def test_staging_closure_and_acl_are_explicit_and_secret_free() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"run_native_postgresql_backup.ps1"' in script
    assert '"invoke_native_postgresql_backup_restore_acceptance.ps1"' in script
    assert '"wait_for_sportsmodel_database.ps1"' in script
    assert '"runtime-manifest.json"' in script
    assert "ReadAndExecute" in script
    assert "SetAccessRuleProtection($true, $false)" in script
    assert "Credential file config\\backup.env is provisioned separately" in script
    assert "POSTGRES_PASSWORD=" not in script
    assert "Register-ScheduledTask" not in script
    assert "Start-Service" not in script
    assert "docker" not in script.lower()
