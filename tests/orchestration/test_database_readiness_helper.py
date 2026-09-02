from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

import psycopg2
import pytest

from sportsmodel.database.readiness_probe import (
    MINIMUM_COMPATIBLE_PRODUCTION_MIGRATION,
    PERMANENT_EXIT_CODE,
    READY_EXIT_CODE,
    TRANSIENT_EXIT_CODE,
    check_database_readiness,
    is_loopback_host,
)


REPOSITORY_ROOT = Path(__file__).parents[2]
HELPER_PATH = (
    REPOSITORY_ROOT
    / "scripts"
    / "wait_for_sportsmodel_database.ps1"
)


def _powershell() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("Windows PowerShell is required for readiness tests.")
    return executable


def _write_fake_python(tmp_path: Path) -> Path:
    fake_python = tmp_path / "fake_python.cmd"
    fake_python.write_text(
        """@echo off
setlocal EnableDelayedExpansion
set "state=%TEST_DB_PROBE_STATE%"
if exist "%state%" (
    set /p attempt=<"%state%"
) else (
    set attempt=0
)
set /a attempt+=1
>"%state%" echo !attempt!
if !attempt! LSS %TEST_DB_PROBE_SUCCEEDS_AFTER% (
    >&2 echo %TEST_DB_PROBE_FAILURE_MESSAGE%
    exit /b %TEST_DB_PROBE_FAILURE_EXIT_CODE%
)
echo Native PostgreSQL production primary is ready.
exit /b 0
""",
        encoding="ascii",
    )
    return fake_python


def _identity_mocks(
    *,
    wrong_listener_owner: bool,
    service_running: bool,
) -> str:
    listener_name = (
        "com.docker.backend.exe"
        if wrong_listener_owner
        else "postgres.exe"
    )
    listener_parent = 999 if wrong_listener_owner else 100
    service_state = "Running" if service_running else "Stopped"
    service_process_id = 100 if service_running else 0
    return rf"""
function Get-CimInstance {{
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$ClassName,
        [string]$Filter
    )

    if ($ClassName -eq "Win32_Service") {{
        return [pscustomobject]@{{
            Name = "SportsModelPostgreSQL16"
            State = "{service_state}"
            StartMode = "Auto"
            ProcessId = {service_process_id}
            PathName = (
                '"D:\PostgreSQL\16\server\bin\pg_ctl.exe" ' +
                'runservice -N "SportsModelPostgreSQL16" ' +
                '-D "D:\PostgreSQL\16\data" -w'
            )
        }}
    }}

    if ($Filter -eq "ProcessId=100") {{
        return [pscustomobject]@{{
            ProcessId = 100
            ParentProcessId = 50
            Name = "pg_ctl.exe"
        }}
    }}

    if ($Filter -eq "ProcessId=200") {{
        return [pscustomobject]@{{
            ProcessId = 200
            ParentProcessId = {listener_parent}
            Name = "{listener_name}"
        }}
    }}

    return $null
}}

function Get-NetTCPConnection {{
    [CmdletBinding()]
    param(
        [string]$State,
        [int]$LocalPort
    )

    return @(
        [pscustomobject]@{{
            LocalAddress = "127.0.0.1"
            LocalPort = 5432
            OwningProcess = 200
        }},
        [pscustomobject]@{{
            LocalAddress = "::1"
            LocalPort = 5432
            OwningProcess = 200
        }}
    )
}}
"""


def _run_readiness(
    tmp_path: Path,
    *,
    succeeds_after: int,
    failure_exit_code: int = TRANSIENT_EXIT_CODE,
    timeout_seconds: int = 3,
    poll_seconds: int = 1,
    wrong_listener_owner: bool = False,
    service_running: bool = True,
    failure_message: str = (
        "Native PostgreSQL is temporarily unavailable."
    ),
    workflow_marker_path: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], int, float]:
    fake_python = _write_fake_python(tmp_path)
    source_path = tmp_path / "src"
    source_path.mkdir()
    state_path = tmp_path / "attempts.txt"
    helper_path = str(HELPER_PATH).replace("'", "''")
    python_path = str(fake_python).replace("'", "''")
    source = str(source_path).replace("'", "''")
    if workflow_marker_path is None:
        workflow_action = ""
    else:
        marker = str(workflow_marker_path).replace("'", "''")
        workflow_action = (
            f"Set-Content -LiteralPath '{marker}' "
            "-Value 'workflow executed'"
        )
    command = rf"""
$ErrorActionPreference = "Stop"
{_identity_mocks(
    wrong_listener_owner=wrong_listener_owner,
    service_running=service_running,
)}
. '{helper_path}'
try {{
    Wait-SportsModelDatabaseReady `
        -PythonPath '{python_path}' `
        -SourcePath '{source}' `
        -TimeoutSeconds {timeout_seconds} `
        -PollSeconds {poll_seconds}
    {workflow_action}
    exit 0
}}
catch {{
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}}
"""
    environment = os.environ.copy()
    environment.update(
        {
            "TEST_DB_PROBE_STATE": str(state_path),
            "TEST_DB_PROBE_SUCCEEDS_AFTER": str(succeeds_after),
            "TEST_DB_PROBE_FAILURE_EXIT_CODE": str(failure_exit_code),
            "TEST_DB_PROBE_FAILURE_MESSAGE": failure_message,
        }
    )
    started_at = time.monotonic()
    result = subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout_seconds + poll_seconds + 10,
        check=False,
    )
    elapsed = time.monotonic() - started_at
    attempts = int(state_path.read_text()) if state_path.exists() else 0
    return result, attempts, elapsed


def test_expected_native_identity_and_healthy_database_are_ready(
    tmp_path: Path,
) -> None:
    result, attempts, _ = _run_readiness(tmp_path, succeeds_after=1)

    assert result.returncode == 0, result.stderr
    assert attempts == 1
    assert "SportsModel database readiness: READY" in result.stdout
    assert "listener identity are valid" in result.stdout
    assert "production primary is ready" in result.stdout


def test_wrong_process_owns_5432_fails_closed(tmp_path: Path) -> None:
    result, attempts, _ = _run_readiness(
        tmp_path,
        succeeds_after=1,
        wrong_listener_owner=True,
    )

    assert result.returncode == 1
    assert attempts == 0
    assert "failed permanently" in result.stderr
    assert "not owned by the postgres.exe child" in result.stderr


def test_listener_while_native_service_is_stopped_fails_closed(
    tmp_path: Path,
) -> None:
    result, attempts, _ = _run_readiness(
        tmp_path,
        succeeds_after=1,
        wrong_listener_owner=True,
        service_running=False,
    )

    assert result.returncode == 1
    assert attempts == 0
    assert "listener while Windows service" in result.stderr


def test_database_temporarily_unavailable_then_ready(tmp_path: Path) -> None:
    result, attempts, _ = _run_readiness(tmp_path, succeeds_after=2)

    assert result.returncode == 0, result.stderr
    assert attempts == 2
    assert "temporarily unavailable" in result.stdout
    assert "no database service will be started automatically" in result.stdout
    assert "SportsModel database readiness: READY" in result.stdout


def test_database_timeout_fails_closed_with_actionable_message(
    tmp_path: Path,
) -> None:
    result, attempts, elapsed = _run_readiness(
        tmp_path,
        succeeds_after=100,
        timeout_seconds=1,
    )

    assert result.returncode == 1
    assert attempts >= 1
    assert elapsed < 3
    assert "did not become ready within 1 seconds" in result.stderr
    assert "SportsModelPostgreSQL16" in result.stderr
    assert "No database service was started automatically" in result.stderr


def test_permanent_database_failure_does_not_retry(tmp_path: Path) -> None:
    result, attempts, elapsed = _run_readiness(
        tmp_path,
        succeeds_after=100,
        failure_exit_code=PERMANENT_EXIT_CODE,
        timeout_seconds=5,
    )

    assert result.returncode == 1
    assert attempts == 1
    assert elapsed < 3
    assert "failed permanently" in result.stderr
    assert "No database service was started automatically" in result.stderr


def test_schema_rejection_prevents_simulated_workflow_execution(
    tmp_path: Path,
) -> None:
    workflow_marker = tmp_path / "workflow_executed.txt"
    result, attempts, _ = _run_readiness(
        tmp_path,
        succeeds_after=100,
        failure_exit_code=PERMANENT_EXIT_CODE,
        timeout_seconds=5,
        failure_message=(
            "Observed production schema migration 026; required minimum "
            "compatible migration 029. Execution was refused before "
            "live workflow or provider work began."
        ),
        workflow_marker_path=workflow_marker,
    )

    assert result.returncode == 1
    assert attempts == 1
    assert not workflow_marker.exists()
    assert "migration 026" in result.stderr
    assert "migration 029" in result.stderr
    assert "before live workflow or provider work began" in result.stderr


def test_helper_has_no_docker_or_service_control_fallback() -> None:
    helper = HELPER_PATH.read_text(encoding="utf-8-sig").lower()

    assert "sportsmodelpostgresql16" in helper
    assert "d:\\postgresql\\16\\server\\bin\\pg_ctl.exe" in helper
    assert "d:\\postgresql\\16\\data" in helper
    assert "get-nettcpconnection" in helper
    assert "diagnostics.stopwatch" in helper
    assert "get-date" not in helper
    assert "docker" not in helper
    assert "start-service" not in helper
    assert "stop-service" not in helper
    assert "restart-service" not in helper


@pytest.mark.parametrize(
    "wrapper_name",
    [
        "run_moneyline_daily_pregame.ps1",
        "run_moneyline_daily_postgame.ps1",
        "run_moneyline_odds_snapshot.ps1",
    ],
)
def test_production_callers_fail_nonzero_when_readiness_throws(
    wrapper_name: str,
) -> None:
    wrapper = (
        REPOSITORY_ROOT / "scripts" / wrapper_name
    ).read_text(encoding="utf-8-sig")
    readiness_call = wrapper.index("Wait-SportsModelDatabaseReady")
    catch_block = wrapper.index("catch {", readiness_call)
    workflow_execution = wrapper.index("& $PythonPath", readiness_call)

    assert "exit 1" in wrapper[catch_block:]
    assert readiness_call < workflow_execution


@pytest.mark.parametrize(
    "host",
    ["localhost", "LOCALHOST", "127.0.0.1", "::1"],
)
def test_loopback_host_validation_accepts_loopback_semantics(host: str) -> None:
    assert is_loopback_host(host)


@pytest.mark.parametrize(
    "host",
    ["", "postgres", "127.10.20.30", "192.168.1.20"],
)
def test_loopback_host_validation_rejects_other_hosts(host: str) -> None:
    assert not is_loopback_host(host)


class _Cursor:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *arguments: object) -> None:
        del arguments

    def execute(self, query: str) -> None:
        assert "current_database()" in query
        assert "pg_is_in_recovery()" in query
        assert "transaction_read_only" in query
        assert "MAX(version)" in query
        assert "schema_migrations" in query

    def fetchone(self) -> tuple[Any, ...]:
        return self._row


class _Connection:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self._row)

    def close(self) -> None:
        self.closed = True


class _FailingCursor:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def __enter__(self) -> _FailingCursor:
        return self

    def __exit__(self, *arguments: object) -> None:
        del arguments

    def execute(self, query: str) -> None:
        del query
        raise self._error


class _FailingConnection:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.closed = False

    def cursor(self) -> _FailingCursor:
        return _FailingCursor(self._error)

    def close(self) -> None:
        self.closed = True


def _environment(**overrides: str) -> dict[str, str]:
    environment = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "sportsmodel",
    }
    environment.update(overrides)
    return environment


def _result_for_row(row: tuple[Any, ...]):
    connection = _Connection(row)
    result = check_database_readiness(
        environment=_environment(),
        connection_factory=lambda: connection,
    )
    assert connection.closed
    return result


def test_probe_accepts_writable_production_primary() -> None:
    result = _result_for_row(
        (
            "sportsmodel",
            5432,
            False,
            "off",
            "off",
            MINIMUM_COMPATIBLE_PRODUCTION_MIGRATION,
        )
    )

    assert result.exit_code == READY_EXIT_CODE
    assert "migration 029" in result.message


def test_probe_accepts_schema_newer_than_minimum() -> None:
    result = _result_for_row(
        ("sportsmodel", 5432, False, "off", "off", 31)
    )

    assert result.exit_code == READY_EXIT_CODE
    assert "migration 031" in result.message
    assert "migration 029" in result.message


def test_probe_rejects_schema_below_minimum_as_permanent() -> None:
    result = _result_for_row(
        ("sportsmodel", 5432, False, "off", "off", 26)
    )

    assert result.exit_code == PERMANENT_EXIT_CODE
    assert "migration 026" in result.message
    assert "migration 029" in result.message
    assert "before live workflow or provider work began" in result.message


def test_probe_fails_closed_when_schema_version_is_unknown() -> None:
    result = _result_for_row(
        ("sportsmodel", 5432, False, "off", "off", None)
    )

    assert result.exit_code == PERMANENT_EXIT_CODE
    assert "migration unavailable" in result.message
    assert "migration 029" in result.message
    assert "before live workflow or provider work began" in result.message


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            ("sportsmodel", 5432, True, "off", "off", 29),
            "recovery replica",
        ),
        (
            ("sportsmodel", 5432, False, "on", "off", 29),
            "transaction state is read-only",
        ),
        (
            ("sportsmodel", 5432, False, "off", "on", 29),
            "server default is read-only",
        ),
    ],
)
def test_probe_rejects_recovery_or_read_only_server(
    row: tuple[Any, ...],
    message: str,
) -> None:
    result = _result_for_row(row)

    assert result.exit_code == PERMANENT_EXIT_CODE
    assert message in result.message


def test_probe_classifies_connection_refusal_as_transient() -> None:
    def unavailable_connection():
        raise psycopg2.OperationalError(
            "could not connect to server: Connection refused"
        )

    result = check_database_readiness(
        environment=_environment(),
        connection_factory=unavailable_connection,
    )

    assert result.exit_code == TRANSIENT_EXIT_CODE


def test_probe_classifies_authentication_failure_as_permanent() -> None:
    def rejected_connection():
        raise psycopg2.OperationalError(
            "password authentication failed for user"
        )

    result = check_database_readiness(
        environment=_environment(),
        connection_factory=rejected_connection,
    )

    assert result.exit_code == PERMANENT_EXIT_CODE
    assert "authentication" in result.message
    assert "password" not in result.message


def test_probe_retries_transient_query_connection_loss() -> None:
    connection = _FailingConnection(
        psycopg2.OperationalError(
            "server closed the connection unexpectedly"
        )
    )

    result = check_database_readiness(
        environment=_environment(),
        connection_factory=lambda: connection,
    )

    assert result.exit_code == TRANSIENT_EXIT_CODE
    assert connection.closed


def test_probe_fails_promptly_for_other_query_errors() -> None:
    connection = _FailingConnection(RuntimeError("unexpected query error"))

    result = check_database_readiness(
        environment=_environment(),
        connection_factory=lambda: connection,
    )

    assert result.exit_code == PERMANENT_EXIT_CODE
    assert connection.closed


def test_probe_rejects_wrong_database_configuration_without_connecting() -> None:
    connection_attempted = False

    def unexpected_connection():
        nonlocal connection_attempted
        connection_attempted = True

    result = check_database_readiness(
        environment=_environment(POSTGRES_DB="other_database"),
        connection_factory=unexpected_connection,
    )

    assert result.exit_code == PERMANENT_EXIT_CODE
    assert not connection_attempted
