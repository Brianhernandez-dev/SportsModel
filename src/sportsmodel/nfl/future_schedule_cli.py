"""Guarded operator CLI for nflverse future regular-season schedules."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from hashlib import sha256
from io import StringIO
from pathlib import Path
import sys
from typing import Any, Callable, TextIO

from sportsmodel.database.connection import get_connection
from sportsmodel.nfl.future_schedule import (
    FutureSchedulePlan,
    build_future_schedule_plan,
    persist_future_schedule,
    utc_text,
)


INPUT_ERROR = 2
BLOCKED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or explicitly persist one nflverse future regular-season "
            "schedule. Default is read-only."
        )
    )
    parser.add_argument("--schedules", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--expected-schedule-sha256")
    parser.add_argument("--expected-teams-sha256")
    parser.add_argument("--confirm-persist", action="store_true")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    connection_factory: Callable[[], Any] = get_connection,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        retrieved_at = _aware_datetime(args.retrieved_at)
        schedule_rows, schedule_hash = _read_csv(args.schedules)
        team_rows, teams_hash = _read_csv(args.teams)
        _validate_hash(
            schedule_hash,
            args.expected_schedule_sha256,
            "schedule",
            required=args.confirm_persist,
        )
        _validate_hash(
            teams_hash,
            args.expected_teams_sha256,
            "teams",
            required=args.confirm_persist,
        )
    except (OSError, ValueError) as error:
        print(f"INPUT ERROR: {error}", file=stderr)
        return INPUT_ERROR

    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            plan = build_future_schedule_plan(
                cursor,
                schedule_rows=schedule_rows,
                team_rows=team_rows,
                season=args.season,
            )
        connection.rollback()
        _print_plan(plan, schedule_hash, teams_hash, stdout)
        if not plan.ready:
            return BLOCKED
        if not args.confirm_persist:
            print("MODE: DRY RUN - production writes NONE", file=stdout)
            return 0
        result = persist_future_schedule(
            connection,
            plan=plan,
            source_asset=str(args.schedules.resolve()),
            source_sha256=schedule_hash,
            retrieved_at=retrieved_at,
        )
    except Exception as error:
        connection.rollback()
        print(f"SCHEDULE ERROR: {type(error).__name__}: {error}", file=stderr)
        return BLOCKED
    finally:
        connection.close()

    print("MODE: CONFIRMED PERSIST", file=stdout)
    print(f"Ingestion run ID: {result.nfl_ingestion_run_id}", file=stdout)
    print(
        "Processed / inserted / updated / skipped: "
        f"{result.rows_processed} / {result.rows_inserted} / "
        f"{result.rows_updated} / {result.rows_skipped}",
        file=stdout,
    )
    return 0


def _read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    content = path.read_bytes()
    text = content.decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(text, newline="")))
    if not rows:
        raise ValueError(f"CSV asset is empty: {path}")
    return rows, sha256(content).hexdigest()


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("--retrieved-at must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--retrieved-at must include a timezone")
    return parsed


def _validate_hash(
    actual: str,
    expected: str | None,
    label: str,
    *,
    required: bool,
) -> None:
    if required and not expected:
        raise ValueError(
            f"--expected-{label}-sha256 is required with --confirm-persist"
        )
    if expected is not None and actual != expected.lower():
        raise ValueError(
            f"{label} SHA-256 mismatch: expected {expected.lower()}, actual {actual}"
        )


def _print_plan(
    plan: FutureSchedulePlan,
    schedule_hash: str,
    teams_hash: str,
    stdout: TextIO,
) -> None:
    print("NFL Future Schedule Dry Run", file=stdout)
    print(f"Season: {plan.season}", file=stdout)
    print(f"Schedule SHA-256: {schedule_hash}", file=stdout)
    print(f"Teams SHA-256: {teams_hash}", file=stdout)
    print(f"Source games discovered: {plan.source_rows_discovered}", file=stdout)
    print(f"Game types: {dict(plan.source_game_type_counts)}", file=stdout)
    print(f"Excluded non-regular rows: {plan.excluded_non_regular_rows}", file=stdout)
    print(
        "New / update / existing: "
        f"{plan.count('new')} / {plan.count('update')} / "
        f"{plan.count('existing')}",
        file=stdout,
    )
    print(f"Conflicts/errors: {len(plan.issues)}", file=stdout)
    print(f"Earliest kickoff UTC: {utc_text(plan.earliest_kickoff)}", file=stdout)
    print(f"Latest kickoff UTC: {utc_text(plan.latest_kickoff)}", file=stdout)
    for issue in plan.issues:
        print(
            f"ISSUE {issue.category} {issue.external_game_id}: {issue.detail}",
            file=stdout,
        )
    print("DRY-RUN READY: " + ("YES" if plan.ready else "NO"), file=stdout)


if __name__ == "__main__":
    raise SystemExit(main())
