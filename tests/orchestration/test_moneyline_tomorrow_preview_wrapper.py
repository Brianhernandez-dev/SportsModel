from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


WRAPPER_PATH = (
    Path(__file__).parents[2]
    / "scripts"
    / "run_moneyline_tomorrow_preview.ps1"
)


def _wrapper() -> str:
    return WRAPPER_PATH.read_text(encoding="utf-8-sig")


def test_wrapper_uses_only_authoritative_project_paths() -> None:
    wrapper = _wrapper()

    assert "SportsModelMobile" not in wrapper
    assert '"D:\\SportsModel\\.venv\\Scripts\\python.exe"' in wrapper
    assert '"D:\\SportsModel\\.env"' in wrapper
    assert "$ProjectRoot = Split-Path -Parent $PSScriptRoot" in wrapper
    assert "$env:PYTHONPATH = $SourcePath" in wrapper


def test_wrapper_logging_allows_and_preserves_empty_output_lines() -> None:
    wrapper = _wrapper()
    write_log = wrapper.index("function Write-Log")
    logging_loop = wrapper.index("foreach ($OutputLine in $PreviewOutput)")

    assert "[AllowEmptyString()]" in wrapper[write_log:logging_loop]
    assert 'Write-Log "$OutputLine"' in wrapper[logging_loop:]


def test_wrapper_checks_opening_before_preview_generation() -> None:
    wrapper = _wrapper()
    opening_check = wrapper.index("Get-ScheduledTask -TaskName")
    last_run_check = wrapper.index("$OpeningInfo.LastRunTime.Date")
    result_check = wrapper.index("$OpeningInfo.LastTaskResult")
    preview_call = wrapper.index("$PreviewOutput = & $PythonPath")

    assert opening_check < last_run_check < preview_call
    assert result_check < preview_call
    assert "Start-Sleep -Seconds 30" in wrapper
    assert "Attempt $Attempt/20" in wrapper


def test_wrapper_runs_shared_readiness_before_opening_and_preview() -> None:
    wrapper = _wrapper()
    first_guard = wrapper.index("Assert-MoneylineScheduledExecutionValid")
    readiness = wrapper.index("Wait-SportsModelDatabaseReady")
    opening_check = wrapper.index("Get-ScheduledTask -TaskName")
    second_guard = wrapper.index(
        "Assert-MoneylineScheduledExecutionValid",
        first_guard + 1,
    )
    preview_call = wrapper.index("$PreviewOutput = & $PythonPath")

    assert "$DatabaseReadinessPath" in wrapper
    assert ". $DatabaseReadinessPath" in wrapper
    assert first_guard < readiness < opening_check < second_guard < preview_call


def test_permanent_readiness_rejection_stops_before_opening_and_preview(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for wrapper tests.")

    project_root = tmp_path / "preview-project"
    scripts = project_root / "scripts"
    source = project_root / "src"
    preview_module = source / "sportsmodel" / "predictions"
    scripts.mkdir(parents=True)
    preview_module.mkdir(parents=True)

    provider_marker = tmp_path / "preview-provider-called.txt"
    fake_python = project_root / "fake-python.cmd"
    environment_path = project_root / ".env"
    fake_python.write_text(
        "@echo off\r\n"
        ">\"%PREVIEW_PROVIDER_MARKER%\" echo provider-called\r\n"
        "exit /b 0\r\n",
        encoding="ascii",
    )
    environment_path.write_text("TEST_ONLY=1\n", encoding="ascii")
    (scripts / "preview_mlb_moneyline.py").write_text(
        "# Provider path must not be reached.\n",
        encoding="ascii",
    )
    (preview_module / "moneyline_preview_cli.py").write_text(
        "# Required module placeholder.\n",
        encoding="ascii",
    )
    (scripts / "assert_moneyline_scheduled_execution.ps1").write_text(
        "function Assert-MoneylineScheduledExecutionValid {\n"
        "    param(\n"
        "        [string]$PythonPath,\n"
        "        [string]$SourcePath,\n"
        "        [string]$TaskIdentity,\n"
        "        [scriptblock]$Logger\n"
        "    )\n"
        "}\n",
        encoding="ascii",
    )
    (scripts / "wait_for_sportsmodel_database.ps1").write_text(
        "function Wait-SportsModelDatabaseReady {\n"
        "    param(\n"
        "        [string]$PythonPath,\n"
        "        [string]$SourcePath,\n"
        "        [int]$TimeoutSeconds,\n"
        "        [int]$PollSeconds,\n"
        "        [scriptblock]$Logger\n"
        "    )\n"
        "    throw 'Database readiness failed permanently: migration 029 absent.'\n"
        "}\n",
        encoding="ascii",
    )

    test_wrapper = _wrapper().replace(
        '$PythonPath = "D:\\SportsModel\\.venv\\Scripts\\python.exe"',
        f'$PythonPath = "{fake_python}"',
    ).replace(
        '$EnvironmentPath = "D:\\SportsModel\\.env"',
        f'$EnvironmentPath = "{environment_path}"',
    )
    wrapper_path = scripts / "run_moneyline_tomorrow_preview.ps1"
    wrapper_path.write_text(test_wrapper, encoding="utf-8-sig")

    environment = os.environ.copy()
    environment["PREVIEW_PROVIDER_MARKER"] = str(provider_marker)
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper_path),
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "migration 029 absent" in output
    assert "Checking opening snapshot task" not in output
    assert not provider_marker.exists()


def test_dry_run_exits_before_scheduler_and_generation() -> None:
    wrapper = _wrapper()
    dry_run = wrapper.index("if ($DryRun)")
    dry_run_exit = wrapper.index("exit 0", dry_run)
    scheduler_check = wrapper.index("Get-ScheduledTask -TaskName")
    preview_call = wrapper.index("$PreviewOutput = & $PythonPath")

    assert dry_run < dry_run_exit < scheduler_check < preview_call
    assert "$PreviewScriptPath --help" in wrapper[dry_run:dry_run_exit]
    assert "print(m.__file__)" in wrapper[dry_run:dry_run_exit]


def test_wrapper_passes_same_pacific_target_date_and_propagates_failure() -> None:
    wrapper = _wrapper()
    preview_call = wrapper.index("$PreviewOutput = & $PythonPath")

    assert 'FindSystemTimeZoneById(\n    "Pacific Standard Time"' in wrapper
    assert "--target-date $TargetDate" in wrapper[preview_call:]
    assert "$PreviewExitCode = $LASTEXITCODE" in wrapper[preview_call:]
    assert "if ($PreviewExitCode -ne 0)" in wrapper[preview_call:]
    assert "exit 1" in wrapper[preview_call:]
