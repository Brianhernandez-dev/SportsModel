from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest


REPOSITORY_ROOT = Path(__file__).parents[2]
WRAPPER_PATH = REPOSITORY_ROOT / "scripts" / "run_native_postgresql_backup.ps1"
READINESS_PATH = REPOSITORY_ROOT / "scripts" / "wait_for_sportsmodel_database.ps1"


def _powershell() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("Windows PowerShell is required for backup-wrapper tests.")
    return executable


def _set_safe_directory_acl(*directories: Path) -> None:
    script = r'''& {
$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$inheritance = (
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
    [Security.AccessControl.InheritanceFlags]::ObjectInherit
)
$propagation = [Security.AccessControl.PropagationFlags]::None
$allow = [Security.AccessControl.AccessControlType]::Allow
foreach ($path in $args) {
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($identity.User)
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $identity.User,
        [Security.AccessControl.FileSystemRights]::Modify,
        $inheritance,
        $propagation,
        $allow
    ))
    foreach ($sid in @("S-1-5-18", "S-1-5-32-544")) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]$sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            $propagation,
            $allow
        ))
    }
    [IO.Directory]::SetAccessControl($path, $acl)
}
}'''
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-Command", script, *map(str, directories)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _add_unsafe_directory_acl(directory: Path) -> None:
    script = r'''& {
param([string]$Path)
$ErrorActionPreference = "Stop"
$acl = [IO.Directory]::GetAccessControl($Path)
$rule = [Security.AccessControl.FileSystemAccessRule]::new(
    [Security.Principal.SecurityIdentifier]"S-1-1-0",
    [Security.AccessControl.FileSystemRights]::ReadAndExecute,
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)
$acl.AddAccessRule($rule)
[IO.Directory]::SetAccessControl($Path, $acl)
}'''
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-Command", script, str(directory)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _add_unsafe_file_acl(path: Path) -> None:
    script = r'''& {
param([string]$Path)
$ErrorActionPreference = "Stop"
$acl = [IO.File]::GetAccessControl($Path)
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    [Security.Principal.SecurityIdentifier]"S-1-1-0",
    [Security.AccessControl.FileSystemRights]::Read,
    [Security.AccessControl.AccessControlType]::Allow
))
[IO.File]::SetAccessControl($Path, $acl)
}'''
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-Command", script, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _grant_current_identity_full_control(directory: Path) -> None:
    script = r'''& {
param([string]$Path)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$acl = [IO.Directory]::GetAccessControl($Path)
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $identity.User,
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
))
[IO.Directory]::SetAccessControl($Path, $acl)
}'''
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-Command", script, str(directory)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _set_protected_runtime_acl(runtime: Path, credential: Path) -> None:
    script = r'''& {
param([string]$Runtime, [string]$Credential)
$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$admins = [Security.Principal.SecurityIdentifier]"S-1-5-32-544"
$system = [Security.Principal.SecurityIdentifier]"S-1-5-18"
$inheritance = (
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
    [Security.AccessControl.InheritanceFlags]::ObjectInherit
)
$none = [Security.AccessControl.PropagationFlags]::None
$allow = [Security.AccessControl.AccessControlType]::Allow
$runtimeAcl = [Security.AccessControl.DirectorySecurity]::new()
$runtimeAcl.SetOwner($admins)
$runtimeAcl.SetAccessRuleProtection($true, $false)
$runtimeAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $identity.User,
    [Security.AccessControl.FileSystemRights]::ReadAndExecute,
    $inheritance,
    $none,
    $allow
))
foreach ($sid in @($system, $admins)) {
    $runtimeAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $sid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        $none,
        $allow
    ))
}
[IO.Directory]::SetAccessControl($Runtime, $runtimeAcl)
$configAcl = [Security.AccessControl.DirectorySecurity]::new()
$configAcl.SetOwner($admins)
$configAcl.SetAccessRuleProtection($true, $false)
$configAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $identity.User,
    [Security.AccessControl.FileSystemRights]::ReadAndExecute,
    $inheritance,
    $none,
    $allow
))
foreach ($sid in @($system, $admins)) {
    $configAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $sid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        $none,
        $allow
    ))
}
[IO.Directory]::SetAccessControl((Join-Path $Runtime "config"), $configAcl)
foreach ($file in Get-ChildItem -LiteralPath $Runtime -File) {
    $fileAcl = [IO.File]::GetAccessControl($file.FullName)
    $fileAcl.SetOwner($admins)
    [IO.File]::SetAccessControl($file.FullName, $fileAcl)
}

$credentialAcl = [Security.AccessControl.FileSecurity]::new()
$credentialAcl.SetOwner($admins)
$credentialAcl.SetAccessRuleProtection($true, $false)
$credentialAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $identity.User,
    [Security.AccessControl.FileSystemRights]::Read,
    $allow
))
foreach ($sid in @($system, $admins)) {
    $credentialAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $sid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $allow
    ))
}
[IO.File]::SetAccessControl($Credential, $credentialAcl)
}'''
    result = subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-Command",
            script,
            str(runtime),
            str(credential),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and "unauthorized" in result.stderr.lower():
        pytest.skip("Protected-runtime ACL integration requires elevation.")
    assert result.returncode == 0, result.stderr


def _write_fake_engine(directory: Path) -> Path:
    path = directory / "invoke_native_postgresql_backup_restore_acceptance.ps1"
    path.write_text(
        r'''[CmdletBinding()]
param(
    [string]$Action,
    [string]$EnvironmentPath,
    [string]$BackupPath,
    [string]$ManifestPath,
    [switch]$ApproveProductionBackup
)
$ErrorActionPreference = "Stop"
Add-Content -LiteralPath $env:FAKE_ACCEPTANCE_TRACE -Value (
    "$Action|$BackupPath|$ManifestPath|approved=" +
    $ApproveProductionBackup.IsPresent
)
Write-Output "provider-password=must-not-reach-wrapper-log"
if ($env:FAKE_FAIL_ACTION -eq $Action) {
    Write-Error "failure-with-secret=must-not-reach-wrapper-log"
    exit 9
}
if ($Action -eq "Backup") {
    if ($env:FAKE_BACKUP_DELAY_MS) {
        Start-Sleep -Milliseconds ([int]$env:FAKE_BACKUP_DELAY_MS)
    }
    [IO.File]::WriteAllBytes($BackupPath, [byte[]](1, 2, 3, 4))
    Set-Content -LiteralPath $ManifestPath -Value '{"fake":true}'
    exit 0
}
if ($Action -eq "VerifyBackup") {
    if (
        -not (Test-Path -LiteralPath $BackupPath -PathType Leaf) `
        -or -not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)
    ) {
        exit 8
    }
    exit 0
}
exit 7
''',
        encoding="utf-8",
    )
    return path


def _fixture_paths(tmp_path: Path) -> dict[str, Path]:
    backup_directory = tmp_path / "backups"
    log_directory = tmp_path / "logs"
    runtime_directory = tmp_path / "runtime"
    backup_directory.mkdir()
    log_directory.mkdir()
    runtime_directory.mkdir()
    _set_safe_directory_acl(backup_directory, log_directory)
    config_directory = runtime_directory / "config"
    config_directory.mkdir()
    environment_path = config_directory / "backup.env"
    environment_path.write_text(
        "POSTGRES_HOST=localhost\n"
        "POSTGRES_PORT=5432\n"
        "POSTGRES_DB=sportsmodel\n"
        "POSTGRES_USER=fixture\n"
        "POSTGRES_PASSWORD=fixture-secret\n",
        encoding="utf-8",
    )
    trace_path = tmp_path / "trace.log"
    wrapper_path = runtime_directory / WRAPPER_PATH.name
    shutil.copyfile(WRAPPER_PATH, wrapper_path)
    acceptance_tool = _write_fake_engine(runtime_directory)
    shutil.copyfile(READINESS_PATH, runtime_directory / READINESS_PATH.name)
    runtime_files = [wrapper_path, acceptance_tool, runtime_directory / READINESS_PATH.name]
    manifest = {
        "FormatVersion": 1,
        "Files": [
            {
                "Name": path.name,
                "Sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            }
            for path in runtime_files
        ],
    }
    (runtime_directory / "runtime-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    _set_protected_runtime_acl(runtime_directory, environment_path)
    return {
        "backup_directory": backup_directory,
        "log_directory": log_directory,
        "environment_path": environment_path,
        "trace_path": trace_path,
        "acceptance_tool": acceptance_tool,
        "wrapper_path": wrapper_path,
        "runtime_directory": runtime_directory,
    }


def _arguments(paths: dict[str, Path], utc_now: str) -> list[str]:
    return [
        _powershell(),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(paths["wrapper_path"]),
        "-BackupDirectory",
        str(paths["backup_directory"]),
        "-LogDirectory",
        str(paths["log_directory"]),
        "-EnvironmentPath",
        str(paths["environment_path"]),
        "-AcceptanceToolPath",
        str(paths["acceptance_tool"]),
        "-UtcNow",
        utc_now,
    ]


def _run(
    paths: dict[str, Path],
    utc_now: str = "2026-09-06T08:00:00+00:00",
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_environment = os.environ.copy()
    process_environment["FAKE_ACCEPTANCE_TRACE"] = str(paths["trace_path"])
    if environment:
        process_environment.update(environment)
    return subprocess.run(
        _arguments(paths, utc_now),
        cwd=REPOSITORY_ROOT,
        env=process_environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _pair(directory: Path, stamp: str) -> tuple[Path, Path]:
    backup = directory / f"sportsmodel-native-{stamp}.dump"
    manifest = directory / f"{backup.name}.manifest.json"
    backup.write_bytes(b"old-backup")
    manifest.write_text('{"fake":true}', encoding="utf-8")
    return backup, manifest


def _logs(paths: dict[str, Path]) -> list[Path]:
    return sorted(paths["log_directory"].glob("postgresql_backup_*.log"))


def test_generates_exact_timestamped_name_and_runs_backup_then_verify(
    tmp_path: Path,
) -> None:
    paths = _fixture_paths(tmp_path)

    result = _run(paths, "2026-09-06T08:01:02+00:00")

    assert result.returncode == 0, result.stderr
    backup = paths["backup_directory"] / (
        "sportsmodel-native-20260906t080102z.dump"
    )
    assert backup.is_file()
    assert Path(f"{backup}.manifest.json").is_file()
    actions = paths["trace_path"].read_text(encoding="utf-8").splitlines()
    assert actions[0].startswith("Backup|")
    assert actions[0].endswith("|approved=True")
    assert actions[1].startswith("VerifyBackup|")
    assert actions[1].endswith("|approved=False")
    assert backup.name in _logs(paths)[0].read_text(encoding="utf-8-sig")


def test_verification_failure_prevents_retention(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    old_pairs = [
        _pair(
            paths["backup_directory"],
            (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index))
            .strftime("%Y%m%dt%H%M%Sz")
            .lower(),
        )
        for index in range(31)
    ]

    result = _run(
        paths,
        environment={"FAKE_FAIL_ACTION": "VerifyBackup"},
    )

    assert result.returncode != 0
    assert all(backup.exists() and manifest.exists() for backup, manifest in old_pairs)
    log_text = _logs(paths)[0].read_text(encoding="utf-8-sig")
    assert "Stage=verification" in log_text
    assert "Retention completed" not in log_text


def test_retention_keeps_newest_30_verified_pairs_and_unrelated_files(
    tmp_path: Path,
) -> None:
    paths = _fixture_paths(tmp_path)
    old_pairs = [
        _pair(
            paths["backup_directory"],
            (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index))
            .strftime("%Y%m%dt%H%M%Sz")
            .lower(),
        )
        for index in range(30)
    ]
    unrelated = paths["backup_directory"] / "operator-notes.txt"
    unrelated.write_text("preserve", encoding="utf-8")
    similar = paths["backup_directory"] / "unrelated-native-backup.dump"
    similar.write_bytes(b"preserve")

    result = _run(paths)

    assert result.returncode == 0, result.stderr
    exact_dumps = list(
        paths["backup_directory"].glob("sportsmodel-native-*.dump")
    )
    assert len(exact_dumps) == 30
    assert not old_pairs[0][0].exists()
    assert not old_pairs[0][1].exists()
    assert all(
        backup.exists() and manifest.exists()
        for backup, manifest in old_pairs[1:]
    )
    assert unrelated.read_text(encoding="utf-8") == "preserve"
    assert similar.read_bytes() == b"preserve"


def test_retention_always_preserves_current_backup_when_older_than_future_pairs(
    tmp_path: Path,
) -> None:
    paths = _fixture_paths(tmp_path)
    future_pairs = [
        _pair(
            paths["backup_directory"],
            (datetime(2026, 9, 7, tzinfo=timezone.utc) + timedelta(days=index))
            .strftime("%Y%m%dt%H%M%Sz")
            .lower(),
        )
        for index in range(30)
    ]

    result = _run(paths, "2026-09-06T08:00:00+00:00")

    assert result.returncode == 0, result.stderr
    current = paths["backup_directory"] / (
        "sportsmodel-native-20260906t080000z.dump"
    )
    assert current.exists()
    assert Path(f"{current}.manifest.json").exists()
    assert len(list(paths["backup_directory"].glob("sportsmodel-native-*.dump"))) == 30
    assert not future_pairs[0][0].exists()
    assert not future_pairs[0][1].exists()


@pytest.mark.parametrize("artifact_kind", ["unpaired", "malformed"])
def test_malformed_or_unpaired_managed_artifact_refuses_all_retention_deletion(
    tmp_path: Path,
    artifact_kind: str,
) -> None:
    paths = _fixture_paths(tmp_path)
    old_pairs = [
        _pair(
            paths["backup_directory"],
            (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index))
            .strftime("%Y%m%dt%H%M%Sz")
            .lower(),
        )
        for index in range(30)
    ]
    if artifact_kind == "unpaired":
        problem = paths["backup_directory"] / (
            "sportsmodel-native-20251231t010000z.dump"
        )
    else:
        problem = paths["backup_directory"] / "sportsmodel-native-invalid.dump"
    problem.write_bytes(b"must-not-delete")

    result = _run(paths)

    assert result.returncode != 0
    assert problem.read_bytes() == b"must-not-delete"
    assert all(backup.exists() and manifest.exists() for backup, manifest in old_pairs)
    assert "Stage=retention" in _logs(paths)[0].read_text(encoding="utf-8-sig")


def test_existing_timestamped_artifact_is_never_overwritten(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    backup = paths["backup_directory"] / (
        "sportsmodel-native-20260906t080000z.dump"
    )
    backup.write_bytes(b"original")

    result = _run(paths)

    assert result.returncode != 0
    assert backup.read_bytes() == b"original"
    assert not paths["trace_path"].exists()
    assert "Stage=artifact-preflight" in _logs(paths)[0].read_text(
        encoding="utf-8-sig"
    )


def test_backup_engine_failure_propagates_nonzero_without_retention(
    tmp_path: Path,
) -> None:
    paths = _fixture_paths(tmp_path)

    result = _run(paths, environment={"FAKE_FAIL_ACTION": "Backup"})

    assert result.returncode != 0
    actions = paths["trace_path"].read_text(encoding="utf-8").splitlines()
    assert len(actions) == 1
    assert actions[0].startswith("Backup|")
    log_text = _logs(paths)[0].read_text(encoding="utf-8-sig")
    assert "Stage=backup" in log_text
    assert "Retention completed" not in log_text


def test_engine_output_and_exception_details_are_not_persisted(
    tmp_path: Path,
) -> None:
    paths = _fixture_paths(tmp_path)

    result = _run(paths, environment={"FAKE_FAIL_ACTION": "Backup"})

    assert result.returncode != 0
    log_text = _logs(paths)[0].read_text(encoding="utf-8-sig").lower()
    assert "password" not in log_text
    assert "secret" not in log_text
    assert "connection" not in log_text
    assert "stage=backup" in log_text


def test_overlapping_wrapper_with_alternate_log_directory_is_refused(
    tmp_path: Path,
) -> None:
    paths = _fixture_paths(tmp_path)
    first_environment = os.environ.copy()
    first_environment["FAKE_ACCEPTANCE_TRACE"] = str(paths["trace_path"])
    first_environment["FAKE_BACKUP_DELAY_MS"] = "2500"
    first = subprocess.Popen(
        _arguments(paths, "2026-09-06T08:00:00+00:00"),
        cwd=REPOSITORY_ROOT,
        env=first_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lock_path = paths["backup_directory"] / "run_native_postgresql_backup.lock"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if lock_path.exists() and paths["trace_path"].exists():
            break
        time.sleep(0.05)
    else:
        first.kill()
        pytest.fail("First wrapper did not acquire its lock in time.")

    second_paths = dict(paths)
    second_paths["log_directory"] = tmp_path / "alternate-logs"
    second_paths["log_directory"].mkdir()
    _set_safe_directory_acl(second_paths["log_directory"])
    second = _run(second_paths, "2026-09-06T08:00:01+00:00")
    first_stdout, first_stderr = first.communicate(timeout=20)

    assert first.returncode == 0, first_stderr or first_stdout
    assert second.returncode != 0
    assert len(_logs(paths)) == 1
    second_logs = _logs(second_paths)
    assert len(second_logs) == 1
    assert "Stage=overlap-protection" in second_logs[0].read_text(
        encoding="utf-8-sig"
    )
    assert (
        paths["backup_directory"]
        / "sportsmodel-native-20260906t080000z.dump"
    ).exists()
    assert not (
        paths["backup_directory"]
        / "sportsmodel-native-20260906t080001z.dump"
    ).exists()


@pytest.mark.parametrize("unsafe_directory", ["backup_directory", "log_directory"])
def test_unsafe_artifact_directory_acl_is_refused_before_backup(
    tmp_path: Path,
    unsafe_directory: str,
) -> None:
    paths = _fixture_paths(tmp_path)
    _add_unsafe_directory_acl(paths[unsafe_directory])

    result = _run(paths)

    assert result.returncode != 0
    assert "unapproved ACL entry" in result.stderr
    assert not paths["trace_path"].exists()
    assert not list(paths["backup_directory"].glob("sportsmodel-native-*.dump"))


def test_artifact_directory_rejects_permission_management_rights(
    tmp_path: Path,
) -> None:
    paths = _fixture_paths(tmp_path)
    _grant_current_identity_full_control(paths["backup_directory"])

    result = _run(paths)

    assert result.returncode != 0
    assert "permission-management rights" in result.stderr
    assert not paths["trace_path"].exists()


@pytest.mark.parametrize(
    "credential_text",
    [
        (
            "POSTGRES_HOST=localhost\nPOSTGRES_PORT=5432\n"
            "POSTGRES_DB=sportsmodel\nPOSTGRES_USER=fixture\n"
        ),
        (
            "POSTGRES_HOST=localhost\nPOSTGRES_PORT=5432\n"
            "POSTGRES_DB=sportsmodel\nPOSTGRES_USER=fixture\n"
            "POSTGRES_PASSWORD=fixture-secret\nUNEXPECTED=value\n"
        ),
        (
            "POSTGRES_HOST=localhost\nPOSTGRES_PORT=5432\n"
            "POSTGRES_DB=sportsmodel\nPOSTGRES_USER=fixture\n"
            "POSTGRES_PASSWORD=fixture-secret\nPOSTGRES_PASSWORD=duplicate\n"
        ),
    ],
)
def test_invalid_dedicated_credential_file_is_refused_before_backup(
    tmp_path: Path,
    credential_text: str,
) -> None:
    paths = _fixture_paths(tmp_path)
    paths["environment_path"].write_text(credential_text, encoding="utf-8")

    result = _run(paths)

    assert result.returncode != 0
    assert not paths["trace_path"].exists()
    assert not list(paths["backup_directory"].glob("sportsmodel-native-*.dump"))
    assert "fixture-secret" not in result.stdout + result.stderr


def test_runtime_manifest_hash_mismatch_is_refused_before_backup(
    tmp_path: Path,
) -> None:
    paths = _fixture_paths(tmp_path)
    helper = paths["runtime_directory"] / READINESS_PATH.name
    helper.write_text(helper.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

    result = _run(paths)

    assert result.returncode != 0
    assert "hash verification failed" in result.stderr
    assert not paths["trace_path"].exists()


def test_unexpected_protected_config_entry_is_refused_before_backup(
    tmp_path: Path,
) -> None:
    paths = _fixture_paths(tmp_path)
    (paths["runtime_directory"] / "config" / "extra.txt").write_text(
        "unexpected",
        encoding="utf-8",
    )

    result = _run(paths)

    assert result.returncode != 0
    assert "config contains an unexpected entry" in result.stderr
    assert not paths["trace_path"].exists()


@pytest.mark.parametrize("unsafe_path", ["runtime", "config", "credential"])
def test_unsafe_runtime_or_credential_acl_is_refused_before_backup(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    paths = _fixture_paths(tmp_path)
    if unsafe_path == "credential":
        _add_unsafe_file_acl(paths["environment_path"])
    else:
        directory = paths["runtime_directory"]
        if unsafe_path == "config":
            directory = directory / "config"
        _add_unsafe_directory_acl(directory)

    result = _run(paths)

    assert result.returncode != 0
    assert "unapproved ACL entry" in result.stderr
    assert not paths["trace_path"].exists()


def test_runtime_and_credentials_are_not_loaded_from_live_repository() -> None:
    script = WRAPPER_PATH.read_text(encoding="utf-8")

    assert 'Join-Path $RuntimeDirectory "config\\backup.env"' in script
    assert "$RepositoryRoot" not in script
    assert '"wait_for_sportsmodel_database.ps1"' in script
    assert "Assert-ProtectedRuntime" in script
    assert "Assert-ProtectedCredentialFile" in script


def test_wrapper_exposes_only_backup_and_verify_actions() -> None:
    script = WRAPPER_PATH.read_text(encoding="utf-8")

    assert '[ValidateSet("Backup", "VerifyBackup")]' in script
    assert '"-ApproveProductionBackup"' in script
    assert '"CreateRestoreTarget"' not in script
    assert '"Restore"' not in script
    assert '"DropRestoreTarget"' not in script
    assert "Start-Service" not in script
    assert "Stop-Service" not in script
    assert "docker" not in script.lower()
