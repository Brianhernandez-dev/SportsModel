"""Leakage-safe historical NFL probability evidence package construction."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
import csv
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import re
from typing import Any

from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from sportsmodel.nfl.moneyline_frozen import (
    EARLY_FEATURE_NAMES,
    MATURE_FEATURE_NAMES,
    FrozenNFLMoneylineArtifact,
    fingerprint_payload,
    load_frozen_nfl_early_artifact,
    load_frozen_nfl_mature_artifact,
    predict_frozen_home_win_probability,
)
from sportsmodel.nfl.moneyline_prediction import (
    canonical_nfl_moneyline_probability_text,
)
from sportsmodel.nfl.moneyline_routing import (
    NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
    NFLMoneylineRoute,
    select_nfl_moneyline_route,
)


HISTORICAL_EVIDENCE_PROTOCOL_VERSION = (
    "nfl_historical_probability_evidence_0.1.0"
)
HISTORICAL_EVIDENCE_EXPORTER_VERSION = (
    "nfl_historical_probability_evidence_exporter_0.1.1"
)
SOURCE_SNAPSHOT_METADATA_VERSION = (
    "nfl_historical_source_snapshot_metadata_0.2.0"
)
HOLDOUT_RECONCILIATION_SHA256 = (
    "5ca0bed9d9d556b7f43e43d7e17850b3def5222fd5c99b1327edaf707acc93b2"
)
EXPECTED_PROBABILITY_COUNTS = {
    ("mature", "DEVELOPMENT_OOF", 2022): 236,
    ("mature", "DEVELOPMENT_OOF", 2023): 237,
    ("mature", "DEVELOPMENT_OOF", 2024): 237,
    ("early", "DEVELOPMENT_OOF", 2021): 48,
    ("early", "DEVELOPMENT_OOF", 2022): 48,
    ("early", "DEVELOPMENT_OOF", 2023): 48,
    ("early", "DEVELOPMENT_OOF", 2024): 48,
    ("mature", "EXPOSED_MODEL_HOLDOUT", 2025): 237,
    ("early", "EXPOSED_MODEL_HOLDOUT", 2025): 48,
}


class EvidenceClassification(StrEnum):
    DEVELOPMENT_OOF = "DEVELOPMENT_OOF"
    EXPOSED_MODEL_HOLDOUT = "EXPOSED_MODEL_HOLDOUT"
    EXPOSED_FORWARD = "EXPOSED_FORWARD"


@dataclass(frozen=True)
class HistoricalFold:
    fold_id: str
    route: NFLMoneylineRoute
    training_seasons: tuple[int, ...]
    score_season: int


HISTORICAL_FOLDS = (
    HistoricalFold("early_oof_2021", NFLMoneylineRoute.EARLY, (2019, 2020), 2021),
    HistoricalFold(
        "early_oof_2022", NFLMoneylineRoute.EARLY, (2019, 2020, 2021), 2022
    ),
    HistoricalFold(
        "early_oof_2023",
        NFLMoneylineRoute.EARLY,
        (2019, 2020, 2021, 2022),
        2023,
    ),
    HistoricalFold(
        "early_oof_2024",
        NFLMoneylineRoute.EARLY,
        (2019, 2020, 2021, 2022, 2023),
        2024,
    ),
    HistoricalFold(
        "mature_oof_2022", NFLMoneylineRoute.MATURE, tuple(range(2018, 2022)), 2022
    ),
    HistoricalFold(
        "mature_oof_2023", NFLMoneylineRoute.MATURE, tuple(range(2018, 2023)), 2023
    ),
    HistoricalFold(
        "mature_oof_2024", NFLMoneylineRoute.MATURE, tuple(range(2018, 2024)), 2024
    ),
)


@dataclass(frozen=True)
class HistoricalTrainingRecord:
    """Internal label-bearing row. It is never serialized into the package."""

    canonical_game_id: int
    kickoff: datetime
    season: int
    route: NFLMoneylineRoute
    feature_names: tuple[str, ...]
    feature_values: tuple[float | None, ...]
    home_win: bool


@dataclass(frozen=True)
class HistoricalScoreTarget:
    """Outcome-free score-season projection used by probability generation."""

    canonical_game_id: int
    kickoff: datetime
    season: int
    season_type: str
    week: int
    week_label: str
    home_team_id: int
    away_team_id: int
    home_team: str
    away_team: str
    neutral_site: bool
    home_current_prior_games: int
    away_current_prior_games: int
    route: NFLMoneylineRoute
    feature_names: tuple[str, ...]
    feature_values: tuple[float | None, ...]
    source_trace: Mapping[str, Any]
    source_snapshot_as_of: datetime
    source_name: str
    external_game_id: str


@dataclass(frozen=True)
class ForwardExposure:
    canonical_game_id: int
    prediction_run_id: int
    prediction_id: int
    prediction_created_at: datetime
    route: NFLMoneylineRoute
    model_specification_version: str
    model_fingerprint: str


@dataclass(frozen=True)
class HistoricalEvidenceInput:
    reconstruction_as_of: datetime
    loaded_source_snapshot_as_of: datetime
    repository_revision: str
    database_identity: Mapping[str, Any]
    server_identity: Mapping[str, Any]
    transaction_snapshot: Mapping[str, Any]
    training_records: tuple[HistoricalTrainingRecord, ...]
    score_targets: tuple[HistoricalScoreTarget, ...]
    forward_exposures: tuple[ForwardExposure, ...] = ()
    source_snapshot_metadata: tuple[Mapping[str, Any], ...] = ()
    source_correction_findings: tuple[Mapping[str, Any], ...] = ()
    locked_dataset_fingerprints: Mapping[str, str] | None = None


@dataclass(frozen=True)
class HistoricalEvidenceBundle:
    probabilities: tuple[dict[str, Any], ...]
    game_identity: tuple[dict[str, Any], ...]
    folds: tuple[dict[str, Any], ...]
    model_fingerprints: tuple[dict[str, Any], ...]
    training_set_fingerprints: tuple[dict[str, Any], ...]
    source_snapshots: dict[str, Any]
    source_traces: tuple[dict[str, Any], ...]
    exposure_registry: dict[str, Any]
    validation_summary: dict[str, Any]
    row_counts: dict[str, Any]
    deterministic_rerun: dict[str, Any]
    source_correction_findings: dict[str, Any]
    package_metadata: dict[str, Any]
    holdout_reconciliation: dict[str, Any] | None = None


PROBABILITY_OUTPUT_FIELDS = (
    "evidence_row_id",
    "canonical_game_id",
    "selected_route",
    "selected_side",
    "home_win_probability",
    "selected_side_probability",
    "feature_cutoff",
    "reconstruction_as_of",
    "source_snapshot_as_of",
    "model_specification_version",
    "feature_schema_version",
    "preprocessing_identity",
    "specification_fingerprint",
    "model_fingerprint",
    "feature_vector_sha256",
    "source_trace_sha256",
    "routing_contract_version",
    "evidence_classification",
    "fold_id",
    "score_season",
    "training_game_set_sha256",
)

GAME_IDENTITY_FIELDS = (
    "canonical_game_id",
    "season",
    "season_type",
    "week",
    "week_label",
    "kickoff",
    "home_team_id",
    "away_team_id",
    "home_team",
    "away_team",
    "neutral_site",
    "source_name",
    "external_game_id",
)

FORBIDDEN_OUTPUT_FIELDS = frozenset({
    "home_score", "away_score", "status", "overtime", "home_win",
    "actual_home_win", "actual_result", "target_tie", "target_tied", "winner",
    "settled_side", "profit_loss", "result", "model_metrics",
    "home_baseline_metrics", "calibration_bins", "actual_home_win_rate",
    "american_price", "decimal_odds", "implied_probability",
    "no_vig_probability", "sportsbook", "market_edge", "expected_value",
    "odds_run_id", "market_observation_time",
})

REQUIRED_PACKAGE_FILES = frozenset({
    "README.md",
    "protocol.json",
    "probabilities.csv",
    "game_identity.csv",
    "folds.csv",
    "model_fingerprints.json",
    "training_set_fingerprints.csv",
    "source_snapshots.json",
    "source_traces.ndjson",
    "exposure_registry.json",
    "audit/validation_summary.json",
    "audit/row_counts.json",
    "audit/deterministic_rerun.json",
    "audit/source_correction_findings.json",
})


def build_historical_evidence(
    source: HistoricalEvidenceInput,
    *,
    enforce_expected_counts: bool = True,
    early_artifact: FrozenNFLMoneylineArtifact | None = None,
    mature_artifact: FrozenNFLMoneylineArtifact | None = None,
) -> HistoricalEvidenceBundle:
    """Build deterministic evidence from an already-pinned read-only snapshot."""

    _require_aware(source.reconstruction_as_of, "reconstruction_as_of")
    _require_aware(
        source.loaded_source_snapshot_as_of,
        "loaded_source_snapshot_as_of",
    )
    _validate_package_source_metadata(source)
    early_artifact = early_artifact or load_frozen_nfl_early_artifact()
    mature_artifact = mature_artifact or load_frozen_nfl_mature_artifact()
    _validate_input(source)

    records = tuple(sorted(
        source.training_records,
        key=lambda item: (item.kickoff, item.canonical_game_id),
    ))
    targets = tuple(sorted(
        source.score_targets,
        key=lambda item: (item.kickoff, item.canonical_game_id),
    ))
    folds_by_key = {(fold.route, fold.score_season): fold for fold in HISTORICAL_FOLDS}
    fold_models: dict[str, FrozenNFLMoneylineArtifact] = {}
    fold_metadata: list[dict[str, Any]] = []
    training_metadata: list[dict[str, Any]] = []

    for fold in HISTORICAL_FOLDS:
        training = tuple(
            item for item in records
            if item.route is fold.route and item.season in fold.training_seasons
        )
        if not training:
            raise ValueError(f"{fold.fold_id} has no training rows")
        if {item.season for item in training} != set(fold.training_seasons):
            raise ValueError(f"{fold.fold_id} is missing a training season")
        score_ids = {
            item.canonical_game_id for item in targets
            if item.route is fold.route and item.season == fold.score_season
        }
        training_ids = {item.canonical_game_id for item in training}
        if training_ids.intersection(score_ids):
            raise ValueError(f"{fold.fold_id} training and score populations overlap")
        artifact, identities = _fit_fold(fold, training)
        fold_models[fold.fold_id] = artifact
        fold_metadata.append({
            "fold_id": fold.fold_id,
            "selected_route": fold.route.value,
            "training_seasons": list(fold.training_seasons),
            "score_season": fold.score_season,
            "training_row_count": len(training),
            "score_row_count": len(score_ids),
            "preprocessing": (
                "SimpleImputer(strategy='median', add_indicator=False) -> "
                "StandardScaler -> LogisticRegression(C=1.0, solver='lbfgs', "
                "max_iter=5000, random_state=42)"
            ),
            "policy_selection": False,
            "hyperparameter_tuning": False,
        })
        training_metadata.append({
            "fold_id": fold.fold_id,
            "selected_route": fold.route.value,
            "training_seasons": "|".join(str(value) for value in fold.training_seasons),
            "training_row_count": len(training),
            **identities,
        })

    frozen_training_identities: dict[NFLMoneylineRoute, dict[str, str]] = {}
    for route, artifact in (
        (NFLMoneylineRoute.EARLY, early_artifact),
        (NFLMoneylineRoute.MATURE, mature_artifact),
    ):
        route_training = tuple(item for item in records if item.route is route)
        identity = _frozen_training_identity(artifact, route_training)
        frozen_training_identities[route] = identity
        training_metadata.append({
            "fold_id": f"{route.value}_fit_free_2025",
            "selected_route": route.value,
            "training_seasons": "|".join(
                str(value) for value in artifact.training_seasons
            ),
            "training_row_count": len(route_training),
            **identity,
        })

    rows: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    evidence_row_snapshot_times: list[datetime] = []
    model_records: dict[str, dict[str, Any]] = {}
    for target in targets:
        if target.season >= 2026:
            raise ValueError("2026+ targets cannot enter historical probabilities")
        if target.season == 2025:
            classification = EvidenceClassification.EXPOSED_MODEL_HOLDOUT
            fold_id = f"{target.route.value}_fit_free_2025"
            artifact = (
                early_artifact
                if target.route is NFLMoneylineRoute.EARLY
                else mature_artifact
            )
            training_identity = frozen_training_identities[target.route]
        else:
            classification = EvidenceClassification.DEVELOPMENT_OOF
            fold = folds_by_key.get((target.route, target.season))
            if fold is None:
                continue
            fold_id = fold.fold_id
            artifact = fold_models[fold_id]
            training_identity = next(
                item for item in training_metadata if item["fold_id"] == fold_id
            )
        probability = predict_frozen_home_win_probability(
            artifact, target.feature_values
        )
        selected_side = "home" if probability >= artifact.classification_threshold else "away"
        selected_probability = probability if selected_side == "home" else 1.0 - probability
        feature_payload = {
            "feature_schema_version": artifact.feature_schema_version,
            "ordered_feature_names": list(target.feature_names),
            "ordered_feature_values": list(target.feature_values),
        }
        trace_payload = _canonical(dict(target.source_trace))
        _assert_no_forbidden_output_fields(trace_payload)
        feature_sha = fingerprint_payload(feature_payload)
        trace_sha = fingerprint_payload(trace_payload)
        preprocessing_identity = _preprocessing_identity(artifact)
        row_identity = {
            "protocol": HISTORICAL_EVIDENCE_PROTOCOL_VERSION,
            "canonical_game_id": target.canonical_game_id,
            "route": target.route.value,
            "classification": classification.value,
            "fold_id": fold_id,
            "feature_vector_sha256": feature_sha,
            "model_fingerprint": artifact.model_fingerprint,
        }
        row = {
            "evidence_row_id": fingerprint_payload(row_identity),
            "canonical_game_id": target.canonical_game_id,
            "selected_route": target.route.value,
            "selected_side": selected_side,
            "home_win_probability": canonical_nfl_moneyline_probability_text(probability),
            "selected_side_probability": (
                canonical_nfl_moneyline_probability_text(selected_probability)
            ),
            "feature_cutoff": _utc_text(target.kickoff),
            "reconstruction_as_of": _utc_text(source.reconstruction_as_of),
            "source_snapshot_as_of": _utc_text(target.source_snapshot_as_of),
            "model_specification_version": artifact.specification_version,
            "feature_schema_version": artifact.feature_schema_version,
            "preprocessing_identity": preprocessing_identity,
            "specification_fingerprint": artifact.specification_fingerprint,
            "model_fingerprint": artifact.model_fingerprint,
            "feature_vector_sha256": feature_sha,
            "source_trace_sha256": trace_sha,
            "routing_contract_version": NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
            "evidence_classification": classification.value,
            "fold_id": fold_id,
            "score_season": target.season,
            "training_game_set_sha256": training_identity["training_game_set_sha256"],
        }
        if tuple(row) != PROBABILITY_OUTPUT_FIELDS:
            raise RuntimeError("probability output allowlist drift")
        rows.append(row)
        evidence_row_snapshot_times.append(target.source_snapshot_as_of)
        identities.append({
            "canonical_game_id": target.canonical_game_id,
            "season": target.season,
            "season_type": target.season_type,
            "week": target.week,
            "week_label": target.week_label,
            "kickoff": _utc_text(target.kickoff),
            "home_team_id": target.home_team_id,
            "away_team_id": target.away_team_id,
            "home_team": target.home_team,
            "away_team": target.away_team,
            "neutral_site": target.neutral_site,
            "source_name": target.source_name,
            "external_game_id": target.external_game_id,
        })
        traces.append({
            "evidence_row_id": row["evidence_row_id"],
            "canonical_game_id": target.canonical_game_id,
            "source_trace_sha256": trace_sha,
            "source_trace": trace_payload,
        })
        model_records.setdefault(fold_id, {
            "fold_id": fold_id,
            "selected_route": target.route.value,
            "model_specification_version": artifact.specification_version,
            "feature_schema_version": artifact.feature_schema_version,
            "ordered_feature_names": list(artifact.feature_names),
            "preprocessing_identity": preprocessing_identity,
            "specification_fingerprint": artifact.specification_fingerprint,
            "model_fingerprint": artifact.model_fingerprint,
            "fit_free_committed_artifact": target.season == 2025,
        })

    rows_tuple = tuple(sorted(rows, key=lambda item: (
        item["feature_cutoff"], item["canonical_game_id"]
    )))
    identity_tuple = tuple(sorted(identities, key=lambda item: (
        item["kickoff"], item["canonical_game_id"]
    )))
    trace_tuple = tuple(sorted(traces, key=lambda item: item["canonical_game_id"]))
    if len({row["canonical_game_id"] for row in rows_tuple}) != len(rows_tuple):
        raise ValueError("duplicate canonical probability rows")
    if {row["canonical_game_id"] for row in rows_tuple} != {
        row["canonical_game_id"] for row in identity_tuple
    }:
        raise RuntimeError("canonical identity projection is incomplete")
    _assert_no_forbidden_output_fields(rows_tuple)
    _assert_no_forbidden_output_fields(identity_tuple)
    _assert_no_forbidden_output_fields(trace_tuple)

    classified_snapshots = _classify_source_snapshots(
        source.source_snapshot_metadata,
        trace_tuple,
    )
    training_snapshot_times = [
        _metadata_timestamp(
            item["training_reconstruction_source_snapshot_as_of"],
            "training reconstruction source snapshot",
        )
        for item in classified_snapshots
        if item["training_reconstruction_source_snapshot_as_of"] is not None
    ]
    evidence_dependency_times = [
        *evidence_row_snapshot_times,
        *training_snapshot_times,
    ]
    if not evidence_dependency_times:
        raise ValueError("historical evidence has no retained source dependencies")
    evidence_dependency_source_snapshot_as_of = max(evidence_dependency_times)
    if (
        evidence_dependency_source_snapshot_as_of
        > source.loaded_source_snapshot_as_of
    ):
        raise ValueError(
            "evidence dependency source snapshot exceeds loaded source snapshot"
        )

    counts = Counter(
        (row["selected_route"], row["evidence_classification"], row["score_season"])
        for row in rows_tuple
    )
    if enforce_expected_counts and dict(counts) != EXPECTED_PROBABILITY_COUNTS:
        raise ValueError(
            "historical probability population differs from the locked 1,187-row contract: "
            f"{dict(sorted(counts.items()))}"
        )
    exposure_registry = _exposure_registry(source.forward_exposures)
    protocol = historical_evidence_protocol()
    package_identity = fingerprint_payload({
        "protocol": HISTORICAL_EVIDENCE_PROTOCOL_VERSION,
        "probabilities": rows_tuple,
        "game_identity": identity_tuple,
        "source_traces": trace_tuple,
        "exposure_registry": exposure_registry,
    })
    row_counts = {
        "canonical_probability_rows": len(rows_tuple),
        "expected_canonical_probability_rows": 1187,
        "legacy_non_tie_reconciliation_rows": 1184,
        "by_route_classification_season": [
            {
                "selected_route": key[0],
                "evidence_classification": key[1],
                "score_season": key[2],
                "row_count": value,
            }
            for key, value in sorted(counts.items())
        ],
        "exposed_forward_rows": len(source.forward_exposures),
    }
    validation = {
        "protocol_version": HISTORICAL_EVIDENCE_PROTOCOL_VERSION,
        "passed": False,
        "overall_validation_result": "UNVERIFIED",
        "outcome_blind_scoring_objects": True,
        "strict_output_allowlist": True,
        "market_and_outcome_denylist": True,
        "routing_contract_version": NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
        "no_2026_probabilities": all(row["score_season"] < 2026 for row in rows_tuple),
        "canonical_population_count_enforced": enforce_expected_counts,
        "package_identity_sha256": package_identity,
    }
    package_metadata = {
        "repository_revision": source.repository_revision,
        "exporter_version": HISTORICAL_EVIDENCE_EXPORTER_VERSION,
        "protocol_version": HISTORICAL_EVIDENCE_PROTOCOL_VERSION,
        "protocol_fingerprint": protocol["protocol_fingerprint"],
        "effective_database_identity": _canonical(dict(source.database_identity)),
        "postgresql_server_identity": _canonical(dict(source.server_identity)),
        "read_only_transaction_snapshot": _canonical(
            dict(source.transaction_snapshot)
        ),
        "source_snapshot_metadata_version": SOURCE_SNAPSHOT_METADATA_VERSION,
        "loaded_source_snapshot_as_of": _utc_text(
            source.loaded_source_snapshot_as_of
        ),
        "evidence_dependency_source_snapshot_as_of": _utc_text(
            evidence_dependency_source_snapshot_as_of
        ),
        "reconstruction_as_of": _utc_text(source.reconstruction_as_of),
        "export_started_at": _utc_text(source.reconstruction_as_of),
        "expected_canonical_row_count": 1187,
        "actual_canonical_row_count": len(rows_tuple),
        "overall_validation_result": "UNVERIFIED",
    }
    return HistoricalEvidenceBundle(
        probabilities=rows_tuple,
        game_identity=identity_tuple,
        folds=tuple(fold_metadata),
        model_fingerprints=tuple(model_records[key] for key in sorted(model_records)),
        training_set_fingerprints=tuple(training_metadata),
        source_snapshots={
            "source_snapshot_metadata_version": SOURCE_SNAPSHOT_METADATA_VERSION,
            "reconstruction_semantics": (
                "event-time point-in-time reconstruction from a pinned current source snapshot"
            ),
            "reconstruction_as_of": _utc_text(source.reconstruction_as_of),
            "loaded_source_snapshot_as_of": _utc_text(
                source.loaded_source_snapshot_as_of
            ),
            "evidence_dependency_source_snapshot_as_of": _utc_text(
                evidence_dependency_source_snapshot_as_of
            ),
            "source_snapshot_semantics": {
                "loaded_source_snapshot_as_of": (
                    "maximum retained observation time across the repository's "
                    "complete loaded provenance scope"
                ),
                "evidence_dependency_source_snapshot_as_of": (
                    "maximum observation time contributing to emitted probability-row "
                    "traces or required training reconstruction dependencies"
                ),
                "per_row_source_snapshot_as_of": (
                    "maximum observation time in that probability row's actual target "
                    "and feature-source trace"
                ),
            },
            "effective_database_identity": _canonical(dict(source.database_identity)),
            "postgresql_server_identity": _canonical(dict(source.server_identity)),
            "read_only_transaction_snapshot": _canonical(
                dict(source.transaction_snapshot)
            ),
            "locked_dataset_fingerprints": dict(
                sorted((source.locked_dataset_fingerprints or {}).items())
            ),
            "snapshots": [_canonical(dict(item)) for item in classified_snapshots],
        },
        source_traces=trace_tuple,
        exposure_registry=exposure_registry,
        validation_summary=validation,
        row_counts=row_counts,
        deterministic_rerun={
            "status": "UNVERIFIED",
            "passed": False,
            "first_render_sha256": None,
            "second_render_sha256": None,
            "package_identity_sha256": package_identity,
            "contract": "identical pinned input and protocol produce identical canonical content",
        },
        source_correction_findings={
            "ambiguous_source_observations": 0,
            "findings": [_canonical(dict(item)) for item in source.source_correction_findings],
        },
        package_metadata=package_metadata,
    )


def record_deterministic_rerun_pass(
    bundle: HistoricalEvidenceBundle,
    *,
    first_render_sha256: str,
    second_render_sha256: str,
) -> HistoricalEvidenceBundle:
    """Record a completed two-render comparison after validating its evidence."""

    for name, value in (
        ("first_render_sha256", first_render_sha256),
        ("second_render_sha256", second_render_sha256),
    ):
        if not _is_sha256(value):
            raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    rendered_sha256 = fingerprint_payload({
        path: content.decode("utf-8")
        for path, content in sorted(evidence_package_documents(bundle).items())
    })
    if first_render_sha256 != rendered_sha256:
        raise ValueError("first render SHA-256 does not identify the supplied bundle")
    if first_render_sha256 != second_render_sha256:
        raise ValueError("deterministic rerun render SHA-256 values differ")
    return replace(
        bundle,
        deterministic_rerun={
            **bundle.deterministic_rerun,
            "status": "PASS",
            "passed": True,
            "first_render_sha256": first_render_sha256,
            "second_render_sha256": second_render_sha256,
        },
        validation_summary={
            **bundle.validation_summary,
            "passed": True,
            "overall_validation_result": "PASS",
        },
        package_metadata={
            **bundle.package_metadata,
            "overall_validation_result": "PASS",
        },
    )


def write_historical_evidence_package(
    bundle: HistoricalEvidenceBundle,
    output_directory: Path,
    *,
    repository_root: Path,
    allow_repository_output: bool = False,
) -> dict[str, Any]:
    """Write a complete package to an explicit, empty output directory."""

    output = output_directory.resolve()
    repository = repository_root.resolve()
    if output == repository or repository in output.parents:
        if not allow_repository_output:
            raise ValueError("refusing historical evidence output inside the repository")
    if output.exists() and any(output.iterdir()):
        raise ValueError("historical evidence output directory must be empty")
    _require_verified_deterministic_rerun(bundle)
    output.mkdir(parents=True, exist_ok=True)
    documents = evidence_package_documents(bundle)
    for relative, content in documents.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    manifest = {
        "protocol_version": HISTORICAL_EVIDENCE_PROTOCOL_VERSION,
        "package_metadata": bundle.package_metadata,
        "files": [
            {
                "path": relative,
                "bytes": len(content),
                "sha256": sha256(content).hexdigest(),
            }
            for relative, content in sorted(documents.items())
        ],
    }
    manifest["manifest_payload_sha256"] = fingerprint_payload(manifest)
    (output / "MANIFEST.json").write_bytes(_json_bytes(manifest))
    validate_evidence_package(output)
    return manifest


def evidence_package_documents(bundle: HistoricalEvidenceBundle) -> dict[str, bytes]:
    """Render all non-manifest package files deterministically in memory."""

    protocol = historical_evidence_protocol()
    documents = {
        "README.md": _readme(bundle).encode("utf-8"),
        "protocol.json": _json_bytes(protocol),
        "probabilities.csv": _csv_bytes(bundle.probabilities, PROBABILITY_OUTPUT_FIELDS),
        "game_identity.csv": _csv_bytes(bundle.game_identity, GAME_IDENTITY_FIELDS),
        "folds.csv": _csv_bytes(bundle.folds, tuple(bundle.folds[0]) if bundle.folds else ()),
        "model_fingerprints.json": _json_bytes(list(bundle.model_fingerprints)),
        "training_set_fingerprints.csv": _csv_bytes(
            bundle.training_set_fingerprints,
            tuple(bundle.training_set_fingerprints[0]) if bundle.training_set_fingerprints else (),
        ),
        "source_snapshots.json": _json_bytes(bundle.source_snapshots),
        "source_traces.ndjson": b"".join(
            _compact_json_bytes(item) + b"\n" for item in bundle.source_traces
        ),
        "exposure_registry.json": _json_bytes(bundle.exposure_registry),
        "audit/validation_summary.json": _json_bytes(bundle.validation_summary),
        "audit/row_counts.json": _json_bytes(bundle.row_counts),
        "audit/deterministic_rerun.json": _json_bytes(bundle.deterministic_rerun),
        "audit/source_correction_findings.json": _json_bytes(
            bundle.source_correction_findings
        ),
    }
    if bundle.holdout_reconciliation is not None:
        documents["audit/holdout_reconciliation.json"] = _json_bytes(
            bundle.holdout_reconciliation
        )
    return documents


def historical_evidence_protocol() -> dict[str, Any]:
    """Return the canonical protocol plus its self-independent fingerprint."""

    protocol = {
        "protocol_version": HISTORICAL_EVIDENCE_PROTOCOL_VERSION,
        "canonical_population": "outcome-blind",
        "allowed_probability_classifications": [
            EvidenceClassification.DEVELOPMENT_OOF.value,
            EvidenceClassification.EXPOSED_MODEL_HOLDOUT.value,
        ],
        "forward_registry_classification": EvidenceClassification.EXPOSED_FORWARD.value,
        "routing_contract_version": NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
        "routing_rule": (
            "mature iff home_current_prior_games >= 3 and "
            "away_current_prior_games >= 3"
        ),
        "feature_cutoff": "canonical target kickoff; every source kickoff is strictly earlier",
        "reconstruction_semantics": (
            "event-time point-in-time reconstruction from a pinned current source snapshot"
        ),
        "probability_output_fields": list(PROBABILITY_OUTPUT_FIELDS),
        "forbidden_output_fields": sorted(FORBIDDEN_OUTPUT_FIELDS),
    }
    return {**protocol, "protocol_fingerprint": fingerprint_payload(protocol)}


def validate_evidence_package(directory: Path) -> None:
    manifest_path = directory / "MANIFEST.json"
    if not manifest_path.is_file():
        raise ValueError("historical evidence package is missing MANIFEST.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload_hash = manifest.pop("manifest_payload_sha256", None)
    if payload_hash != fingerprint_payload(manifest):
        raise ValueError("historical evidence manifest payload hash mismatch")
    recorded = {item["path"]: item for item in manifest.get("files", [])}
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*") if path.is_file()
    }
    expected = set(recorded) | {"MANIFEST.json"}
    if actual != expected:
        raise ValueError(
            f"historical evidence package file set mismatch; missing={sorted(expected-actual)}, "
            f"extra={sorted(actual-expected)}"
        )
    if not REQUIRED_PACKAGE_FILES.issubset(actual):
        raise ValueError("historical evidence package is missing a required artifact")
    for relative, item in recorded.items():
        content = (directory / relative).read_bytes()
        if len(content) != item["bytes"] or sha256(content).hexdigest() != item["sha256"]:
            raise ValueError(f"historical evidence package hash mismatch: {relative}")


def reconcile_optional_2025_holdout(
    bundle: HistoricalEvidenceBundle,
    report_path: Path,
) -> dict[str, Any]:
    """Optionally reconcile legacy 2025 mature non-tie probabilities by identity."""

    content = report_path.read_bytes()
    actual_sha = sha256(content).hexdigest()
    if actual_sha != HOLDOUT_RECONCILIATION_SHA256:
        raise ValueError("optional 2025 holdout report SHA-256 mismatch")
    report = json.loads(content)
    legacy = report.get("eligible_holdout_predictions")
    if not isinstance(legacy, list):
        raise ValueError("optional 2025 holdout report lacks prediction rows")
    exported = {
        row["canonical_game_id"]: float(row["home_win_probability"])
        for row in bundle.probabilities
        if row["score_season"] == 2025 and row["selected_route"] == "mature"
    }
    compared = 0
    maximum_difference = 0.0
    for item in legacy:
        game_id = item.get("game_id")
        probability = item.get("model_home_win_probability")
        if game_id not in exported or not isinstance(probability, (int, float)):
            raise ValueError("optional 2025 holdout row cannot be reconciled")
        maximum_difference = max(maximum_difference, abs(exported[game_id] - float(probability)))
        compared += 1
    if compared != 236 or maximum_difference > 1e-12:
        raise ValueError("optional 2025 holdout probabilities differ from fit-free replay")
    return {
        "performed": True,
        "source_sha256": actual_sha,
        "legacy_non_tie_rows_compared": compared,
        "maximum_absolute_probability_difference": maximum_difference,
        "passed": True,
    }


def _fit_fold(
    fold: HistoricalFold,
    training: tuple[HistoricalTrainingRecord, ...],
) -> tuple[FrozenNFLMoneylineArtifact, dict[str, Any]]:
    expected_names = (
        EARLY_FEATURE_NAMES
        if fold.route is NFLMoneylineRoute.EARLY
        else MATURE_FEATURE_NAMES
    )
    if any(item.feature_names != expected_names for item in training):
        raise ValueError(f"{fold.fold_id} feature order differs from the frozen family")
    targets = [item.home_win for item in training]
    if len(set(targets)) != 2:
        raise ValueError(f"{fold.fold_id} training requires both target classes")
    matrix = [
        [math.nan if value is None else value for value in item.feature_values]
        for item in training
    ]
    if any(all(math.isnan(row[index]) for row in matrix) for index in range(len(expected_names))):
        raise ValueError(f"{fold.fold_id} has an all-missing training feature")
    pipeline = _pipeline()
    pipeline.fit(matrix, targets)
    imputer: SimpleImputer = pipeline.named_steps["imputer"]
    scaler: StandardScaler = pipeline.named_steps["scaler"]
    classifier: LogisticRegression = pipeline.named_steps["classifier"]
    training_game_set_sha = fingerprint_payload([
        item.canonical_game_id for item in training
    ])
    training_dataset_sha = fingerprint_payload([
        {
            "canonical_game_id": item.canonical_game_id,
            "kickoff": _utc_text(item.kickoff),
            "season": item.season,
            "feature_names": list(item.feature_names),
            "feature_values": list(item.feature_values),
            "home_win": item.home_win,
        }
        for item in training
    ])
    specification = {
        "protocol_version": HISTORICAL_EVIDENCE_PROTOCOL_VERSION,
        "fold_id": fold.fold_id,
        "route": fold.route.value,
        "training_seasons": list(fold.training_seasons),
        "score_season": fold.score_season,
        "feature_names": list(expected_names),
        "imputation": "training-row median",
        "scaling": "training-row StandardScaler",
        "regularization_c": 1.0,
        "solver": "lbfgs",
        "max_iterations": 5000,
        "random_state": 42,
    }
    fitted = {
        "specification": specification,
        "training_game_set_sha256": training_game_set_sha,
        "training_dataset_sha256": training_dataset_sha,
        "imputer_statistics": [float(value) for value in imputer.statistics_],
        "scaler_means": [float(value) for value in scaler.mean_],
        "scaler_scales": [float(value) for value in scaler.scale_],
        "coefficients": [float(value) for value in classifier.coef_[0]],
        "intercept": float(classifier.intercept_[0]),
    }
    specification_sha = fingerprint_payload(specification)
    model_sha = fingerprint_payload(fitted)
    artifact = FrozenNFLMoneylineArtifact(
        route=fold.route,
        specification_version=(
            f"{HISTORICAL_EVIDENCE_PROTOCOL_VERSION}:{fold.fold_id}"
        ),
        specification_fingerprint=specification_sha,
        feature_schema_version=(
            "nfl_moneyline_early_0.1.0"
            if fold.route is NFLMoneylineRoute.EARLY
            else "nfl_moneyline_0.2.0"
        ),
        feature_names=expected_names,
        target="home_win",
        training_seasons=fold.training_seasons,
        training_population="fold training rows only",
        training_row_count=len(training),
        training_home_win_rate=sum(targets) / len(targets),
        dataset_fingerprint=training_dataset_sha,
        regularization_c=1.0,
        solver="lbfgs",
        max_iterations=5000,
        random_state=42,
        imputation="training-row median",
        scaling="training-row StandardScaler",
        classification_threshold=0.5,
        imputer_statistics=tuple(fitted["imputer_statistics"]),
        scaler_means=tuple(fitted["scaler_means"]),
        scaler_scales=tuple(fitted["scaler_scales"]),
        coefficients=tuple(fitted["coefficients"]),
        intercept=fitted["intercept"],
        historical_evidence_status="DEVELOPMENT_OOF",
        next_forward_evidence_season=2026,
        model_fingerprint=model_sha,
    )
    return artifact, {
        "training_game_set_sha256": training_game_set_sha,
        "training_dataset_sha256": training_dataset_sha,
        "pinned_source_dataset_fingerprint": "",
        "preprocessing_identity": _preprocessing_identity(artifact),
        "model_fingerprint": model_sha,
    }


def _frozen_training_identity(
    artifact: FrozenNFLMoneylineArtifact,
    training: tuple[HistoricalTrainingRecord, ...],
) -> dict[str, str]:
    expected_seasons = set(artifact.training_seasons)
    if {item.season for item in training} != expected_seasons:
        raise ValueError("fit-free frozen training population is missing a season")
    training_dataset_sha = fingerprint_payload([
        {
            "canonical_game_id": item.canonical_game_id,
            "kickoff": _utc_text(item.kickoff),
            "season": item.season,
            "feature_names": list(item.feature_names),
            "feature_values": list(item.feature_values),
            "home_win": item.home_win,
        }
        for item in training
    ])
    return {
        "training_game_set_sha256": fingerprint_payload([
            item.canonical_game_id for item in training
        ]),
        "training_dataset_sha256": training_dataset_sha,
        "pinned_source_dataset_fingerprint": artifact.dataset_fingerprint,
        "preprocessing_identity": _preprocessing_identity(artifact),
        "model_fingerprint": artifact.model_fingerprint,
    }


def _preprocessing_identity(artifact: FrozenNFLMoneylineArtifact) -> str:
    return fingerprint_payload({
        "imputation": artifact.imputation,
        "scaling": artifact.scaling,
        "imputer_statistics": list(artifact.imputer_statistics),
        "scaler_means": list(artifact.scaler_means),
        "scaler_scales": list(artifact.scaler_scales),
    })


def _pipeline() -> Pipeline:
    return Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median", add_indicator=False)),
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(
            C=1.0, solver="lbfgs", max_iter=5000, random_state=42
        )),
    ])


def _validate_input(source: HistoricalEvidenceInput) -> None:
    training_ids = [item.canonical_game_id for item in source.training_records]
    if len(training_ids) != len(set(training_ids)):
        raise ValueError("duplicate internal training game IDs")
    score_ids = [item.canonical_game_id for item in source.score_targets]
    if len(score_ids) != len(set(score_ids)):
        raise ValueError("duplicate score target game IDs")
    for record in source.training_records:
        _require_aware(record.kickoff, "training kickoff")
        expected = (
            EARLY_FEATURE_NAMES
            if record.route is NFLMoneylineRoute.EARLY
            else MATURE_FEATURE_NAMES
        )
        if record.feature_names != expected or len(record.feature_values) != len(expected):
            raise ValueError("training record differs from frozen feature order")
    for target in source.score_targets:
        _require_aware(target.kickoff, "score kickoff")
        _require_aware(target.source_snapshot_as_of, "target source_snapshot_as_of")
        selected = select_nfl_moneyline_route(
            target.home_current_prior_games, target.away_current_prior_games
        )
        if target.route is not selected:
            raise ValueError("score target route differs from the frozen 3/3 rule")
        expected = (
            EARLY_FEATURE_NAMES
            if target.route is NFLMoneylineRoute.EARLY
            else MATURE_FEATURE_NAMES
        )
        if target.feature_names != expected or len(target.feature_values) != len(expected):
            raise ValueError("score target differs from frozen feature order")
        for kickoff in _source_kickoffs(target.source_trace):
            if kickoff >= target.kickoff:
                raise ValueError("source kickoff must be strictly before feature_cutoff")
        trace_observation_times = tuple(
            _metadata_timestamp(
                observation["observed_at"],
                "probability trace source observation",
            )
            for observation in _trace_source_observations(target.source_trace)
        )
        if (
            trace_observation_times
            and max(trace_observation_times) != target.source_snapshot_as_of
        ):
            raise ValueError(
                "target source_snapshot_as_of differs from actual source trace"
            )
    if source.locked_dataset_fingerprints:
        for name, value in source.locked_dataset_fingerprints.items():
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError("locked dataset fingerprint metadata is invalid")


def _validate_package_source_metadata(source: HistoricalEvidenceInput) -> None:
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source.repository_revision):
        raise ValueError("repository revision metadata is invalid")
    for name, value in (
        ("effective database identity", source.database_identity),
        ("PostgreSQL server identity", source.server_identity),
        ("read-only transaction snapshot", source.transaction_snapshot),
    ):
        if not isinstance(value, Mapping) or not value:
            raise ValueError(f"{name} metadata is missing")
    snapshot = source.transaction_snapshot
    if (
        str(snapshot.get("transaction_isolation", "")).lower().replace("_", " ")
        != "repeatable read"
        or snapshot.get("transaction_read_only") is not True
        or not snapshot.get("snapshot_id")
    ):
        raise ValueError("transaction snapshot metadata is not read-only REPEATABLE READ")
    serialized_identity = json.dumps(
        _canonical({
            "database": source.database_identity,
            "server": source.server_identity,
        }),
        sort_keys=True,
    ).lower()
    if any(secret in serialized_identity for secret in ("password", "secret", "credential")):
        raise ValueError("database identity metadata contains a secret-bearing field")
    if source.source_snapshot_metadata:
        run_ids: set[int] = set()
        loaded_times: list[datetime] = []
        for item in source.source_snapshot_metadata:
            if not isinstance(item, Mapping):
                raise ValueError("source snapshot metadata row is invalid")
            run_id = item.get("ingestion_run_id")
            loaded_count = item.get("loaded_observation_count")
            training_count = item.get(
                "training_reconstruction_observation_count"
            )
            if (
                not isinstance(run_id, int)
                or run_id in run_ids
                or not isinstance(loaded_count, int)
                or loaded_count <= 0
                or not isinstance(training_count, int)
                or not 0 <= training_count <= loaded_count
            ):
                raise ValueError("source snapshot contribution metadata is invalid")
            run_ids.add(run_id)
            loaded_times.append(_metadata_timestamp(
                item.get("loaded_source_snapshot_as_of"),
                "loaded source snapshot",
            ))
            training_time = item.get(
                "training_reconstruction_source_snapshot_as_of"
            )
            if (training_count == 0) != (training_time is None):
                raise ValueError(
                    "training reconstruction contribution timestamp is inconsistent"
                )
            if training_time is not None:
                _metadata_timestamp(
                    training_time,
                    "training reconstruction source snapshot",
                )
        if max(loaded_times) != source.loaded_source_snapshot_as_of:
            raise ValueError(
                "loaded source snapshot timestamp differs from snapshot inventory"
            )


def _classify_source_snapshots(
    snapshots: Iterable[Mapping[str, Any]],
    traces: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    snapshot_rows = tuple(dict(item) for item in snapshots)
    if not snapshot_rows:
        return ()
    known_run_ids = {item["ingestion_run_id"] for item in snapshot_rows}
    reference_counts: Counter[int] = Counter()
    unique_observations: dict[int, set[str]] = defaultdict(set)
    latest_references: dict[int, datetime] = {}
    for trace in traces:
        for observation in _trace_source_observations(trace):
            run_id = observation["ingestion_run_id"]
            if run_id not in known_run_ids:
                raise ValueError(
                    "probability trace references an unlisted ingestion run"
                )
            observed_at = _metadata_timestamp(
                observation["observed_at"],
                "probability trace source observation",
            )
            reference_counts[run_id] += 1
            unique_observations[run_id].add(fingerprint_payload(observation))
            latest_references[run_id] = max(
                observed_at,
                latest_references.get(run_id, observed_at),
            )

    classified = []
    for item in sorted(snapshot_rows, key=lambda row: row["ingestion_run_id"]):
        run_id = item["ingestion_run_id"]
        probability_count = reference_counts[run_id]
        training_count = item["training_reconstruction_observation_count"]
        classifications = []
        if probability_count:
            classifications.append("probability_row_trace_contributor")
        if training_count:
            classifications.append("training_reconstruction_contributor")
        if not classifications:
            classifications.append("unrelated_loaded_context")
        classified.append({
            **item,
            "contribution_classifications": classifications,
            "probability_row_trace_reference_count": probability_count,
            "probability_row_trace_unique_observation_count": len(
                unique_observations[run_id]
            ),
            "probability_row_trace_source_snapshot_as_of": (
                latest_references.get(run_id)
            ),
        })
    return tuple(classified)


def _trace_source_observations(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if {
            "ingestion_run_id", "observed_at", "raw_row_sha256"
        }.issubset(value):
            yield value
        for item in value.values():
            yield from _trace_source_observations(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _trace_source_observations(item)


def _metadata_timestamp(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        _require_aware(value, name)
        return value
    if isinstance(value, str):
        try:
            return _parse_source_kickoff(value)
        except ValueError as error:
            raise ValueError(f"{name} is invalid") from error
    raise ValueError(f"{name} must be a timezone-aware timestamp")


def _source_kickoffs(value: Any) -> Iterable[datetime]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "kickoff":
                if isinstance(item, datetime):
                    _require_aware(item, "source kickoff")
                    yield item
                elif isinstance(item, str):
                    yield _parse_source_kickoff(item)
                else:
                    raise ValueError(
                        "source kickoff must be a timezone-aware datetime or strict ISO-8601 string"
                    )
            else:
                yield from _source_kickoffs(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _source_kickoffs(item)


def _parse_source_kickoff(value: str) -> datetime:
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
        value,
    ):
        raise ValueError("source kickoff string must be strict timezone-aware ISO-8601")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise ValueError("source kickoff string is malformed") from error
    _require_aware(parsed, "source kickoff")
    return parsed


def _require_verified_deterministic_rerun(bundle: HistoricalEvidenceBundle) -> None:
    rerun = bundle.deterministic_rerun
    first = rerun.get("first_render_sha256")
    second = rerun.get("second_render_sha256")
    if (
        rerun.get("status") != "PASS"
        or rerun.get("passed") is not True
        or not _is_sha256(first)
        or first != second
        or bundle.package_metadata.get("overall_validation_result") != "PASS"
    ):
        raise ValueError(
            "historical evidence package requires a completed deterministic rerun PASS"
        )


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _exposure_registry(exposures: Iterable[ForwardExposure]) -> dict[str, Any]:
    ordered = sorted(
        exposures,
        key=lambda item: (item.prediction_created_at, item.prediction_id),
    )
    rows = [
        {
            "evidence_classification": EvidenceClassification.EXPOSED_FORWARD.value,
            "canonical_game_id": item.canonical_game_id,
            "prediction_run_id": item.prediction_run_id,
            "prediction_id": item.prediction_id,
            "prediction_created_at": _utc_text(item.prediction_created_at),
            "selected_route": item.route.value,
            "model_specification_version": item.model_specification_version,
            "model_fingerprint": item.model_fingerprint,
        }
        for item in ordered
    ]
    if any(item["evidence_classification"] != "EXPOSED_FORWARD" for item in rows):
        raise RuntimeError("forward exposure classification drift")
    return {"classification": "EXPOSED_FORWARD", "rows": rows}


def _assert_no_forbidden_output_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        conflicts = FORBIDDEN_OUTPUT_FIELDS.intersection(str(key) for key in value)
        if conflicts:
            raise ValueError(f"forbidden outcome/market output fields: {sorted(conflicts)}")
        for item in value.values():
            _assert_no_forbidden_output_fields(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _assert_no_forbidden_output_fields(item)


def _readme(bundle: HistoricalEvidenceBundle) -> str:
    return (
        "# NFL Historical Probability Evidence\n\n"
        "This package contains 1,187 outcome-blind probability rows when built "
        "from the locked production population: DEVELOPMENT_OOF for 2021-2024 "
        "early and 2022-2024 mature routes, plus EXPOSED_MODEL_HOLDOUT for all "
        "2025 routes. The legacy 1,184 non-tie population is reconciliation-only.\n\n"
        "The reconstruction is event-time point-in-time from a pinned current "
        "source snapshot. It is not a bitemporal recreation of database knowledge "
        "on each historical game date. Already observed 2026 evidence appears only "
        "in exposure_registry.json as EXPOSED_FORWARD; this package creates no "
        "PROSPECTIVE_CONFIRMATION evidence.\n\n"
        "source_snapshots.json distinguishes the complete loaded provenance scope "
        "from source observations that contribute to probability-row traces or "
        "required training reconstruction. Each probabilities.csv row retains its "
        "own actual target/feature-trace source_snapshot_as_of timestamp.\n\n"
        "The 2022 scored population has 284 canonical games: 48 early-route and "
        "236 mature-route. The upstream-cancelled 2022_17_BUF_CIN event is absent, "
        "not an unexplained mature-route exclusion. Mature OOF coverage intentionally "
        "begins in 2022 with the frozen 2018-2021 -> 2022 fold; 2021 historical "
        "evidence is early-route only.\n\n"
        "No target outcomes, market observations, prices, evaluation results, or "
        "profit/loss fields are included.\n\n"
        f"Package identity: {bundle.validation_summary['package_identity_sha256']}\n"
    )


def _csv_bytes(rows: Iterable[Mapping[str, Any]], fields: tuple[str, ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        if set(row) != set(fields):
            raise ValueError("CSV row differs from its explicit output allowlist")
        writer.writerow({key: _csv_value(row[key]) for key in fields})
    return stream.getvalue().encode("utf-8")


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(
        _canonical(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n").encode("utf-8")


def _compact_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _canonical(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return _utc_text(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("historical evidence cannot contain nonfinite values")
    return value


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
