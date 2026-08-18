from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsmodel.nfl.early_dataset_audit import (
    build_and_audit_production_early_dataset,
)
from sportsmodel.nfl.early_moneyline_dataset import (
    NFL_EARLY_DEVELOPMENT_SEASON_FROM,
    NFL_EARLY_DEVELOPMENT_SEASON_TO,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build and independently audit the guarded 2019-2024 NFL "
            "early-season Moneyline dataset."
        )
    )
    parser.add_argument(
        "--season-from",
        type=int,
        default=NFL_EARLY_DEVELOPMENT_SEASON_FROM,
    )
    parser.add_argument(
        "--season-to",
        type=int,
        default=NFL_EARLY_DEVELOPMENT_SEASON_TO,
    )
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    first = build_and_audit_production_early_dataset(
        season_from=args.season_from,
        season_to=args.season_to,
    )
    second = build_and_audit_production_early_dataset(
        season_from=args.season_from,
        season_to=args.season_to,
    )
    reproducible = (
        first.fingerprint == second.fingerprint
        and first.dataset == second.dataset
        and first.report == second.report
    )
    report = dict(first.report)
    report["fingerprint"] = first.fingerprint
    report["repeat_fingerprint"] = second.fingerprint
    report["reproducible"] = reproducible

    print("NFL Early-Season Moneyline Dataset Audit (2019-2024 Guarded)")
    print("=" * 72)
    print(f"Dataset rows: {report['dataset_rows']}")
    print(
        "Early rows by season: "
        f"{report['early_route_counts_by_season']}"
    )
    print(
        "Minimum current prior games: "
        f"{report['minimum_current_prior_game_counts']}"
    )
    print(
        "Canonical targets by season: "
        f"{report['canonical_target_counts_by_season']}"
    )
    print(
        "Prior-season source coverage: "
        f"{report['prior_season_source_coverage_by_target_season']}"
    )
    print(
        "Prior-season games-used distribution: "
        f"{report['prior_season_games_used_distribution']}"
    )
    print(
        "Current-season history distribution: "
        f"{report['current_season_history_distribution']}"
    )
    print(
        "Numeric feature null rates: "
        f"{report['numeric_feature_null_rates']}"
    )
    print(f"Schema versions: {report['feature_schema_versions']}")
    print(f"Fingerprint: {first.fingerprint}")
    print(f"Repeat fingerprint: {second.fingerprint}")
    print(f"Reproducible: {'YES' if reproducible else 'NO'}")
    print(
        "Integrity passed: "
        f"{'YES' if report['integrity_passed'] else 'NO'}"
    )
    print(f"Integrity findings: {len(report['integrity_findings'])}")

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )

    return 0 if report["integrity_passed"] and reproducible else 1


if __name__ == "__main__":
    raise SystemExit(main())
