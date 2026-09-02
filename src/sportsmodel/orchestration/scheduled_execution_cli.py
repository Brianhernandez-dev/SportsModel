from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import date, datetime

from sportsmodel.orchestration.scheduled_execution import (
    MONEYLINE_ODDS_SNAPSHOT_TASK,
    MONEYLINE_PREGAME_TASK,
    SCHEDULED_TASK_IDENTITIES,
    SNAPSHOT_SCHEDULES,
    ScheduledExecutionValidity,
    evaluate_scheduled_execution,
)


SemanticDeadlineLoader = Callable[[date], datetime | None]


def main(
    arguments: Sequence[str] | None = None,
    *,
    current_time: datetime | None = None,
    semantic_deadline_loader: SemanticDeadlineLoader | None = None,
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
    parser.add_argument(
        "--enforce-canonical-pregame-deadline",
        action="store_true",
        help=(
            "Cap Pregame execution at the earliest canonical MLB game "
            "start for its intended Pacific target date."
        ),
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
    if (
        parsed.enforce_canonical_pregame_deadline
        and parsed.task_identity != MONEYLINE_PREGAME_TASK
    ):
        parser.error(
            "--enforce-canonical-pregame-deadline is only valid for "
            "the Moneyline Pregame task."
        )

    validity = evaluate_scheduled_execution(
        task_identity=parsed.task_identity,
        snapshot_role=parsed.snapshot_role,
        current_time=current_time,
    )

    if parsed.enforce_canonical_pregame_deadline and validity.valid:
        loader = (
            semantic_deadline_loader
            if semantic_deadline_loader is not None
            else _load_canonical_pregame_deadline
        )

        try:
            semantic_deadline = loader(
                validity.intended_target_date
            )
        except Exception as error:
            _print_validity(validity)
            print(
                "Canonical Pregame deadline: UNKNOWN. "
                "Execution was refused before live workflow or provider "
                f"execution: {type(error).__name__}: {error}"
            )
            return 1

        if semantic_deadline is None:
            _print_validity(validity)
            print(
                "Canonical Pregame deadline: UNKNOWN. No canonical MLB "
                f"games exist for target date {validity.intended_target_date}. "
                "Execution was refused before live workflow or provider "
                "execution."
            )
            return 1

        validity = evaluate_scheduled_execution(
            task_identity=parsed.task_identity,
            snapshot_role=parsed.snapshot_role,
            current_time=current_time,
            semantic_deadline=semantic_deadline,
        )

    _print_validity(validity)

    return 0 if validity.valid else 1


def _print_validity(validity: ScheduledExecutionValidity) -> None:
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
        "Operational latest valid start: "
        f"{validity.operational_latest_valid_start_time.isoformat()}"
    )
    if validity.semantic_deadline is not None:
        print(
            "Semantic point-in-time deadline: "
            f"{validity.semantic_deadline.isoformat()}"
        )
    print(
        "Valid start window: ["
        f"{validity.intended_scheduled_time.isoformat()}, "
        f"{validity.latest_valid_start_time.isoformat()})"
    )
    print(validity.reason)


def _load_canonical_pregame_deadline(
    target_date: date,
) -> datetime | None:
    from sportsmodel.database.scheduled_execution_repository import (
        get_earliest_mlb_game_start_for_pacific_date,
    )

    return get_earliest_mlb_game_start_for_pacific_date(target_date)


if __name__ == "__main__":
    raise SystemExit(main())
