from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from sportsmodel.nfl.dataset_audit import build_and_audit_production_dataset
from sportsmodel.nfl.moneyline_holdout import (
    FROZEN_NFL_BASELINE_SPECIFICATION,
    nfl_final_holdout_evaluation_to_dict,
    run_guarded_final_nfl_holdout_evaluation,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the one-time frozen NFL 2025 historical holdout evaluation."
    )
    parser.add_argument(
        "--confirm-final-2025-holdout",
        action="store_true",
        help=(
            "Explicitly acknowledge that this exposes the final historical "
            "2025-season holdout."
        ),
    )
    parser.add_argument("--json-output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if not arguments.confirm_final_2025_holdout:
        parser.error(
            "refusing before any holdout load: pass "
            "--confirm-final-2025-holdout for the one-time final evaluation"
        )

    spec = FROZEN_NFL_BASELINE_SPECIFICATION

    def development_loader():
        outcome = build_and_audit_production_dataset(
            season_from=spec.training_seasons[0],
            season_to=spec.training_seasons[-1],
        )
        _require_integrity(outcome.report, "development")
        return tuple(outcome.dataset.rows), tuple(outcome.canonical_games)

    def holdout_loader():
        outcome = build_and_audit_production_dataset(
            season_from=spec.holdout_season,
            season_to=spec.holdout_season,
        )
        _require_integrity(outcome.report, "final holdout")
        return tuple(outcome.dataset.rows), tuple(outcome.canonical_games)

    evaluation = run_guarded_final_nfl_holdout_evaluation(
        confirmed=True,
        development_loader=development_loader,
        holdout_loader=holdout_loader,
    )
    report = nfl_final_holdout_evaluation_to_dict(evaluation)
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print("THIS IS THE FINAL HISTORICAL 2025 HOLDOUT EVALUATION")
    print("BASELINE SPECIFICATION WAS FROZEN BEFORE HOLDOUT EXPOSURE")
    print(f"Eligible holdout rows: {evaluation.holdout_rows_eligible}")
    print(f"Excluded holdout rows: {evaluation.holdout_rows_excluded}")
    print(f"Report fingerprint: {evaluation.report_fingerprint}")
    print(f"Report written to: {arguments.json_output}")
    return 0


def _require_integrity(report: dict[str, object], population: str) -> None:
    if not report.get("integrity_passed"):
        raise RuntimeError(f"audited NFL {population} dataset has integrity findings")


if __name__ == "__main__":
    raise SystemExit(main())
