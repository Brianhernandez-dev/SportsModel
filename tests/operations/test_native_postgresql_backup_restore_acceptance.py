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
    / "invoke_native_postgresql_backup_restore_acceptance.ps1"
)


def _powershell() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("Windows PowerShell is required for acceptance tests.")
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


def test_default_action_is_plan_only() -> None:
    result = _run()

    assert result.returncode == 0, result.stderr
    assert "PLAN ONLY" in result.stdout
    assert "no database or backup operation was executed" in result.stdout


def test_plan_accepts_clearly_disposable_target() -> None:
    result = _run(
        "-Action",
        "Plan",
        "-TargetDatabase",
        "sportsmodel_restore_acceptance_20260903t180000z",
    )

    assert result.returncode == 0, result.stderr
    assert "PLAN ONLY" in result.stdout


@pytest.mark.parametrize(
    "target",
    [
        "sportsmodel",
        "postgres",
        "template0",
        "template1",
        "production",
        "prod",
        "sportsmodel_prod",
        "sportsmodel_production",
        "unrelated_test_database",
        "sportsmodel_restore_acceptance_not_timestamped",
    ],
)
def test_restore_target_guard_rejects_protected_or_ambiguous_names(
    target: str,
) -> None:
    result = _run(
        "-Action",
        "VerifyRestore",
        "-TargetDatabase",
        target,
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "refused" in combined or "protected database" in combined


@pytest.mark.parametrize(
    ("action", "approval_name"),
    [
        ("Backup", "ApproveProductionBackup"),
        ("CreateRestoreTarget", "ApproveCreateRestoreTarget"),
        ("Restore", "ApproveRestore"),
        ("DropRestoreTarget", "ApproveDropRestoreTarget"),
    ],
)
def test_consequential_action_requires_exact_approval(
    action: str,
    approval_name: str,
) -> None:
    arguments = ["-Action", action]
    if action != "Backup":
        arguments.extend(
            [
                "-TargetDatabase",
                "sportsmodel_restore_acceptance_20260903t180000z",
            ]
        )

    result = _run(*arguments)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert f"Supply -{approval_name}" in combined


def test_backup_approval_does_not_bypass_required_artifact_path() -> None:
    result = _run("-Action", "Backup", "-ApproveProductionBackup")

    assert result.returncode != 0
    assert "BackupPath is required" in result.stdout + result.stderr


def test_backup_requires_timestamped_non_overwriting_artifact_name(
    tmp_path: Path,
) -> None:
    result = _run(
        "-Action",
        "Backup",
        "-ApproveProductionBackup",
        "-BackupPath",
        str(tmp_path / "sportsmodel.dump"),
    )

    assert result.returncode != 0
    assert "Timestamped backup filenames must match" in (
        result.stdout + result.stderr
    )


def test_script_has_no_hidden_destructive_or_docker_restore_flags() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8").lower()

    assert "--clean" not in script
    assert "--create" not in script
    assert "--force" not in script
    assert "start-service" not in script
    assert "stop-service" not in script
    assert "docker" not in script


def test_restore_uses_single_transaction_without_owner_or_acl_replay() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"--single-transaction"' in script
    assert '"--no-owner"' in script
    assert '"--no-privileges"' in script
    assert '"--exit-on-error"' in script


def test_disposable_database_requires_marker_and_expected_owner() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "sportsmodel-backup-restore-acceptance-v1" in script
    assert "Assert-RestoreTargetMarker" in script
    assert "$SafeTarget,\n            $RestoreTargetMarker" in script
    assert "--comment=" not in script
    assert "pg_get_userbyid(datdba)" in script


def test_password_is_environment_sourced_and_never_a_command_argument() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'Values["POSTGRES_PASSWORD"]' in script
    assert 'Set-ProcessEnvironmentValue -Name "PGPASSWORD"' in script
    assert "--password=" not in script
    assert "--no-password" in script


def test_read_only_identity_check_does_not_misclassify_its_own_session() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    identity_start = script.index("function Assert-DatabaseIdentity")
    identity_end = script.index(
        "function Get-DatabaseContentSnapshot",
        identity_start,
    )
    identity_function = script[identity_start:identity_end]

    assert "current_database()" in identity_function
    assert "inet_server_port()" in identity_function
    assert "pg_is_in_recovery()" in identity_function
    assert "default_transaction_read_only" not in identity_function
    assert 'ExpectedIdentity = "$ExpectedDatabase|$ExpectedSourcePort|f"' in (
        identity_function
    )


def test_postgresql_boolean_text_expectations_use_psql_representation() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'TargetWriteState -cne "f|off"' in script
    assert 'relkind::text ||' in script


def _function_body(script: str, name: str, next_name: str) -> str:
    start = script.index(f"function {name}")
    end = script.index(f"function {next_name}", start)
    return script[start:end]


def test_recurring_actions_resolve_only_required_postgresql_tools() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    backup = _function_body(script, "Invoke-Backup", "Invoke-VerifyBackup")
    verify = _function_body(script, "Invoke-VerifyBackup", "Get-AdminConnection")

    assert 'Get-PostgreSqlTools -Names @("pg_dump", "pg_restore", "psql")' in backup
    assert 'Get-PostgreSqlTools -Names @("pg_restore")' in verify
    assert "createdb" not in backup + verify
    assert "dropdb" not in backup + verify


def test_verify_backup_rejects_truncated_custom_format_archive(
    tmp_path: Path,
) -> None:
    postgresql_bin = Path(r"D:\PostgreSQL\16\server\bin")
    assert (postgresql_bin / "pg_restore.exe").is_file()
    backup = tmp_path / "sportsmodel-native-20260907t120000z.dump"
    backup.write_bytes(b"PGDMP\x01\x0f\x00")
    manifest = Path(f"{backup}.manifest.json")
    manifest.write_text(
        json.dumps(
            {
                "BackupSha256": hashlib.sha256(backup.read_bytes())
                .hexdigest()
                .upper(),
                "BackupSizeBytes": backup.stat().st_size,
            }
        ),
        encoding="utf-8",
    )

    result = _run(
        "-Action",
        "VerifyBackup",
        "-PostgreSqlBinPath",
        str(postgresql_bin),
        "-BackupPath",
        str(backup),
        "-ManifestPath",
        str(manifest),
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "pg_restore" in combined
    assert "end of file" in combined


def test_operator_restore_actions_retain_action_specific_tools_and_guards() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    preflight = _function_body(script, "Invoke-Preflight", "Assert-BackupInputs")
    create = _function_body(script, "Invoke-CreateRestoreTarget", "Invoke-Restore")
    restore = _function_body(script, "Invoke-Restore", "Invoke-VerifyRestore")
    drop_start = script.index("function Invoke-DropRestoreTarget")
    drop_end = script.index("if ($Action -in", drop_start)
    drop = script[drop_start:drop_end]

    assert '"createdb"' in preflight
    assert '"dropdb"' in preflight
    assert 'Get-PostgreSqlTools -Names @("psql", "createdb")' in create
    assert "ApproveCreateRestoreTarget" in create
    assert 'Get-PostgreSqlTools -Names @("psql", "pg_restore")' in restore
    assert "ApproveRestore" in restore
    assert 'Get-PostgreSqlTools -Names @("psql", "dropdb")' in drop
    assert "ApproveDropRestoreTarget" in drop
    assert "Assert-RestoreTargetMarker" in create + restore + drop


def test_backup_readiness_uses_shared_helper_without_python_runtime() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    readiness = _function_body(
        script,
        "Invoke-NativeReadinessPreflight",
        "Get-ToolVersions",
    )

    assert "wait_for_sportsmodel_database.ps1" in readiness
    assert "-DatabaseProbe $ReadinessProbe" in readiness
    assert "-PythonPath" not in readiness
    assert "-SourcePath" not in readiness
    assert "Start-Service" not in readiness
    assert "docker" not in readiness.lower()


def test_readiness_probe_requires_exact_database_and_migration_row() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    probe = _function_body(
        script,
        "Invoke-AcceptanceDatabaseReadinessProbe",
        "Invoke-NativeReadinessPreflight",
    )

    assert "bool_or(version = $MinimumCompatibleMigration)" in probe
    assert "-ReadOnly $false" in probe
    assert "must observe the server's actual writable-primary state" in probe
    assert "hardcoded and SELECT-only" in probe
    assert "current_setting('transaction_read_only')" in probe
    assert "current_setting('default_transaction_read_only')" in probe
    assert "$ObservedMigration -lt $MinimumCompatibleMigration" in probe
    assert '$Parts[1] -cne "t"' in probe
    assert 'Status = "permanent"' in probe
