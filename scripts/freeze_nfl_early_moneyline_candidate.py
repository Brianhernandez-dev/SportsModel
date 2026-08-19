from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sportsmodel.nfl.early_dataset_audit import (
    build_and_audit_production_early_dataset,
)
from sportsmodel.nfl.early_moneyline_baseline import (
    assert_nfl_early_production_dataset_contract,
    build_nfl_early_modeling_examples,
)
from sportsmodel.nfl.early_moneyline_frozen import (
    FROZEN_NFL_EARLY_RETROSPECTIVE_LABEL,
    assert_committed_frozen_nfl_early_artifact,
    fit_frozen_nfl_early_candidate,
    frozen_nfl_early_artifact_to_dict,
)


COMMITTED_ARTIFACT = Path("artifacts/nfl_moneyline_early_frozen_0.1.0.json")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce the frozen NFL early candidate metadata. Historical "
            "output is consistency-only and is not validation."
        )
    )
    parser.add_argument("--print-json", action="store_true")
    arguments = parser.parse_args()

    audited = build_and_audit_production_early_dataset(
        season_from=2019,
        season_to=2024,
    )
    if not audited.report["integrity_passed"]:
        raise RuntimeError("frozen early source dataset has integrity findings")
    assert_nfl_early_production_dataset_contract(
        audited.dataset.rows,
        audited.fingerprint,
    )
    examples = build_nfl_early_modeling_examples(audited.dataset.rows)
    first = fit_frozen_nfl_early_candidate(
        examples,
        dataset_fingerprint=audited.fingerprint,
    )
    second = fit_frozen_nfl_early_candidate(
        examples,
        dataset_fingerprint=audited.fingerprint,
    )
    if first != second:
        raise RuntimeError("frozen NFL early fit is not deterministic")
    if COMMITTED_ARTIFACT.exists():
        committed = json.loads(COMMITTED_ARTIFACT.read_text(encoding="utf-8"))
        assert_committed_frozen_nfl_early_artifact(first, committed)

    print(FROZEN_NFL_EARLY_RETROSPECTIVE_LABEL)
    print("NOT HOLDOUT VALIDATION")
    print("NOT INDEPENDENT MODEL EVIDENCE")
    print("=" * 78)
    print(f"Specification: {first.specification_version}")
    print(f"Feature schema: {first.feature_schema_version}")
    print(f"Learned features: {first.feature_names}")
    print(
        "Model: LogisticRegression("
        f"C={first.regularization_c}, solver='{first.solver}', "
        f"max_iter={first.max_iterations}, random_state={first.random_state})"
    )
    print(f"Imputation: {first.imputation}")
    print(f"Scaling: {first.scaling}")
    print(f"Training seasons: {first.training_seasons}")
    print(f"Training rows: {first.training_row_count}")
    print(f"Training home-win rate: {first.training_home_win_rate:.12f}")
    print(f"Dataset fingerprint: {first.dataset_fingerprint}")
    print(f"Specification fingerprint: {first.specification_fingerprint}")
    print(f"Model fingerprint: {first.model_fingerprint}")
    print(f"Imputer statistics: {first.imputer_statistics}")
    print(f"Scaler means: {first.scaler_means}")
    print(f"Scaler scales: {first.scaler_scales}")
    print(f"Intercept: {first.intercept:+.12f}")
    print(f"Coefficients: {first.coefficients}")
    print(f"Evidence: {first.historical_evidence_status}")
    print("Deterministic repeated fit: YES")
    print(
        "Committed metadata match: "
        f"{'YES' if COMMITTED_ARTIFACT.exists() else 'NOT YET PRESENT'}"
    )
    if arguments.print_json:
        print(json.dumps(
            frozen_nfl_early_artifact_to_dict(first),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
