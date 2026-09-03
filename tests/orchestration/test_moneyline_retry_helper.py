from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


REPOSITORY_ROOT = Path(__file__).parents[2]
RETRY_HELPER = REPOSITORY_ROOT / "scripts" / "invoke_moneyline_retry.ps1"


def _run_harness(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for retry-helper tests.")

    harness = tmp_path / "retry-harness.ps1"
    harness.write_text(
        f'. "{RETRY_HELPER}"\n'
        "$ErrorActionPreference = 'Stop'\n"
        + body,
        encoding="utf-8",
    )
    return subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def test_transient_failure_then_success_rechecks_preflight(
    tmp_path: Path,
) -> None:
    result = _run_harness(
        tmp_path,
        """
$script:Preflights = 0
$script:Operations = 0
$Preflight = {
    $script:Preflights++
    [pscustomobject]@{
        LatestValidStartTime = [DateTimeOffset]'2026-09-02T09:00:00-07:00'
    }
}
$Operation = {
    $script:Operations++
    if ($script:Operations -eq 1) { return 75 }
    return 0
}
Invoke-MoneylineOperationWithRetry `
    -OperationName 'Pregame' `
    -Preflight $Preflight `
    -Operation $Operation `
    -MaxAttempts 4 `
    -RetryDelaySeconds 900 `
    -NowProvider { [DateTimeOffset]'2026-09-02T08:00:00-07:00' } `
    -Sleeper { param([int]$Seconds) } `
    -Logger { param([string]$Message) Write-Output $Message }
Write-Output "COUNTS=$script:Preflights,$script:Operations"
""",
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Classification: transient" in output
    assert "COUNTS=2,2" in output


def test_transient_readiness_failure_then_success(
    tmp_path: Path,
) -> None:
    result = _run_harness(
        tmp_path,
        """
$script:Preflights = 0
$script:Operations = 0
$Preflight = {
    $script:Preflights++
    if ($script:Preflights -eq 1) {
        throw (New-MoneylineRetryableException -Message 'database unavailable')
    }
    [pscustomobject]@{
        LatestValidStartTime = [DateTimeOffset]'2026-09-02T09:00:00-07:00'
    }
}
$Operation = { $script:Operations++; return 0 }
Invoke-MoneylineOperationWithRetry `
    -OperationName 'Pregame' `
    -Preflight $Preflight `
    -Operation $Operation `
    -RetryDelaySeconds 0 `
    -Sleeper { param([int]$Seconds) } `
    -Logger { param([string]$Message) Write-Output $Message }
Write-Output "COUNTS=$script:Preflights,$script:Operations"
""",
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "database unavailable" in output
    assert "COUNTS=2,1" in output


@pytest.mark.parametrize(
    "message",
    [
        "migration 029 absent",
        "scheduled execution expired",
    ],
)
def test_permanent_preflight_failure_is_not_retried(
    tmp_path: Path,
    message: str,
) -> None:
    result = _run_harness(
        tmp_path,
        f"""
$script:Preflights = 0
$script:Operations = 0
$Preflight = {{ $script:Preflights++; throw '{message}' }}
$Operation = {{ $script:Operations++; return 0 }}
try {{
    Invoke-MoneylineOperationWithRetry `
        -OperationName 'Pregame' `
        -Preflight $Preflight `
        -Operation $Operation `
        -RetryDelaySeconds 0 `
        -Sleeper {{ param([int]$Seconds) }} `
        -Logger {{ param([string]$Message) Write-Output $Message }}
}}
catch {{
    Write-Output $_.Exception.Message
    Write-Output "COUNTS=$script:Preflights,$script:Operations"
    exit 1
}}
""",
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Classification: permanent/nonretryable" in output
    assert "COUNTS=1,0" in output


@pytest.mark.parametrize("operation_name", ["Pregame", "Morning snapshot"])
def test_retry_that_would_cross_pit_deadline_is_refused(
    tmp_path: Path,
    operation_name: str,
) -> None:
    result = _run_harness(
        tmp_path,
        f"""
$script:Preflights = 0
$script:Operations = 0
$Preflight = {{
    $script:Preflights++
    [pscustomobject]@{{
        LatestValidStartTime = [DateTimeOffset]'2026-09-02T08:10:00-07:00'
    }}
}}
$Operation = {{ $script:Operations++; return 75 }}
try {{
    Invoke-MoneylineOperationWithRetry `
        -OperationName '{operation_name}' `
        -Preflight $Preflight `
        -Operation $Operation `
        -RetryDelaySeconds 900 `
        -NowProvider {{ [DateTimeOffset]'2026-09-02T08:00:00-07:00' }} `
        -Sleeper {{ param([int]$Seconds) }} `
        -Logger {{ param([string]$Message) Write-Output $Message }}
}}
catch {{
    Write-Output $_.Exception.Message
    Write-Output "COUNTS=$script:Preflights,$script:Operations"
    exit 1
}}
""",
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "would reach or cross the PIT deadline" in output
    assert "COUNTS=1,1" in output


def test_successful_first_attempt_does_not_retry(tmp_path: Path) -> None:
    result = _run_harness(
        tmp_path,
        """
$script:Preflights = 0
$script:Operations = 0
$Preflight = { $script:Preflights++ }
$Operation = { $script:Operations++; return 0 }
Invoke-MoneylineOperationWithRetry `
    -OperationName 'Snapshot' `
    -Preflight $Preflight `
    -Operation $Operation `
    -Sleeper { param([int]$Seconds) }
Write-Output "COUNTS=$script:Preflights,$script:Operations"
""",
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "COUNTS=1,1" in output


def test_exhausted_transient_failures_exit_cleanly(
    tmp_path: Path,
) -> None:
    result = _run_harness(
        tmp_path,
        """
$script:Preflights = 0
$script:Operations = 0
$Preflight = { $script:Preflights++ }
$Operation = { $script:Operations++; return 75 }
try {
    Invoke-MoneylineOperationWithRetry `
        -OperationName 'Snapshot' `
        -Preflight $Preflight `
        -Operation $Operation `
        -MaxAttempts 2 `
        -RetryDelaySeconds 0 `
        -Sleeper { param([int]$Seconds) }
}
catch {
    Write-Output $_.Exception.Message
    Write-Output "COUNTS=$script:Preflights,$script:Operations"
    exit 1
}
""",
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "exhausted 2 attempts" in output
    assert "COUNTS=2,2" in output
