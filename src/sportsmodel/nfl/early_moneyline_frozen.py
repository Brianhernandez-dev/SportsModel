"""Frozen parsimonious NFL early-season candidate for 2026 forward evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from typing import Any, Iterable

from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from sportsmodel.nfl.early_features import (
    NFL_EARLY_MONEYLINE_FEATURE_NAMES,
    NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION,
    NFLMoneylineRoute,
    select_nfl_moneyline_route,
)
from sportsmodel.nfl.early_moneyline_baseline import (
    NFL_EARLY_BASELINE_C,
    NFL_EARLY_BASELINE_MAX_ITERATIONS,
    NFL_EARLY_BASELINE_RANDOM_STATE,
    NFL_EARLY_BASELINE_SOLVER,
    NFL_EARLY_DATASET_FINGERPRINT,
    NFLEarlyMoneylineModelingExample,
)
from sportsmodel.nfl.moneyline_holdout import (
    FROZEN_NFL_BASELINE_SPECIFICATION_VERSION,
)


FROZEN_NFL_EARLY_SPECIFICATION_VERSION = "nfl_moneyline_early_frozen_0.1.0"
FROZEN_NFL_EARLY_TRAINING_SEASONS = tuple(range(2019, 2025))
FROZEN_NFL_EARLY_NEXT_FORWARD_SEASON = 2026
FROZEN_NFL_EARLY_FEATURE_NAMES = (
    "prior_season_games_played_difference",
    "prior_season_win_percentage_difference",
    "prior_season_average_point_differential_difference",
    "prior_season_average_turnover_differential_difference",
)
FROZEN_NFL_EARLY_FEATURE_INDEXES = tuple(
    NFL_EARLY_MONEYLINE_FEATURE_NAMES.index(name)
    for name in FROZEN_NFL_EARLY_FEATURE_NAMES
)
FROZEN_NFL_EARLY_EVIDENCE_NOTICE = (
    "2019-2025 HISTORICAL EVIDENCE IS EXPOSED FOR THIS MODEL FAMILY. "
    "THE NEXT GENUINELY UNSEEN EVIDENCE IS 2026 FORWARD PERFORMANCE."
)
FROZEN_NFL_EARLY_RETROSPECTIVE_LABEL = (
    "RETROSPECTIVE CONSISTENCY ONLY — NOT VALIDATION"
)


@dataclass(frozen=True)
class FrozenNflEarlySpecification:
    specification_version: str
    model_purpose: str
    target: str
    training_seasons: tuple[int, ...]
    training_population: str
    routing_population: str
    feature_schema_version: str
    feature_names: tuple[str, ...]
    regularization_c: float
    solver: str
    max_iterations: int
    random_state: int
    imputation: str
    scaling: str
    classification_threshold: float
    dataset_fingerprint: str
    historical_evidence_status: str
    next_forward_evidence_season: int


FROZEN_NFL_EARLY_SPECIFICATION = FrozenNflEarlySpecification(
    specification_version=FROZEN_NFL_EARLY_SPECIFICATION_VERSION,
    model_purpose=(
        "Parsimonious NFL early-route Moneyline probability candidate frozen "
        "for prospective 2026 evaluation"
    ),
    target="home_win",
    training_seasons=FROZEN_NFL_EARLY_TRAINING_SEASONS,
    training_population=(
        "Final non-tied NFL early-route targets in seasons 2019-2024; "
        "either team has fewer than 3 PIT-safe current-season prior games"
    ),
    routing_population=(
        "early when home_current_prior_games < 3 or "
        "away_current_prior_games < 3; scheduled week is never used"
    ),
    feature_schema_version=NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION,
    feature_names=FROZEN_NFL_EARLY_FEATURE_NAMES,
    regularization_c=1.0,
    solver="lbfgs",
    max_iterations=5000,
    random_state=42,
    imputation="training-row SimpleImputer(strategy='median', add_indicator=False)",
    scaling="training-row StandardScaler",
    classification_threshold=0.5,
    dataset_fingerprint=NFL_EARLY_DATASET_FINGERPRINT,
    historical_evidence_status=FROZEN_NFL_EARLY_EVIDENCE_NOTICE,
    next_forward_evidence_season=FROZEN_NFL_EARLY_NEXT_FORWARD_SEASON,
)


@dataclass(frozen=True)
class FrozenNflEarlyModelArtifact:
    specification_version: str
    specification_fingerprint: str
    feature_schema_version: str
    feature_names: tuple[str, ...]
    target: str
    regularization_c: float
    solver: str
    max_iterations: int
    random_state: int
    imputation: str
    scaling: str
    classification_threshold: float
    training_seasons: tuple[int, ...]
    training_population: str
    routing_population: str
    training_row_count: int
    training_home_win_rate: float
    dataset_fingerprint: str
    imputer_statistics: tuple[float, ...]
    scaler_means: tuple[float, ...]
    scaler_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    historical_evidence_status: str
    next_forward_evidence_season: int
    retrospective_status: str
    model_fingerprint: str


@dataclass(frozen=True)
class NflMoneylineRoutingDecision:
    route: NFLMoneylineRoute
    model_specification_version: str
    home_current_prior_games: int
    away_current_prior_games: int


@dataclass(frozen=True)
class FrozenNflForwardEvaluationProtocol:
    first_forward_season: int
    prediction_record_fields: tuple[str, ...]
    primary_probability_metrics: tuple[str, ...]
    baseline: str
    required_route_breakouts: tuple[str, ...]
    early_history_states: tuple[int, ...]
    evidence_rules: tuple[str, ...]


FROZEN_NFL_FORWARD_EVALUATION_PROTOCOL = FrozenNflForwardEvaluationProtocol(
    first_forward_season=2026,
    prediction_record_fields=(
        "game_id",
        "target_kickoff",
        "season",
        "home_team_id",
        "away_team_id",
        "home_current_prior_games",
        "away_current_prior_games",
        "route",
        "model_specification_version",
        "feature_schema_version",
        "feature_cutoff",
        "model_home_win_probability",
        "predicted_side",
        "actual_result",
        "target_tied",
        "prediction_timestamp",
        "prediction_run_id",
    ),
    primary_probability_metrics=(
        "accuracy",
        "log_loss",
        "brier_score",
        "roc_auc_when_both_classes_exist",
        "mean_predicted_home_win_probability",
        "actual_home_win_rate",
        "calibration",
        "expected_calibration_error",
    ),
    baseline="frozen training-derived empirical home-win probability",
    required_route_breakouts=("early", "mature", "combined_with_routes_visible"),
    early_history_states=(0, 1, 2),
    evidence_rules=(
        "Generate and retain predictions before target outcomes are known.",
        "Do not modify a frozen model specification in place after forward use begins.",
        "Version successor models and preserve all original forward predictions.",
        "Do not tune after Week 1, Week 2, or Week 3 outcomes.",
        "Report uncertainty and do not overinterpret one roughly 47-48 game season.",
        "Treat 2026 as forward validation, not permission for continuous adaptation.",
    ),
)


def select_frozen_nfl_moneyline_route(
    home_current_prior_games: int,
    away_current_prior_games: int,
) -> NflMoneylineRoutingDecision:
    route = select_nfl_moneyline_route(
        home_current_prior_games,
        away_current_prior_games,
    )
    model = (
        FROZEN_NFL_EARLY_SPECIFICATION_VERSION
        if route is NFLMoneylineRoute.EARLY
        else FROZEN_NFL_BASELINE_SPECIFICATION_VERSION
    )
    return NflMoneylineRoutingDecision(
        route=route,
        model_specification_version=model,
        home_current_prior_games=home_current_prior_games,
        away_current_prior_games=away_current_prior_games,
    )


def assert_frozen_nfl_early_specification() -> None:
    spec = FROZEN_NFL_EARLY_SPECIFICATION
    excluded = set(NFL_EARLY_MONEYLINE_FEATURE_NAMES) - set(spec.feature_names)
    required_excluded = {
        "current_season_prior_games_played_difference",
        "current_season_win_percentage_difference",
        "current_season_average_points_for_difference",
        "current_season_average_points_against_difference",
        "current_season_average_turnover_differential_difference",
        "minimum_current_season_prior_games",
        "neutral_site",
    }
    checks = {
        "specification version": spec.specification_version
        == FROZEN_NFL_EARLY_SPECIFICATION_VERSION,
        "feature schema": spec.feature_schema_version
        == NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION,
        "ordered learned features": spec.feature_names
        == FROZEN_NFL_EARLY_FEATURE_NAMES,
        "excluded current/context features": required_excluded.issubset(excluded),
        "training seasons": spec.training_seasons == tuple(range(2019, 2025)),
        "dataset fingerprint": spec.dataset_fingerprint
        == NFL_EARLY_DATASET_FINGERPRINT,
        "regularization C": spec.regularization_c
        == NFL_EARLY_BASELINE_C == 1.0,
        "solver": spec.solver == NFL_EARLY_BASELINE_SOLVER == "lbfgs",
        "max iterations": spec.max_iterations
        == NFL_EARLY_BASELINE_MAX_ITERATIONS == 5000,
        "random state": spec.random_state
        == NFL_EARLY_BASELINE_RANDOM_STATE == 42,
        "evidence notice": "2019-2025" in spec.historical_evidence_status
        and "2026 FORWARD" in spec.historical_evidence_status,
    }
    drift = [name for name, matches in checks.items() if not matches]
    if drift:
        raise RuntimeError(
            "frozen NFL early specification drift: " + ", ".join(drift)
        )
    pipeline = _pipeline()
    if tuple(pipeline.named_steps) != ("imputer", "scaler", "classifier"):
        raise RuntimeError("frozen NFL early preprocessing order drift")
    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scaler"]
    classifier = pipeline.named_steps["classifier"]
    if not (
        isinstance(imputer, SimpleImputer)
        and imputer.strategy == "median"
        and not imputer.add_indicator
    ):
        raise RuntimeError("frozen NFL early imputer drift")
    if not (
        isinstance(scaler, StandardScaler)
        and scaler.with_mean
        and scaler.with_std
    ):
        raise RuntimeError("frozen NFL early scaler drift")
    params = classifier.get_params()
    if not isinstance(classifier, LogisticRegression) or any(
        params[name] != value
        for name, value in {
            "C": spec.regularization_c,
            "solver": spec.solver,
            "max_iter": spec.max_iterations,
            "random_state": spec.random_state,
        }.items()
    ):
        raise RuntimeError("frozen NFL early classifier drift")


def frozen_nfl_early_specification_fingerprint() -> str:
    assert_frozen_nfl_early_specification()
    return _fingerprint(asdict(FROZEN_NFL_EARLY_SPECIFICATION))


def fit_frozen_nfl_early_candidate(
    examples: Iterable[NFLEarlyMoneylineModelingExample],
    *,
    dataset_fingerprint: str,
) -> FrozenNflEarlyModelArtifact:
    assert_frozen_nfl_early_specification()
    ordered = tuple(examples)
    _validate_training_population(ordered)
    targets = [item.home_win for item in ordered]
    if len(set(targets)) != 2:
        raise ValueError("frozen NFL early training requires both target classes")
    matrix = _matrix(ordered)
    if any(
        all(math.isnan(row[index]) for row in matrix)
        for index in range(len(FROZEN_NFL_EARLY_FEATURE_NAMES))
    ):
        raise ValueError("frozen NFL early training has an all-missing feature")
    pipeline = _pipeline()
    pipeline.fit(matrix, targets)
    imputer: SimpleImputer = pipeline.named_steps["imputer"]
    scaler: StandardScaler = pipeline.named_steps["scaler"]
    classifier: LogisticRegression = pipeline.named_steps["classifier"]
    values = {
        "specification_version": FROZEN_NFL_EARLY_SPECIFICATION_VERSION,
        "specification_fingerprint": frozen_nfl_early_specification_fingerprint(),
        "feature_schema_version": NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION,
        "feature_names": FROZEN_NFL_EARLY_FEATURE_NAMES,
        "target": "home_win",
        "regularization_c": FROZEN_NFL_EARLY_SPECIFICATION.regularization_c,
        "solver": FROZEN_NFL_EARLY_SPECIFICATION.solver,
        "max_iterations": FROZEN_NFL_EARLY_SPECIFICATION.max_iterations,
        "random_state": FROZEN_NFL_EARLY_SPECIFICATION.random_state,
        "imputation": FROZEN_NFL_EARLY_SPECIFICATION.imputation,
        "scaling": FROZEN_NFL_EARLY_SPECIFICATION.scaling,
        "classification_threshold": (
            FROZEN_NFL_EARLY_SPECIFICATION.classification_threshold
        ),
        "training_seasons": FROZEN_NFL_EARLY_TRAINING_SEASONS,
        "training_population": FROZEN_NFL_EARLY_SPECIFICATION.training_population,
        "routing_population": FROZEN_NFL_EARLY_SPECIFICATION.routing_population,
        "training_row_count": len(ordered),
        "training_home_win_rate": sum(targets) / len(targets),
        "dataset_fingerprint": dataset_fingerprint,
        "imputer_statistics": tuple(float(value) for value in imputer.statistics_),
        "scaler_means": tuple(float(value) for value in scaler.mean_),
        "scaler_scales": tuple(float(value) for value in scaler.scale_),
        "coefficients": tuple(float(value) for value in classifier.coef_[0]),
        "intercept": float(classifier.intercept_[0]),
        "historical_evidence_status": FROZEN_NFL_EARLY_EVIDENCE_NOTICE,
        "next_forward_evidence_season": FROZEN_NFL_EARLY_NEXT_FORWARD_SEASON,
        "retrospective_status": FROZEN_NFL_EARLY_RETROSPECTIVE_LABEL,
    }
    if any(
        len(values[name]) != len(FROZEN_NFL_EARLY_FEATURE_NAMES)
        for name in (
            "imputer_statistics",
            "scaler_means",
            "scaler_scales",
            "coefficients",
        )
    ):
        raise RuntimeError("frozen NFL early fitted dimensionality drift")
    return FrozenNflEarlyModelArtifact(
        **values,
        model_fingerprint=_fingerprint(values),
    )


def frozen_nfl_early_artifact_to_dict(
    artifact: FrozenNflEarlyModelArtifact,
) -> dict[str, Any]:
    return _canonical(asdict(artifact))


def predict_frozen_nfl_early_home_win_probability(
    artifact: FrozenNflEarlyModelArtifact,
    feature_values: Iterable[float | None],
) -> float:
    values = tuple(feature_values)
    if len(values) != len(FROZEN_NFL_EARLY_FEATURE_NAMES):
        raise ValueError("frozen NFL early inference requires exactly four features")
    standardized = []
    for index, value in enumerate(values):
        numeric = artifact.imputer_statistics[index] if value is None else float(value)
        if not math.isfinite(numeric):
            raise ValueError("frozen NFL early inference values must be finite")
        standardized.append(
            (numeric - artifact.scaler_means[index])
            / artifact.scaler_scales[index]
        )
    logit = artifact.intercept + sum(
        coefficient * value
        for coefficient, value in zip(
            artifact.coefficients,
            standardized,
            strict=True,
        )
    )
    return 1 / (1 + math.exp(-logit))


def assert_committed_frozen_nfl_early_artifact(
    artifact: FrozenNflEarlyModelArtifact,
    committed: dict[str, Any],
) -> None:
    if frozen_nfl_early_artifact_to_dict(artifact) != committed:
        raise RuntimeError("committed frozen NFL early artifact differs from deterministic fit")


def _validate_training_population(examples) -> None:
    if not examples:
        raise ValueError("frozen NFL early training population cannot be empty")
    if tuple(sorted(
        examples,
        key=lambda item: (item.kickoff, item.game_id),
    )) != examples:
        raise ValueError("frozen NFL early training rows must be chronological")
    seasons = {item.season for item in examples}
    if seasons != set(FROZEN_NFL_EARLY_TRAINING_SEASONS):
        raise ValueError("frozen NFL early training must contain seasons 2019-2024 only")
    if len({item.game_id for item in examples}) != len(examples):
        raise ValueError("frozen NFL early training game IDs must be unique")
    if any(
        len(item.feature_values) != len(NFL_EARLY_MONEYLINE_FEATURE_NAMES)
        for item in examples
    ):
        raise ValueError("frozen NFL early source feature representation drift")


def _matrix(examples) -> list[list[float]]:
    return [
        [
            math.nan if item.feature_values[index] is None
            else item.feature_values[index]
            for index in FROZEN_NFL_EARLY_FEATURE_INDEXES
        ]
        for item in examples
    ]


def _pipeline() -> Pipeline:
    spec = FROZEN_NFL_EARLY_SPECIFICATION
    return Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median", add_indicator=False)),
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(
            C=spec.regularization_c,
            solver=spec.solver,
            max_iter=spec.max_iterations,
            random_state=spec.random_state,
        )),
    ])


def _fingerprint(value: Any) -> str:
    return sha256(json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("frozen NFL early metadata cannot contain nonfinite values")
    return value
