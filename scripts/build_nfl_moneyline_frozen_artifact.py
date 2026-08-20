"""Reproduce the frozen 2018-2024 mature NFL model-only artifact."""

from __future__ import annotations

import argparse
from datetime import timezone
import json
from pathlib import Path
from typing import Any, Sequence

from sportsmodel.nfl.dataset_audit import build_and_audit_production_dataset
from sportsmodel.nfl.moneyline_baseline import (
    _matrix,
    _pipeline,
    build_nfl_moneyline_modeling_examples,
)
from sportsmodel.nfl.moneyline_frozen import (
    MATURE_ARTIFACT_PATH,
    MATURE_FEATURE_NAMES,
    fingerprint_payload,
    mature_specification_fingerprint,
    mature_specification_payload,
)


DEFAULT_REFERENCE_REPORT = Path("artifacts/nfl_2025_final_holdout.json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reproduce the frozen mature NFL model-only artifact."
    )
    parser.add_argument("--output", type=Path, default=MATURE_ARTIFACT_PATH)
    parser.add_argument(
        "--reference-report",
        type=Path,
        default=DEFAULT_REFERENCE_REPORT,
    )
    arguments = parser.parse_args(argv)

    payload = reproduce_mature_artifact(arguments.reference_report)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Training rows: {payload['training_row_count']}")
    print(f"Dataset fingerprint: {payload['dataset_fingerprint']}")
    print(f"Model fingerprint: {payload['model_fingerprint']}")
    print(f"Artifact written to: {arguments.output}")
    return 0


def reproduce_mature_artifact(reference_report_path: Path) -> dict[str, Any]:
    outcome = build_and_audit_production_dataset(
        season_from=2018,
        season_to=2024,
    )
    if not outcome.report.get("integrity_passed"):
        raise RuntimeError("audited 2018-2024 mature dataset failed integrity")
    examples = build_nfl_moneyline_modeling_examples(
        outcome.dataset.rows,
        outcome.canonical_games,
    )
    eligible = tuple(
        item
        for item in examples
        if item.home_prior_games >= 3 and item.away_prior_games >= 3
    )
    if {item.season for item in eligible} != set(range(2018, 2025)):
        raise RuntimeError("mature fit does not contain every season 2018-2024")
    if any(item.season == 2025 for item in eligible):
        raise RuntimeError("2025 cannot enter mature model training")
    targets = [item.home_win for item in eligible]
    pipeline = _pipeline(1.0)
    pipeline.fit(_matrix(eligible), targets)
    fitted = {
        "imputer_statistics": [
            float(value)
            for value in pipeline.named_steps["imputer"].statistics_
        ],
        "scaler_means": [
            float(value)
            for value in pipeline.named_steps["scaler"].mean_
        ],
        "scaler_scales": [
            float(value)
            for value in pipeline.named_steps["scaler"].scale_
        ],
        "coefficients": [
            float(value)
            for value in pipeline.named_steps["classifier"].coef_[0]
        ],
        "intercept": float(
            pipeline.named_steps["classifier"].intercept_[0]
        ),
    }
    reference = json.loads(reference_report_path.read_text(encoding="utf-8"))
    if fitted != reference.get("fitted_training_pipeline"):
        raise RuntimeError(
            "reproduced 2018-2024 fit differs from frozen holdout-era pipeline"
        )
    if len(eligible) != reference.get("training_rows_eligible"):
        raise RuntimeError("reproduced mature training row count drift")
    training_home_rate = sum(targets) / len(targets)
    if training_home_rate != reference.get("training_home_win_rate"):
        raise RuntimeError("reproduced mature training home baseline drift")

    specification = mature_specification_payload()
    payload: dict[str, Any] = {
        **specification,
        "specification_fingerprint": mature_specification_fingerprint(),
        "training_population": (
            "Final non-tied NFL mature-route targets in seasons 2018-2024; "
            "both teams have at least 3 PIT-safe current-season prior games"
        ),
        "training_row_count": len(eligible),
        "training_home_win_rate": training_home_rate,
        "dataset_fingerprint": _training_population_fingerprint(eligible),
        **fitted,
        "historical_evidence_status": (
            "2018-2024 IS THE FROZEN MATURE TRAINING/DEVELOPMENT POPULATION; "
            "2025 IS PERMANENTLY EXPOSED; 2026+ IS FORWARD EVIDENCE."
        ),
        "next_forward_evidence_season": 2026,
        "evidence_status": {
            "2018_2024": "frozen mature training/development population",
            "2025": "permanently exposed historical holdout",
            "2026_plus": "forward evidence",
        },
    }
    payload["model_fingerprint"] = fingerprint_payload(payload)
    if tuple(payload["feature_names"]) != MATURE_FEATURE_NAMES:
        raise RuntimeError("mature artifact ordered feature contract drift")
    return payload


def _training_population_fingerprint(examples) -> str:
    return fingerprint_payload([
        {
            "game_id": item.game_id,
            "kickoff": item.kickoff.astimezone(timezone.utc).isoformat(),
            "season": item.season,
            "season_type": item.season_type.value,
            "home_win": item.home_win,
            "home_prior_games": item.home_prior_games,
            "away_prior_games": item.away_prior_games,
            "feature_values": list(item.feature_values),
        }
        for item in examples
    ])


if __name__ == "__main__":
    raise SystemExit(main())
