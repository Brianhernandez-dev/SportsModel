"""Run the reproducible nflverse Phase 1 schedules coverage audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from sportsmodel.nfl.coverage_audit import audit, select_rows


CANONICAL_NFLVERSE_TEAM_IDS = {
    "0200", "0325", "0610", "0750", "0810", "0920", "1050", "1200",
    "1400", "1540", "1800", "2100", "2120", "2200", "2250", "2310",
    "2510", "2520", "2700", "3000", "3200", "3300", "3410", "3430",
    "3700", "3800", "3900", "4400", "4500", "4600", "4900", "5110",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _print_summary(result: dict) -> None:
    print("season regular postseason total unique_ids duplicate_ids teams final unplayed overtime ties neutral")
    for row in result["coverage"]:
        print("{season} {regular_rows} {postseason_rows} {total_rows} {unique_game_ids} {duplicate_game_ids} {unique_teams} {final_games} {unplayed_games} {overtime_games} {tied_games} {neutral_site_games}".format(**row))
    parser = result["parser"]
    print(f"parser attempted={parser['attempted']} succeeded={parser['succeeded']} rejected={parser['rejected']} rejection_percentage={parser['rejection_percentage']:.6f}")
    print("validation_categories=" + str(len(result["validation_findings"])))
    print("unresolved_team_abbreviations=" + ",".join(result["teams"]["unresolved_abbreviations"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedules", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--season-from", type=int, default=2018)
    parser.add_argument("--season-to", type=int, default=2025)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--retrieved-at", required=True, help="ISO-8601 retrieval time recorded by the caller")
    args = parser.parse_args()
    rows = _read_csv(args.schedules)
    team_rows = _read_csv(args.teams)
    result = audit(rows, team_rows, season_from=args.season_from, season_to=args.season_to, canonical_ids=CANONICAL_NFLVERSE_TEAM_IDS)
    future = select_rows(rows, 2026, 2026)
    result["future_2026"] = {
        "rows": len(future),
        "unplayed_rows": sum(not row.get("home_score") and not row.get("away_score") for row in future),
        "sample_game_ids": [row["game_id"] for row in future[:5]],
    }
    result["provenance"] = {
        "source": "nflverse/nflverse-data static GitHub release assets",
        "schedules_asset": "releases/download/schedules/games.csv",
        "teams_asset": "releases/download/teams/teams_colors_logos.csv",
        "schedules_sha256": _sha256(args.schedules),
        "teams_sha256": _sha256(args.teams),
        "retrieved_at": args.retrieved_at,
        "schedule_asset_rows": len(rows),
        "team_asset_rows": len(team_rows),
    }
    _print_summary(result)
    if args.json_output:
        args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
