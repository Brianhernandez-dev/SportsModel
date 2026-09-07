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
    target = tmp_path / "runtime"

    result = _run(
        "-Action",
        "Stage",
        "-RuntimeDirectory",
        str(target),
        "-ApproveProtectedRuntimeStage",
    )

    if result.returncode != 0 and "unauthorized" in result.stderr.lower():
        pytest.skip("Protected-runtime staging integration requires elevation.")
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
