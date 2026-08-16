from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sportsmodel.nfl.dataset_audit import build_and_audit_production_dataset


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and audit the historical NFL Moneyline PIT dataset."
    )
    parser.add_argument("--season-from", type=int, default=2018)
    parser.add_argument("--season-to", type=int, default=2025)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    args = parser.parse_args()

    first = build_and_audit_production_dataset(
        season_from=args.season_from,
        season_to=args.season_to,
    )
    second = build_and_audit_production_dataset(
        season_from=args.season_from,
        season_to=args.season_to,
    )
    reproducible = (
        first.fingerprint == second.fingerprint
        and first.dataset.rows == second.dataset.rows
    )
    report = dict(first.report)
    report["fingerprint"] = first.fingerprint
    report["repeat_fingerprint"] = second.fingerprint
    report["reproducible"] = reproducible

    population = report["population"]
    balance = report["class_balance"]
    print("NFL Historical Moneyline Dataset Audit")
    print("=" * 72)
    print(f"Canonical games: {population['canonical_games']}")
    print(f"Eligible targets: {population['eligible_targets']}")
    print(f"Dataset rows: {report['dataset_rows']}")
    print(f"Excluded ties: {report['excluded_ties']}")
    print(f"Home wins/losses: {balance['home_wins']}/{balance['home_losses']}")
    print(f"Home win rate: {balance['home_win_rate']:.6f}")
    print(f"Fingerprint: {first.fingerprint}")
    print(f"Reproducible: {'YES' if reproducible else 'NO'}")
    print(f"Integrity passed: {'YES' if report['integrity_passed'] else 'NO'}")
    print(f"Integrity findings: {len(report['integrity_findings'])}")

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    if args.csv_output:
        _write_csv(args.csv_output, first.dataset.rows)

    return 0 if report["integrity_passed"] and reproducible else 1


def _write_csv(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    if not rows:
        raise RuntimeError("No NFL Moneyline dataset rows were generated")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
