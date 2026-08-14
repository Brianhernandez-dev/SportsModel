from pathlib import Path


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
