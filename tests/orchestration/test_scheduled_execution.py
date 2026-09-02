from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsmodel.orchestration.scheduled_execution import (
    MONEYLINE_ODDS_SNAPSHOT_TASK,
    MONEYLINE_POSTGAME_TASK,
    MONEYLINE_PREGAME_TASK,
    MONEYLINE_TOMORROW_PREVIEW_TASK,
    PACIFIC_TIME_ZONE,
    evaluate_scheduled_execution,
)
from sportsmodel.orchestration.scheduled_execution_cli import main


REPOSITORY_ROOT = Path(__file__).parents[2]
SCRIPTS_ROOT = REPOSITORY_ROOT / "scripts"


def _pacific_time(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int = 0,
) -> datetime:
    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        tzinfo=PACIFIC_TIME_ZONE,
    )


@pytest.mark.parametrize(
    ("task_identity", "snapshot_role", "scheduled_time", "target_date"),
    [
        (
            MONEYLINE_ODDS_SNAPSHOT_TASK,
            "morning",
            _pacific_time(2026, 9, 1, 6, 0),
            date(2026, 9, 1),
        ),
        (
            MONEYLINE_ODDS_SNAPSHOT_TASK,
            "afternoon",
            _pacific_time(2026, 9, 1, 12, 0),
            date(2026, 9, 1),
        ),
        (
            MONEYLINE_ODDS_SNAPSHOT_TASK,
            "opening",
            _pacific_time(2026, 9, 1, 18, 30),
            date(2026, 9, 2),
        ),
        (
            MONEYLINE_ODDS_SNAPSHOT_TASK,
            "evening",
            _pacific_time(2026, 9, 1, 20, 30),
            date(2026, 9, 2),
        ),
        (
            MONEYLINE_ODDS_SNAPSHOT_TASK,
            "late_night",
            _pacific_time(2026, 9, 1, 23, 0),
            date(2026, 9, 2),
        ),
        (
            MONEYLINE_PREGAME_TASK,
            None,
            _pacific_time(2026, 9, 1, 8, 0),
            date(2026, 9, 1),
        ),
        (
            MONEYLINE_POSTGAME_TASK,
            None,
            _pacific_time(2026, 9, 1, 7, 15),
            date(2026, 8, 31),
        ),
        (
            MONEYLINE_POSTGAME_TASK,
            None,
            _pacific_time(2026, 9, 1, 13, 15),
            date(2026, 8, 31),
        ),
        (
            MONEYLINE_TOMORROW_PREVIEW_TASK,
            None,
            _pacific_time(2026, 9, 1, 18, 45),
            date(2026, 9, 2),
        ),
    ],
)
def test_execution_at_scheduled_time_is_valid(
    task_identity: str,
    snapshot_role: str | None,
    scheduled_time: datetime,
    target_date: date,
) -> None:
    result = evaluate_scheduled_execution(
        task_identity=task_identity,
        snapshot_role=snapshot_role,
        current_time=scheduled_time,
    )

    assert result.valid
    assert result.intended_scheduled_time == scheduled_time
    assert result.intended_target_date == target_date
    assert result.latest_valid_start_time == scheduled_time + timedelta(hours=1)


@pytest.mark.parametrize("minutes_late", [1, 15, 30, 45, 59])
def test_normal_delay_and_configured_retries_remain_valid(
    minutes_late: int,
) -> None:
    result = evaluate_scheduled_execution(
        task_identity=MONEYLINE_ODDS_SNAPSHOT_TASK,
        snapshot_role="morning",
        current_time=(
            _pacific_time(2026, 9, 1, 6, 0)
            + timedelta(minutes=minutes_late)
        ),
    )

    assert result.valid


def test_execution_at_exclusive_maximum_is_expired() -> None:
    result = evaluate_scheduled_execution(
        task_identity=MONEYLINE_ODDS_SNAPSHOT_TASK,
        snapshot_role="morning",
        current_time=_pacific_time(2026, 9, 1, 7, 0),
    )

    assert not result.valid
    assert "point-in-time correctness" in result.reason
    assert "must not be backfilled" in result.reason


def test_semantic_deadline_caps_operational_window() -> None:
    semantic_deadline = _pacific_time(2026, 9, 1, 8, 20)

    before_deadline = evaluate_scheduled_execution(
        task_identity=MONEYLINE_PREGAME_TASK,
        current_time=_pacific_time(2026, 9, 1, 8, 19, 59),
        semantic_deadline=semantic_deadline,
    )
    at_deadline = evaluate_scheduled_execution(
        task_identity=MONEYLINE_PREGAME_TASK,
        current_time=semantic_deadline,
        semantic_deadline=semantic_deadline,
    )

    assert before_deadline.valid
    assert before_deadline.latest_valid_start_time == semantic_deadline
    assert before_deadline.operational_latest_valid_start_time == (
        _pacific_time(2026, 9, 1, 9, 0)
    )
    assert at_deadline.valid is False
    assert "semantic point-in-time deadline" in at_deadline.reason


def test_later_semantic_deadline_does_not_extend_operational_window() -> None:
    result = evaluate_scheduled_execution(
        task_identity=MONEYLINE_PREGAME_TASK,
        current_time=_pacific_time(2026, 9, 1, 9, 0),
        semantic_deadline=_pacific_time(2026, 9, 1, 10, 0),
    )

    assert result.valid is False
    assert result.latest_valid_start_time == _pacific_time(
        2026, 9, 1, 9, 0
    )
    assert "Scheduler retry window" in result.reason


@pytest.mark.parametrize("minutes_late", [15, 30, 45])
def test_pregame_retries_pass_before_later_first_pitch(
    minutes_late: int,
) -> None:
    result = evaluate_scheduled_execution(
        task_identity=MONEYLINE_PREGAME_TASK,
        current_time=(
            _pacific_time(2026, 9, 1, 8, 0)
            + timedelta(minutes=minutes_late)
        ),
        semantic_deadline=_pacific_time(2026, 9, 1, 9, 30),
    )

    assert result.valid
    assert result.latest_valid_start_time == _pacific_time(
        2026, 9, 1, 9, 0
    )


def test_semantic_deadline_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="Semantic deadline"):
        evaluate_scheduled_execution(
            task_identity=MONEYLINE_PREGAME_TASK,
            current_time=_pacific_time(2026, 9, 1, 8, 10),
            semantic_deadline=datetime(2026, 9, 1, 8, 20),
        )


def test_earlier_snapshot_is_expired_after_later_role_begins() -> None:
    result = evaluate_scheduled_execution(
        task_identity=MONEYLINE_ODDS_SNAPSHOT_TASK,
        snapshot_role="opening",
        current_time=_pacific_time(2026, 9, 1, 20, 30),
    )

    assert not result.valid
    assert result.intended_scheduled_time == _pacific_time(
        2026, 9, 1, 18, 30
    )


def test_late_night_catch_up_after_date_boundary_is_expired() -> None:
    result = evaluate_scheduled_execution(
        task_identity=MONEYLINE_ODDS_SNAPSHOT_TASK,
        snapshot_role="late_night",
        current_time=_pacific_time(2026, 9, 2, 0, 1),
    )

    assert not result.valid
    assert result.intended_scheduled_time == _pacific_time(
        2026, 9, 1, 23, 0
    )
    assert result.intended_target_date == date(2026, 9, 2)


def test_opening_retry_at_preview_trigger_remains_valid() -> None:
    result = evaluate_scheduled_execution(
        task_identity=MONEYLINE_ODDS_SNAPSHOT_TASK,
        snapshot_role="opening",
        current_time=_pacific_time(2026, 9, 1, 18, 45),
    )

    assert result.valid
    assert result.intended_target_date == date(2026, 9, 2)


@pytest.mark.parametrize(
    ("current_time", "expected_offset"),
    [
        (datetime(2026, 1, 15, 14, 15, tzinfo=timezone.utc), "-08:00"),
        (datetime(2026, 8, 15, 13, 15, tzinfo=timezone.utc), "-07:00"),
    ],
)
def test_pacific_conversion_is_dst_safe(
    current_time: datetime,
    expected_offset: str,
) -> None:
    result = evaluate_scheduled_execution(
        task_identity=MONEYLINE_ODDS_SNAPSHOT_TASK,
        snapshot_role="morning",
        current_time=current_time,
    )

    assert result.valid
    assert result.current_pacific_time.hour == 6
    assert result.current_pacific_time.minute == 15
    assert result.current_pacific_time.isoformat().endswith(expected_offset)


def test_naive_current_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_scheduled_execution(
            task_identity=MONEYLINE_PREGAME_TASK,
            current_time=datetime(2026, 9, 1, 8, 0),
        )


def test_cli_expired_result_is_clear_and_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--task-identity",
            MONEYLINE_ODDS_SNAPSHOT_TASK,
            "--snapshot-role",
            "morning",
        ],
        current_time=_pacific_time(2026, 9, 1, 7, 0),
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Scheduled execution validity: EXPIRED" in output
    assert "Intended target date: 2026-09-01" in output
    assert "Valid start window: [" in output
    assert "point-in-time correctness" in output
    assert "must not be backfilled" in output


def test_cli_accepts_pregame_before_canonical_first_pitch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    loaded_dates: list[date] = []

    def load_deadline(target_date: date) -> datetime:
        loaded_dates.append(target_date)
        return _pacific_time(2026, 9, 1, 8, 30)

    exit_code = main(
        [
            "--task-identity",
            MONEYLINE_PREGAME_TASK,
            "--enforce-canonical-pregame-deadline",
        ],
        current_time=_pacific_time(2026, 9, 1, 8, 29, 59),
        semantic_deadline_loader=load_deadline,
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert loaded_dates == [date(2026, 9, 1)]
    assert "Scheduled execution validity: VALID" in output
    assert "Semantic point-in-time deadline: 2026-09-01T08:30:00" in output
    assert "Valid start window: [" in output


def test_cli_refuses_pregame_at_canonical_first_pitch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider_called = False

    def load_deadline(target_date: date) -> datetime:
        assert target_date == date(2026, 9, 1)
        return _pacific_time(2026, 9, 1, 8, 30)

    exit_code = main(
        [
            "--task-identity",
            MONEYLINE_PREGAME_TASK,
            "--enforce-canonical-pregame-deadline",
        ],
        current_time=_pacific_time(2026, 9, 1, 8, 30),
        semantic_deadline_loader=load_deadline,
    )

    if exit_code == 0:
        provider_called = True

    output = capsys.readouterr().out
    assert exit_code == 1
    assert provider_called is False
    assert "Scheduled execution validity: EXPIRED" in output
    assert "semantic point-in-time deadline" in output


@pytest.mark.parametrize(
    "deadline_loader",
    [
        lambda _: None,
        lambda _: _raise_database_unavailable(),
    ],
)
def test_cli_refuses_pregame_when_canonical_deadline_is_unknown(
    deadline_loader: Callable[[date], datetime | None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--task-identity",
            MONEYLINE_PREGAME_TASK,
            "--enforce-canonical-pregame-deadline",
        ],
        current_time=_pacific_time(2026, 9, 1, 8, 10),
        semantic_deadline_loader=deadline_loader,
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Canonical Pregame deadline: UNKNOWN" in output
    assert "before live workflow or provider execution" in output


def _raise_database_unavailable() -> None:
    raise RuntimeError("database unavailable")


@pytest.mark.parametrize(
    ("wrapper_name", "task_identity"),
    [
        ("run_moneyline_daily_pregame.ps1", "moneyline_pregame"),
        ("run_moneyline_daily_postgame.ps1", "moneyline_postgame"),
    ],
)
def test_daily_wrappers_recheck_after_readiness_before_workflow(
    wrapper_name: str,
    task_identity: str,
) -> None:
    wrapper = (SCRIPTS_ROOT / wrapper_name).read_text(encoding="utf-8-sig")
    first_guard = wrapper.index("Assert-MoneylineScheduledExecutionValid")
    readiness = wrapper.index("Wait-SportsModelDatabaseReady")
    second_guard = wrapper.index(
        "Assert-MoneylineScheduledExecutionValid",
        first_guard + 1,
    )
    workflow = wrapper.index("& $PythonPath $ScriptPath 2>&1", second_guard)

    assert first_guard < readiness < second_guard < workflow
    assert wrapper.count("Assert-MoneylineScheduledExecutionValid") == 2
    assert f'-TaskIdentity "{task_identity}"' in wrapper

    if task_identity == "moneyline_pregame":
        assert "-EnforceCanonicalPregameDeadline" not in wrapper[
            first_guard:readiness
        ]
        assert "-EnforceCanonicalPregameDeadline" in wrapper[
            second_guard:workflow
        ]


def test_snapshot_wrapper_rechecks_after_readiness_before_provider() -> None:
    wrapper = (
        SCRIPTS_ROOT / "run_moneyline_odds_snapshot.ps1"
    ).read_text(encoding="utf-8-sig")
    first_guard = wrapper.index("Assert-MoneylineScheduledExecutionValid")
    readiness = wrapper.index("Wait-SportsModelDatabaseReady")
    second_guard = wrapper.index(
        "Assert-MoneylineScheduledExecutionValid",
        first_guard + 1,
    )
    provider = wrapper.index("& $PythonPath `", second_guard)

    assert first_guard < readiness < second_guard < provider
    assert wrapper.count("Assert-MoneylineScheduledExecutionValid") == 2
    assert 'if ($SnapshotRole -in $ScheduledSnapshotRoles)' in wrapper


def test_fixed_snapshot_task_checks_before_target_resolution_and_capture() -> None:
    wrapper = (
        SCRIPTS_ROOT / "run_moneyline_odds_snapshot_task.ps1"
    ).read_text(encoding="utf-8-sig")
    first_guard = wrapper.index("Assert-MoneylineScheduledExecutionValid")
    target_resolver = wrapper.index("$TargetDateOutput = & $PythonPath")
    snapshot = wrapper.index("& $SnapshotWrapperPath `")
    second_guard = wrapper.index(
        "Assert-MoneylineScheduledExecutionValid",
        first_guard + 1,
    )
    early_entry = wrapper.index("$CaptureOutput = & $PythonPath")

    assert first_guard < target_resolver < snapshot < second_guard < early_entry
    assert wrapper.count("Assert-MoneylineScheduledExecutionValid") == 2


def test_preview_checks_before_wait_and_again_before_generation() -> None:
    wrapper = (
        SCRIPTS_ROOT / "run_moneyline_tomorrow_preview.ps1"
    ).read_text(encoding="utf-8-sig")
    first_guard = wrapper.index("Assert-MoneylineScheduledExecutionValid")
    readiness = wrapper.index("Wait-SportsModelDatabaseReady")
    opening_wait = wrapper.index("Get-ScheduledTask -TaskName")
    second_guard = wrapper.index(
        "Assert-MoneylineScheduledExecutionValid",
        first_guard + 1,
    )
    preview = wrapper.index("$PreviewOutput = & $PythonPath")

    assert first_guard < readiness < opening_wait < second_guard < preview
    assert wrapper.count("Assert-MoneylineScheduledExecutionValid") == 2
    assert 'if ($OpeningTask.State -eq "Running")' in wrapper[
        opening_wait:preview
    ]
    assert "Opening snapshot has not run today" in wrapper[
        opening_wait:preview
    ]
    assert "Opening snapshot task failed with result" in wrapper[
        opening_wait:preview
    ]


def test_guard_failure_prevents_following_simulated_provider(
    tmp_path: Path,
) -> None:
    shell = _windows_powershell()
    fake_python = tmp_path / "expired.cmd"
    marker = tmp_path / "provider-called.txt"
    harness = tmp_path / "guard-harness.ps1"

    fake_python.write_text(
        "@echo Scheduled execution validity: EXPIRED\r\n"
        "@echo Execution was refused to preserve point-in-time correctness.\r\n"
        "@exit /b 1\r\n",
        encoding="ascii",
    )
    harness.write_text(
        f'. "{SCRIPTS_ROOT / "assert_moneyline_scheduled_execution.ps1"}"\n'
        "try {\n"
        "    Assert-MoneylineScheduledExecutionValid "
        f'-PythonPath "{fake_python}" '
        f'-SourcePath "{REPOSITORY_ROOT / "src"}" '
        '-TaskIdentity "moneyline_pregame"\n'
        f'    Set-Content -LiteralPath "{marker}" -Value "called"\n'
        "}\n"
        "catch {\n"
        "    Write-Error $_.Exception.Message\n"
        "    exit 1\n"
        "}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            shell,
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
    )

    assert result.returncode == 1
    assert not marker.exists()
    assert "refused task moneyline_pregame" in result.stderr


def _windows_powershell() -> str:
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        pytest.skip("Windows PowerShell is required for wrapper guard tests.")
    return shell
