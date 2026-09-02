from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime

from sportsmodel.orchestration.scheduled_execution import (
    MONEYLINE_ODDS_SNAPSHOT_TASK,
    SCHEDULED_TASK_IDENTITIES,
    SNAPSHOT_SCHEDULES,
    evaluate_scheduled_execution,
)


def main(
    arguments: Sequence[str] | None = None,
    *,
    current_time: datetime | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refuse stale SportsModel MLB scheduled task executions."
        )
    )
    parser.add_argument(
        "--task-identity",
        required=True,
        choices=sorted(SCHEDULED_TASK_IDENTITIES),
    )
    parser.add_argument(
        "--snapshot-role",
        choices=sorted(SNAPSHOT_SCHEDULES),
    )
    parsed = parser.parse_args(arguments)

    if (
        parsed.task_identity == MONEYLINE_ODDS_SNAPSHOT_TASK
        and parsed.snapshot_role is None
    ):
        parser.error(
            "--snapshot-role is required for the odds snapshot task."
        )
    if (
        parsed.task_identity != MONEYLINE_ODDS_SNAPSHOT_TASK
        and parsed.snapshot_role is not None
    ):
        parser.error(
            "--snapshot-role is only valid for the odds snapshot task."
        )

    validity = evaluate_scheduled_execution(
        task_identity=parsed.task_identity,
        snapshot_role=parsed.snapshot_role,
        current_time=current_time,
    )

    print(
        "Scheduled execution validity: "
        f"{'VALID' if validity.valid else 'EXPIRED'}"
    )
    print(f"Task identity: {validity.task_identity}")
    if validity.snapshot_role is not None:
        print(f"Snapshot role: {validity.snapshot_role}")
    print(f"Intended target date: {validity.intended_target_date}")
    print(
        "Current Pacific time: "
        f"{validity.current_pacific_time.isoformat()}"
    )
    print(
        "Intended scheduled time: "
        f"{validity.intended_scheduled_time.isoformat()}"
    )
    print(
        "Valid start window: ["
        f"{validity.intended_scheduled_time.isoformat()}, "
        f"{validity.latest_valid_start_time.isoformat()})"
    )
    print(validity.reason)

    return 0 if validity.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
