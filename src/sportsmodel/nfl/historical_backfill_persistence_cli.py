"""Explicitly confirmed CLI for validated NFL historical persistence."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Callable, TextIO
from urllib.parse import urlparse

import psycopg2

from sportsmodel.nfl.historical_backfill_cli import (
    HistoricalBackfillInputError,
    prepare_historical_backfill,
)
from sportsmodel.nfl.historical_backfill_persistence import (
    HistoricalBackfillValidationError,
    persist_validated_historical_backfill,
    validate_prepared_for_persistence,
)


INPUT_ERROR = 2
BLOCKED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Persist a validated NFL historical snapshot."
    )
    parser.add_argument("--schedules", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--team-stats-dir", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--database-url")
    parser.add_argument("--confirm-persist", action="store_true")
    parser.add_argument("--season-from", type=int, default=2018)
    parser.add_argument("--season-to", type=int, default=2025)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    connect: Callable[[str], Any] = psycopg2.connect,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = build_parser().parse_args(argv)
    if not args.confirm_persist:
        print("INPUT ERROR: --confirm-persist is required", file=stderr)
        return INPUT_ERROR
    if not args.database_url:
        print("INPUT ERROR: --database-url is required", file=stderr)
        return INPUT_ERROR
    try:
        target_description = describe_database_target(args.database_url)
        prepared = prepare_historical_backfill(
            schedules_path=args.schedules,
            teams_path=args.teams,
            team_stats_dir=args.team_stats_dir,
            retrieved_at=args.retrieved_at,
            season_from=args.season_from,
            season_to=args.season_to,
        )
        validate_prepared_for_persistence(prepared)
    except HistoricalBackfillInputError as error:
        print(f"INPUT ERROR: {error}", file=stderr)
        return INPUT_ERROR
    except HistoricalBackfillValidationError as error:
        print(f"VALIDATION ERROR: {error}", file=stderr)
        return BLOCKED

    print(f"Target database: {target_description}", file=stdout)
    connection = connect(args.database_url)
    try:
        result = persist_validated_historical_backfill(
            connection, prepared=prepared
        )
    finally:
        connection.close()
    print(
        "Schedule processed / inserted / updated / quarantined: "
        f"{result.schedule.rows_processed} / {result.schedule.rows_inserted} / "
        f"{result.schedule.rows_updated} / {result.schedule.rows_quarantined}",
        file=stdout,
    )
    print(
        "Team statistics processed / inserted / updated: "
        f"{result.team_statistics.processed} / "
        f"{result.team_statistics.inserted} / {result.team_statistics.updated}",
        file=stdout,
    )
    print("INTEGRITY READY: " + ("YES" if result.integrity.ready else "NO"), file=stdout)
    return 0 if result.integrity.ready else BLOCKED


def describe_database_target(database_url: str) -> str:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise HistoricalBackfillInputError("--database-url must be a PostgreSQL URL")
    database = parsed.path.lstrip("/") or "<unspecified>"
    try:
        port = parsed.port or 5432
    except ValueError as error:
        raise HistoricalBackfillInputError(
            "--database-url contains an invalid port"
        ) from error
    return f"host={parsed.hostname} port={port} database={database}"
