"""Database-free CLI for validating local nflverse historical assets."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
from io import StringIO
import json
from pathlib import Path
import sys
from typing import Any, TextIO

from sportsmodel.nfl.historical_backfill import (
    HistoricalBackfillPlan,
    build_nflverse_historical_backfill_plan,
)
from sportsmodel.nfl.nflverse_parser import (
    build_nflverse_team_identity_index,
    parse_nflverse_team_records,
)


INPUT_ERROR = 2
BLOCKING_ISSUES = 1
APPROVED_SEASON_RANGE = (2018, 2025)
APPROVED_SCHEDULE_ROWS = 2227


class HistoricalBackfillInputError(ValueError):
    """An invalid CLI option or local source asset."""


@dataclass(frozen=True)
class AssetProvenance:
    logical_role: str
    season: int | None
    path: str
    byte_size: int
    row_count: int
    sha256: str
    retrieved_at: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate local nflverse historical assets without writes."
    )
    parser.add_argument("--schedules", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--team-stats-dir", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--season-from", type=int, default=2018)
    parser.add_argument("--season-to", type=int, default=2025)
    parser.add_argument("--json-output", type=Path)
    return parser


def build_historical_backfill_report(
    *,
    schedules_path: Path,
    teams_path: Path,
    team_stats_dir: Path,
    retrieved_at: str,
    season_from: int = 2018,
    season_to: int = 2025,
) -> dict[str, Any]:
    """Read explicit local assets and return a deterministic dry-run report."""

    _validate_inputs(retrieved_at, season_from, season_to, team_stats_dir)
    schedule_rows, schedule_provenance = _read_csv_asset(
        schedules_path, "schedules", None, retrieved_at
    )
    team_rows, teams_provenance = _read_csv_asset(
        teams_path, "teams", None, retrieved_at
    )
    try:
        identities = build_nflverse_team_identity_index(
            parse_nflverse_team_records(team_rows)
        )
    except (TypeError, ValueError) as error:
        raise HistoricalBackfillInputError(
            f"Invalid teams asset {teams_path}: {error}"
        ) from error

    all_stats: list[dict[str, str]] = []
    provenance = [schedule_provenance, teams_provenance]
    for season in range(season_from, season_to + 1):
        path = team_stats_dir / f"stats_team_week_{season}.csv"
        if not path.is_file():
            raise HistoricalBackfillInputError(
                f"Missing required team-statistics asset for {season}: {path}"
            )
        rows, asset = _read_csv_asset(
            path, "team_statistics", season, retrieved_at
        )
        all_stats.extend(rows)
        provenance.append(asset)

    plan = build_nflverse_historical_backfill_plan(
        schedule_rows,
        all_stats,
        team_identities=identities,
        season_from=season_from,
        season_to=season_to,
    )
    return _report_from_plan(
        plan,
        schedule_asset_rows=len(schedule_rows),
        statistics_asset_rows=len(all_stats),
        provenance=provenance,
    )


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        report = build_historical_backfill_report(
            schedules_path=args.schedules,
            teams_path=args.teams,
            team_stats_dir=args.team_stats_dir,
            retrieved_at=args.retrieved_at,
            season_from=args.season_from,
            season_to=args.season_to,
        )
        if args.json_output is not None:
            args.json_output.write_text(
                deterministic_json(report), encoding="utf-8"
            )
    except (HistoricalBackfillInputError, OSError) as error:
        print(f"INPUT ERROR: {error}", file=stderr)
        return INPUT_ERROR

    print(_human_summary(report), file=stdout)
    return 0 if report["backfill_ready"] else BLOCKING_ISSUES


def deterministic_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _read_csv_asset(
    path: Path,
    logical_role: str,
    season: int | None,
    retrieved_at: str,
) -> tuple[list[dict[str, str]], AssetProvenance]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise HistoricalBackfillInputError(
            f"Cannot read {logical_role} asset {path}: {error}"
        ) from error
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HistoricalBackfillInputError(
            f"Asset is not valid UTF-8: {path}"
        ) from error
    try:
        reader = csv.DictReader(StringIO(text, newline=""))
        if reader.fieldnames is None:
            raise HistoricalBackfillInputError(f"CSV has no header: {path}")
        rows = [dict(row) for row in reader]
    except csv.Error as error:
        raise HistoricalBackfillInputError(
            f"Invalid CSV asset {path}: {error}"
        ) from error
    return rows, AssetProvenance(
        logical_role=logical_role,
        season=season,
        path=str(path.resolve()),
        byte_size=len(content),
        row_count=len(rows),
        sha256=hashlib.sha256(content).hexdigest(),
        retrieved_at=retrieved_at,
    )


def _validate_inputs(
    retrieved_at: str,
    season_from: int,
    season_to: int,
    team_stats_dir: Path,
) -> None:
    try:
        parsed_retrieved_at = datetime.fromisoformat(
            retrieved_at.replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as error:
        raise HistoricalBackfillInputError(
            f"--retrieved-at must be ISO8601: {retrieved_at!r}"
        ) from error
    if (
        parsed_retrieved_at.tzinfo is None
        or parsed_retrieved_at.utcoffset() is None
    ):
        raise HistoricalBackfillInputError(
            "--retrieved-at must include an explicit timezone: "
            f"{retrieved_at!r}"
        )
    if season_from > season_to:
        raise HistoricalBackfillInputError(
            "--season-from cannot be greater than --season-to"
        )
    if not team_stats_dir.is_dir():
        raise HistoricalBackfillInputError(
            f"Team-statistics directory does not exist: {team_stats_dir}"
        )


def _report_from_plan(
    plan: HistoricalBackfillPlan,
    *,
    schedule_asset_rows: int,
    statistics_asset_rows: int,
    provenance: list[AssetProvenance],
) -> dict[str, Any]:
    issue_counts = Counter(issue.category for issue in plan.issues)
    selected_schedule = len(plan.selected_schedule_rows)
    accepted_schedule = len(plan.accepted_schedule_rows)
    quarantined_schedule = len(plan.quarantined_schedule_rows)
    report: dict[str, Any] = {
        "season_from": plan.season_from,
        "season_to": plan.season_to,
        "schedule": {
            "asset_rows": schedule_asset_rows,
            "selected_rows": selected_schedule,
            "accepted_rows": accepted_schedule,
            "quarantined_rows": quarantined_schedule,
        },
        "team_statistics": {
            "asset_rows_total": statistics_asset_rows,
            "selected_rows": len(plan.selected_team_statistics_rows),
            "accepted_rows": len(plan.accepted_team_statistics_rows),
            "rejected_rows": (
                len(plan.selected_team_statistics_rows)
                - len(plan.accepted_team_statistics_rows)
            ),
        },
        "reconciliation": {
            "issue_count": len(plan.issues),
            "issue_counts_by_category": dict(sorted(issue_counts.items())),
            "issues": [asdict(issue) for issue in plan.issues],
        },
        "special_checks": {
            "reviewed_override_game_ids": list(plan.reviewed_override_game_ids),
            "cancelled_buf_cin_absent": plan.cancelled_buf_cin_absent,
        },
        "approved_schedule_contract": None,
        "provenance": [asdict(asset) for asset in provenance],
        "backfill_ready": plan.is_valid,
    }
    if (plan.season_from, plan.season_to) == APPROVED_SEASON_RANGE:
        unique_ids = len({
            str(row.get("game_id"))
            for row in plan.selected_schedule_rows
            if row.get("game_id")
        })
        contract = {
            "expected_schedule_rows": APPROVED_SCHEDULE_ROWS,
            "expected_unique_historical_schedule_identities": APPROVED_SCHEDULE_ROWS,
            "selected_schedule_rows_match": selected_schedule == APPROVED_SCHEDULE_ROWS,
            "accepted_schedule_rows_match": accepted_schedule == APPROVED_SCHEDULE_ROWS,
            "quarantined_schedule_rows_match": quarantined_schedule == 0,
            "unique_historical_schedule_identities": unique_ids,
            "unique_historical_schedule_identities_match": unique_ids == APPROVED_SCHEDULE_ROWS,
        }
        contract["contract_satisfied"] = all((
            contract["selected_schedule_rows_match"],
            contract["accepted_schedule_rows_match"],
            contract["quarantined_schedule_rows_match"],
            contract["unique_historical_schedule_identities_match"],
        ))
        report["approved_schedule_contract"] = contract
        report["backfill_ready"] = (
            plan.is_valid and contract["contract_satisfied"]
        )
    return report


def _human_summary(report: dict[str, Any]) -> str:
    schedule = report["schedule"]
    stats = report["team_statistics"]
    reconciliation = report["reconciliation"]
    special = report["special_checks"]
    categories = reconciliation["issue_counts_by_category"]
    category_text = ", ".join(
        f"{name}={count}" for name, count in categories.items()
    ) or "none"
    reviewed = ", ".join(special["reviewed_override_game_ids"]) or "none"
    return "\n".join((
        "NFL Historical Backfill Dry Run",
        f"Seasons: {report['season_from']}-{report['season_to']}",
        "Schedule selected / accepted / quarantined: "
        f"{schedule['selected_rows']} / {schedule['accepted_rows']} / {schedule['quarantined_rows']}",
        "Team-stat selected / accepted: "
        f"{stats['selected_rows']} / {stats['accepted_rows']}",
        f"Issue count: {reconciliation['issue_count']}",
        f"Issue categories: {category_text}",
        f"Reviewed Wembley IDs: {reviewed}",
        "BUF-CIN absent: " + ("YES" if special["cancelled_buf_cin_absent"] else "NO"),
        "BACKFILL READY: " + ("YES" if report["backfill_ready"] else "NO"),
    ))
