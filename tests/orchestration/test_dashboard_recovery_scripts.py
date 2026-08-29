from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import threading

import pytest


REPOSITORY_ROOT = Path(__file__).parents[2]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
LAUNCHER_PATH = SCRIPTS_DIRECTORY / "run_dashboard.ps1"
HEALTH_PATH = SCRIPTS_DIRECTORY / "dashboard_health.ps1"
HEALTH_CHECK_PATH = SCRIPTS_DIRECTORY / "check_dashboard_health.ps1"
REGISTRATION_PATH = SCRIPTS_DIRECTORY / "register_dashboard_task.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_launcher_owns_streamlit_with_a_kill_on_close_job_object() -> None:
    launcher = _read(LAUNCHER_PATH)

    assert "Start-Process" in launcher
    assert "-PassThru" in launcher
    assert "CreateKillOnCloseJob" in launcher
    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in launcher
    assert "AssignProcessToJobObject" in launcher
    assert "CloseHandle" in launcher
    assert "finally" in launcher
    assert 'Stop-OwnedProcessTree -OwnedProcessId $childProcess.Id' in launcher


def test_job_object_closure_terminates_its_exact_child() -> None:
    launcher_path = str(LAUNCHER_PATH).replace("'", "''")
    command = rf"""
$launcher = Get-Content -LiteralPath '{launcher_path}' -Raw
$match = [regex]::Match(
    $launcher,
    '(?s)Add-Type -TypeDefinition @"\r?\n(.*?)\r?\n"@'
)
if (-not $match.Success) {{ throw 'Job Object type definition was not found.' }}
Add-Type -TypeDefinition $match.Groups[1].Value
$job = [SportsModel.DashboardJobObject]::CreateKillOnCloseJob()
$child = Start-Process `
    -FilePath (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') `
    -ArgumentList @('-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 30') `
    -WindowStyle Hidden `
    -PassThru
try {{
    if (-not [SportsModel.DashboardJobObject]::AssignProcessToJobObject(
        $job,
        $child.Handle
    )) {{ throw 'Unable to assign test child to Job Object.' }}
    [void][SportsModel.DashboardJobObject]::CloseHandle($job)
    $job = [IntPtr]::Zero
    if (-not $child.WaitForExit(5000)) {{
        throw 'Closing the Job Object did not terminate its child.'
    }}
}}
finally {{
    if ($job -ne [IntPtr]::Zero) {{
        [void][SportsModel.DashboardJobObject]::CloseHandle($job)
    }}
    if (-not $child.HasExited) {{
        Stop-Process -Id $child.Id -Force
    }}
}}
"""

    result = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_launcher_never_uses_a_broad_python_kill() -> None:
    launcher = _read(LAUNCHER_PATH)

    assert "Get-Process python" not in launcher
    assert "Get-Process -Name python" not in launcher
    assert "Stop-Process -Name" not in launcher
    assert "taskkill.exe /IM" not in launcher
    assert '@("/PID", $OwnedProcessId, "/T", "/F")' in launcher


def test_launcher_only_cleans_up_a_proven_dashboard_listener() -> None:
    launcher = _read(LAUNCHER_PATH)
    identity_check = launcher.index("function Test-KnownDashboardListener")
    existing_listener_check = launcher.index("$existingListeners")
    owned_cleanup = launcher.index(
        "Stop-OwnedProcessTree -OwnedProcessId $listener.OwningProcess"
    )

    identity_contract = launcher[identity_check:existing_listener_check]
    assert 'python.exe' in identity_contract
    assert "*-m streamlit*" in identity_contract
    assert "*$ExpectedAppPath*" in identity_contract
    assert "*--server.port=$ExpectedPort*" in identity_contract
    assert "Refusing to terminate it" in launcher[
        existing_listener_check:owned_cleanup
    ]


def test_launcher_watchdog_converts_exit_or_http_failure_to_task_failure() -> None:
    launcher = _read(LAUNCHER_PATH)

    assert "Get-SportsModelDashboardHealth" in launcher
    assert "AddSeconds(60)" in launcher
    assert "$consecutiveHealthFailures -ge 3" in launcher
    assert "CloseHandle($jobHandle)" in launcher
    assert "$childExitCode -eq 0) { 1 } else { $childExitCode }" in launcher
    assert "exit $wrapperExitCode" in launcher


def test_registration_defines_one_idempotent_dashboard_task() -> None:
    registration = _read(REGISTRATION_PATH)

    assert '$taskName = "SportsModel - Dashboard"' in registration
    assert registration.count("Register-ScheduledTask") == 1
    assert "-TaskName $taskName" in registration
    assert "-InputObject $task" in registration
    assert "-Force" in registration
    assert "Unregister-ScheduledTask" not in registration
    assert "Get-ScheduledTask" not in registration
    assert "SportsModel - MLB" not in registration
    assert "SportsModel - NFL" not in registration


def test_registration_defines_boot_logon_and_s4u_contract() -> None:
    registration = _read(REGISTRATION_PATH)

    assert "[ValidateRange(60, 90)]" in registration
    assert "[int]$StartupDelaySeconds = 75" in registration
    assert "New-ScheduledTaskTrigger -AtStartup" in registration
    assert '$startupTrigger.Delay = "PT${StartupDelaySeconds}S"' in registration
    assert "New-ScheduledTaskTrigger" in registration
    assert "-AtLogOn" in registration
    assert "-User $UserId" in registration
    assert "-LogonType S4U" in registration
    assert "-RunLevel Limited" in registration


def test_registration_defines_action_and_recovery_settings() -> None:
    registration = _read(REGISTRATION_PATH)

    assert '"run_dashboard.ps1"' in registration
    assert "-WorkingDirectory $repositoryRoot" in registration
    assert '"-Port 8501"' not in registration
    assert "-Port 8501" in registration
    assert "-MultipleInstances IgnoreNew" in registration
    assert "-RestartCount 3" in registration
    assert "-RestartInterval (New-TimeSpan -Minutes 1)" in registration
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in registration
    assert "-StartWhenAvailable" in registration
    assert "-AllowStartIfOnBatteries" in registration
    assert "-DontStopIfGoingOnBatteries" in registration


def test_health_contract_requires_loopback_tcp_and_http_200() -> None:
    health = _read(HEALTH_PATH)

    assert 'ConnectAsync("127.0.0.1", $Port)' in health
    assert '"http://127.0.0.1:$Port/_stcore/health"' in health
    assert "$listenerPresent" in health
    assert "$httpStatusCode -eq 200" in health


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - standard-library callback name
        if self.path == "/_stcore/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def _powershell() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("Windows PowerShell is required for dashboard script tests.")
    return executable


def _run_health_check(port: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(HEALTH_CHECK_PATH),
            "-Port",
            str(port),
            "-TimeoutSeconds",
            "2",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_health_check_succeeds_for_loopback_http_200() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        result = _run_health_check(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert "Listener: True" in result.stdout
    assert "HTTP:     200" in result.stdout
    assert "Dashboard healthy" in result.stdout


def test_health_check_fails_when_loopback_listener_is_absent() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        unused_port = probe.getsockname()[1]

    result = _run_health_check(unused_port)

    assert result.returncode != 0
    assert "Listener: False" in result.stdout
    assert "Dashboard healthy" not in result.stdout
