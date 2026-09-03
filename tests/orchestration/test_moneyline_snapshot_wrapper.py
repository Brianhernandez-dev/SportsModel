from pathlib import Path


WRAPPER_PATH = (
    Path(__file__).parents[2]
    / "scripts"
    / "run_moneyline_odds_snapshot.ps1"
)

TASK_WRAPPER_PATH = (
    Path(__file__).parents[2]
    / "scripts"
    / "run_moneyline_odds_snapshot_task.ps1"
)

EXPECTED_SNAPSHOT_ROLES = (
    "opening",
    "evening",
    "late_night",
    "morning",
    "afternoon",
    "near_close",
)


def test_snapshot_wrappers_accept_expected_roles() -> None:
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8-sig")
    task_wrapper = TASK_WRAPPER_PATH.read_text(
        encoding="utf-8-sig"
    )

    for snapshot_role in EXPECTED_SNAPSHOT_ROLES:
        assert f'"{snapshot_role}"' in wrapper

    for snapshot_role in EXPECTED_SNAPSHOT_ROLES[:-1]:
        assert f'"{snapshot_role}"' in task_wrapper


def test_live_snapshot_uses_shared_database_readiness() -> None:
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8-sig")

    assert (
        '"scripts\\wait_for_sportsmodel_database.ps1"'
        in wrapper
    )
    assert ". $DatabaseReadinessPath" in wrapper
    assert "Wait-SportsModelDatabaseReady" in wrapper


def test_live_snapshot_uses_bounded_shared_retry() -> None:
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8-sig")

    assert '"scripts\\invoke_moneyline_retry.ps1"' in wrapper
    assert ". $RetryHelperPath" in wrapper
    assert "Invoke-MoneylineOperationWithRetry" in wrapper
    assert "-MaxAttempts $MaximumAttempts" in wrapper
    assert "-RetryDelaySeconds 900" in wrapper
    assert "-RetryDeadlineProvider $SnapshotRetryDeadlineProvider" in wrapper
    assert "return $LASTEXITCODE" in wrapper


def test_non_live_modes_exit_before_database_readiness() -> None:
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8-sig")

    readiness_call = wrapper.index(
        "Wait-SportsModelDatabaseReady"
    )

    assert wrapper.index("if ($ValidateOnly)") < readiness_call
    assert wrapper.index("if ($DryRun)") < readiness_call
    assert wrapper.index("exit 0", wrapper.index("if ($ValidateOnly)")) < (
        readiness_call
    )
    assert wrapper.index("exit 0", wrapper.index("if ($DryRun)")) < (
        readiness_call
    )


def test_database_readiness_precedes_live_odds_ingestion() -> None:
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8-sig")

    readiness_call = wrapper.index(
        "Wait-SportsModelDatabaseReady"
    )
    ingestion_call = wrapper.index(
        "& $PythonPath `",
        readiness_call,
    )

    assert readiness_call < ingestion_call


def test_late_night_task_captures_early_entry_after_snapshot() -> None:
    wrapper = TASK_WRAPPER_PATH.read_text(encoding="utf-8-sig")

    snapshot_call = wrapper.index("& $SnapshotWrapperPath `")
    capture_guard = wrapper.index('if ($SnapshotRole -eq "late_night")')
    capture_call = wrapper.index("$EarlyEntryCapturePath `", capture_guard)

    assert snapshot_call < capture_guard < capture_call
    assert "--target-date $TargetDate" in wrapper[capture_call:]
    assert wrapper.count("$EarlyEntryCapturePath `") == 1
    assert "Early Entry capture failed with exit code" in wrapper


def test_late_night_task_logging_allows_empty_output_lines() -> None:
    wrapper = TASK_WRAPPER_PATH.read_text(encoding="utf-8-sig")
    write_log = wrapper.index("function Write-Log")
    logging_loop = wrapper.index(
        "foreach ($OutputLine in $CaptureOutput)"
    )

    assert "[AllowEmptyString()]" in wrapper[write_log:logging_loop]
    assert 'Write-Log "$OutputLine"' in wrapper[logging_loop:]


def test_non_live_task_modes_precede_early_entry_capture() -> None:
    wrapper = TASK_WRAPPER_PATH.read_text(encoding="utf-8-sig")
    capture_guard = wrapper.index('if ($SnapshotRole -eq "late_night")')

    validate_guard = wrapper.index("if ($ValidateOnly)")
    dry_run_guard = wrapper.index("if ($DryRun)")

    assert validate_guard < capture_guard
    assert dry_run_guard < capture_guard
    assert wrapper.index("return", validate_guard) < capture_guard
    assert wrapper.index("return", dry_run_guard) < capture_guard
