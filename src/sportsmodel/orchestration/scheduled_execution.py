from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sportsmodel.orchestration.odds_snapshot_schedule import (
    PACIFIC_TIME_ZONE,
)


EXECUTION_VALIDITY_WINDOW = timedelta(hours=1)

MONEYLINE_ODDS_SNAPSHOT_TASK = "moneyline_odds_snapshot"
MONEYLINE_PREGAME_TASK = "moneyline_pregame"
MONEYLINE_POSTGAME_TASK = "moneyline_postgame"
MONEYLINE_TOMORROW_PREVIEW_TASK = "moneyline_tomorrow_preview"

SCHEDULED_TASK_IDENTITIES = frozenset(
    {
        MONEYLINE_ODDS_SNAPSHOT_TASK,
        MONEYLINE_PREGAME_TASK,
        MONEYLINE_POSTGAME_TASK,
        MONEYLINE_TOMORROW_PREVIEW_TASK,
    }
)

SNAPSHOT_SCHEDULES = {
    "morning": time(6, 0),
    "afternoon": time(12, 0),
    "opening": time(18, 30),
    "evening": time(20, 30),
    "late_night": time(23, 0),
}


@dataclass(frozen=True)
class ScheduledExecutionValidity:
    task_identity: str
    snapshot_role: str | None
    intended_target_date: date
    current_pacific_time: datetime
    intended_scheduled_time: datetime
    latest_valid_start_time: datetime
    valid: bool
    reason: str


@dataclass(frozen=True)
class _ScheduleDefinition:
    scheduled_times: tuple[time, ...]
    target_day_offset: int
    snapshot_role: str | None = None


def evaluate_scheduled_execution(
    *,
    task_identity: str,
    snapshot_role: str | None = None,
    current_time: datetime | None = None,
) -> ScheduledExecutionValidity:
    """Evaluate one scheduled MLB task against its Pacific start window."""

    normalized_task = task_identity.strip().lower()
    normalized_role = (
        snapshot_role.strip().lower()
        if snapshot_role is not None
        else None
    )
    schedule = _resolve_schedule(
        task_identity=normalized_task,
        snapshot_role=normalized_role,
    )

    resolved_time = (
        current_time
        if current_time is not None
        else datetime.now(timezone.utc)
    )
    if resolved_time.tzinfo is None:
        raise ValueError("Current time must be timezone-aware.")

    current_pacific_time = resolved_time.astimezone(PACIFIC_TIME_ZONE)
    intended_scheduled_time = _most_recent_scheduled_time(
        current_pacific_time=current_pacific_time,
        scheduled_times=schedule.scheduled_times,
    )
    latest_valid_start_time = (
        intended_scheduled_time + EXECUTION_VALIDITY_WINDOW
    )
    intended_target_date = (
        intended_scheduled_time.date()
        + timedelta(days=schedule.target_day_offset)
    )
    valid = current_pacific_time < latest_valid_start_time

    if valid:
        reason = (
            "Execution is within the configured Scheduler retry window."
        )
    else:
        reason = (
            "Execution is outside the configured Scheduler retry window. "
            "Execution was refused to preserve point-in-time correctness. "
            "The missed observation must not be backfilled."
        )

    return ScheduledExecutionValidity(
        task_identity=normalized_task,
        snapshot_role=schedule.snapshot_role,
        intended_target_date=intended_target_date,
        current_pacific_time=current_pacific_time,
        intended_scheduled_time=intended_scheduled_time,
        latest_valid_start_time=latest_valid_start_time,
        valid=valid,
        reason=reason,
    )


def _resolve_schedule(
    *,
    task_identity: str,
    snapshot_role: str | None,
) -> _ScheduleDefinition:
    if task_identity not in SCHEDULED_TASK_IDENTITIES:
        raise ValueError(
            f"Unsupported scheduled task identity: {task_identity}"
        )

    if task_identity == MONEYLINE_ODDS_SNAPSHOT_TASK:
        if snapshot_role not in SNAPSHOT_SCHEDULES:
            raise ValueError(
                "A supported snapshot role is required for the scheduled "
                "Moneyline odds snapshot task."
            )
        target_day_offset = (
            1
            if snapshot_role in {"opening", "evening", "late_night"}
            else 0
        )
        return _ScheduleDefinition(
            scheduled_times=(SNAPSHOT_SCHEDULES[snapshot_role],),
            target_day_offset=target_day_offset,
            snapshot_role=snapshot_role,
        )

    if snapshot_role is not None:
        raise ValueError(
            "Snapshot role is only valid for the Moneyline odds snapshot "
            "task."
        )

    if task_identity == MONEYLINE_PREGAME_TASK:
        return _ScheduleDefinition(
            scheduled_times=(time(8, 0),),
            target_day_offset=0,
        )

    if task_identity == MONEYLINE_POSTGAME_TASK:
        return _ScheduleDefinition(
            scheduled_times=(time(7, 15), time(13, 15)),
            target_day_offset=-1,
        )

    return _ScheduleDefinition(
        scheduled_times=(time(18, 45),),
        target_day_offset=1,
    )


def _most_recent_scheduled_time(
    *,
    current_pacific_time: datetime,
    scheduled_times: tuple[time, ...],
) -> datetime:
    candidate_dates = (
        current_pacific_time.date(),
        current_pacific_time.date() - timedelta(days=1),
    )
    candidates = tuple(
        datetime.combine(
            candidate_date,
            scheduled_time,
            tzinfo=PACIFIC_TIME_ZONE,
        )
        for candidate_date in candidate_dates
        for scheduled_time in scheduled_times
    )
    return max(
        candidate
        for candidate in candidates
        if candidate <= current_pacific_time
    )
