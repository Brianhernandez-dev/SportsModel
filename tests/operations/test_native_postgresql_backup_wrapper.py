from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest


REPOSITORY_ROOT = Path(__file__).parents[2]
WRAPPER_PATH = REPOSITORY_ROOT / "scripts" / "run_native_postgresql_backup.ps1"


def _powershell() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("Windows PowerShell is required for backup-wrapper tests.")
    return executable


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
    tool_directory = tmp_path / "tool"
    backup_directory.mkdir()
    log_directory.mkdir()
    tool_directory.mkdir()
    environment_path = tmp_path / ".env"
    environment_path.write_text("fixture=true\n", encoding="utf-8")
    trace_path = tmp_path / "trace.log"
    acceptance_tool = _write_fake_engine(tool_directory)
    return {
        "backup_directory": backup_directory,
        "log_directory": log_directory,
        "environment_path": environment_path,
        "trace_path": trace_path,
        "acceptance_tool": acceptance_tool,
    }


def _arguments(paths: dict[str, Path], utc_now: str) -> list[str]:
    return [
        _powershell(),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(WRAPPER_PATH),
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


def test_overlapping_wrapper_is_refused_without_touching_first_run(
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
    lock_path = paths["log_directory"] / "run_native_postgresql_backup.lock"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if lock_path.exists() and paths["trace_path"].exists():
            break
        time.sleep(0.05)
    else:
        first.kill()
        pytest.fail("First wrapper did not acquire its lock in time.")

    second = _run(paths, "2026-09-06T08:00:01+00:00")
    first_stdout, first_stderr = first.communicate(timeout=20)

    assert first.returncode == 0, first_stderr or first_stdout
    assert second.returncode != 0
    logs = _logs(paths)
    assert len(logs) == 2
    assert any("Stage=overlap-protection" in path.read_text(encoding="utf-8-sig") for path in logs)
    assert (
        paths["backup_directory"]
        / "sportsmodel-native-20260906t080000z.dump"
    ).exists()
    assert not (
        paths["backup_directory"]
        / "sportsmodel-native-20260906t080001z.dump"
    ).exists()


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
