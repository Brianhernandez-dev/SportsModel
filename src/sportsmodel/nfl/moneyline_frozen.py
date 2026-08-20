"""Strict, fit-free loaders for frozen NFL Moneyline model artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

from sportsmodel.nfl.moneyline_routing import NFLMoneylineRoute


EARLY_ARTIFACT_PATH = Path(
    "artifacts/nfl_moneyline_early_frozen_0.1.0.json"
)
MATURE_ARTIFACT_PATH = Path(
    "artifacts/nfl_moneyline_frozen_0.1.0.json"
)

EARLY_SPECIFICATION_VERSION = "nfl_moneyline_early_frozen_0.1.0"
MATURE_SPECIFICATION_VERSION = "nfl_moneyline_frozen_0.1.0"
EARLY_FEATURE_SCHEMA_VERSION = "nfl_moneyline_early_0.1.0"
MATURE_FEATURE_SCHEMA_VERSION = "nfl_moneyline_0.2.0"
EARLY_SPECIFICATION_FINGERPRINT = (
    "109d8bf693f67836d0acd39a631a50dccfdfaea61284aa9ef09349f2b71b9675"
)
EARLY_MODEL_FINGERPRINT = (
    "ea7a9e90c59e4cdd87a2115895dddbfe117feb8b5f53a593eb6c3007fe0c1fd8"
)
MATURE_MODEL_FINGERPRINT = (
    "cb7b1d0dde2272ed49317f25441a32dc6518b25950266e577374bf13b28b20ac"
)

EARLY_FEATURE_NAMES = (
    "prior_season_games_played_difference",
    "prior_season_win_percentage_difference",
    "prior_season_average_point_differential_difference",
    "prior_season_average_turnover_differential_difference",
)
MATURE_FEATURE_NAMES = (
    "minimum_prior_games",
    "matchup_prior_games_used_difference",
    "matchup_win_percentage_difference",
    "matchup_average_points_for_difference",
    "matchup_average_points_against_difference",
    "matchup_average_passing_yards_difference",
    "matchup_average_passing_yards_allowed_difference",
    "matchup_average_rushing_yards_difference",
    "matchup_average_rushing_yards_allowed_difference",
    "matchup_average_turnovers_difference",
    "matchup_average_takeaways_difference",
    "matchup_rolling_3_games_used_difference",
    "matchup_rolling_3_average_points_for_difference",
    "matchup_rolling_3_average_points_against_difference",
    "matchup_rolling_3_average_turnover_differential_difference",
    "matchup_rolling_5_games_used_difference",
    "matchup_rolling_5_average_points_for_difference",
    "matchup_rolling_5_average_points_against_difference",
    "matchup_rolling_5_average_turnover_differential_difference",
)

_COMMON_FIELDS = {
    "classification_threshold",
    "coefficients",
    "dataset_fingerprint",
    "feature_names",
    "feature_schema_version",
    "historical_evidence_status",
    "imputation",
    "imputer_statistics",
    "intercept",
    "max_iterations",
    "model_fingerprint",
    "next_forward_evidence_season",
    "random_state",
    "regularization_c",
    "scaler_means",
    "scaler_scales",
    "scaling",
    "solver",
    "specification_fingerprint",
    "specification_version",
    "target",
    "training_home_win_rate",
    "training_population",
    "training_row_count",
    "training_seasons",
}
_EARLY_FIELDS = _COMMON_FIELDS | {
    "retrospective_status",
    "routing_population",
}
_MATURE_FIELDS = _COMMON_FIELDS | {
    "evidence_status",
    "mature_eligibility_policy",
}


@dataclass(frozen=True)
class FrozenNFLMoneylineArtifact:
    route: NFLMoneylineRoute
    specification_version: str
    specification_fingerprint: str
    feature_schema_version: str
    feature_names: tuple[str, ...]
    target: str
    training_seasons: tuple[int, ...]
    training_population: str
    training_row_count: int
    training_home_win_rate: float
    dataset_fingerprint: str
    regularization_c: float
    solver: str
    max_iterations: int
    random_state: int
    imputation: str
    scaling: str
    classification_threshold: float
    imputer_statistics: tuple[float, ...]
    scaler_means: tuple[float, ...]
    scaler_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    historical_evidence_status: str
    next_forward_evidence_season: int
    model_fingerprint: str
    mature_eligibility_policy: str | None = None
    routing_population: str | None = None
    evidence_status: tuple[tuple[str, str], ...] = ()


def load_frozen_nfl_early_artifact(
    path: Path = EARLY_ARTIFACT_PATH,
) -> FrozenNFLMoneylineArtifact:
    return _load_artifact(
        path=path,
        route=NFLMoneylineRoute.EARLY,
        required_fields=_EARLY_FIELDS,
        expected_specification_version=EARLY_SPECIFICATION_VERSION,
        expected_schema_version=EARLY_FEATURE_SCHEMA_VERSION,
        expected_feature_names=EARLY_FEATURE_NAMES,
        expected_training_seasons=tuple(range(2019, 2025)),
        expected_specification_fingerprint=(
            EARLY_SPECIFICATION_FINGERPRINT
        ),
        expected_model_fingerprint=EARLY_MODEL_FINGERPRINT,
    )


def load_frozen_nfl_mature_artifact(
    path: Path = MATURE_ARTIFACT_PATH,
) -> FrozenNFLMoneylineArtifact:
    artifact = _load_artifact(
        path=path,
        route=NFLMoneylineRoute.MATURE,
        required_fields=_MATURE_FIELDS,
        expected_specification_version=MATURE_SPECIFICATION_VERSION,
        expected_schema_version=MATURE_FEATURE_SCHEMA_VERSION,
        expected_feature_names=MATURE_FEATURE_NAMES,
        expected_training_seasons=tuple(range(2018, 2025)),
        expected_specification_fingerprint=None,
        expected_model_fingerprint=MATURE_MODEL_FINGERPRINT,
    )
    expected = mature_specification_fingerprint()
    if artifact.specification_fingerprint != expected:
        raise ValueError("mature artifact specification fingerprint mismatch")
    return artifact


def mature_specification_fingerprint() -> str:
    return fingerprint_payload(mature_specification_payload())


def mature_specification_payload() -> dict[str, Any]:
    return {
        "specification_version": MATURE_SPECIFICATION_VERSION,
        "feature_schema_version": MATURE_FEATURE_SCHEMA_VERSION,
        "feature_names": list(MATURE_FEATURE_NAMES),
        "target": "home_win",
        "training_seasons": list(range(2018, 2025)),
        "mature_eligibility_policy": (
            "home_current_prior_games >= 3 and "
            "away_current_prior_games >= 3"
        ),
        "imputation": "training-row median",
        "scaling": "training-row StandardScaler",
        "regularization_c": 1.0,
        "solver": "lbfgs",
        "max_iterations": 5000,
        "random_state": 42,
        "classification_threshold": 0.5,
    }


def predict_frozen_home_win_probability(
    artifact: FrozenNFLMoneylineArtifact,
    feature_values: tuple[float | int | None, ...],
) -> float:
    if len(feature_values) != len(artifact.feature_names):
        raise ValueError("feature count does not match frozen artifact")
    standardized: list[float] = []
    for index, value in enumerate(feature_values):
        numeric = (
            artifact.imputer_statistics[index]
            if value is None
            else _finite_number(value, "feature value")
        )
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
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    exponential = math.exp(logit)
    return exponential / (1.0 + exponential)


def fingerprint_payload(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _load_artifact(
    *,
    path: Path,
    route: NFLMoneylineRoute,
    required_fields: set[str],
    expected_specification_version: str,
    expected_schema_version: str,
    expected_feature_names: tuple[str, ...],
    expected_training_seasons: tuple[int, ...],
    expected_specification_fingerprint: str | None,
    expected_model_fingerprint: str,
) -> FrozenNFLMoneylineArtifact:
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_raise_nonfinite(value)),
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to load frozen artifact: {path}") from error
    if not isinstance(raw, dict):
        raise ValueError("frozen artifact must be a JSON object")
    actual_fields = set(raw)
    if actual_fields != required_fields:
        missing = sorted(required_fields - actual_fields)
        unknown = sorted(actual_fields - required_fields)
        raise ValueError(
            f"frozen artifact fields mismatch; missing={missing}, "
            f"unknown={unknown}"
        )
    if raw["specification_version"] != expected_specification_version:
        raise ValueError("frozen artifact specification version mismatch")
    if raw["feature_schema_version"] != expected_schema_version:
        raise ValueError("frozen artifact feature schema mismatch")
    feature_names = _string_tuple(raw["feature_names"], "feature_names")
    if feature_names != expected_feature_names:
        raise ValueError("frozen artifact ordered feature names mismatch")
    training_seasons = _integer_tuple(
        raw["training_seasons"], "training_seasons"
    )
    if training_seasons != expected_training_seasons:
        raise ValueError("frozen artifact training seasons mismatch")
    if raw["target"] != "home_win":
        raise ValueError("frozen artifact target mismatch")
    specification_fingerprint = _hash(
        raw["specification_fingerprint"], "specification_fingerprint"
    )
    if (
        expected_specification_fingerprint is not None
        and specification_fingerprint
        != expected_specification_fingerprint
    ):
        raise ValueError("frozen artifact specification fingerprint mismatch")
    model_fingerprint = _hash(raw["model_fingerprint"], "model_fingerprint")
    model_payload = dict(raw)
    del model_payload["model_fingerprint"]
    if fingerprint_payload(model_payload) != model_fingerprint:
        raise ValueError("frozen artifact model fingerprint mismatch")

    dimensions = len(feature_names)
    imputer = _numeric_tuple(raw["imputer_statistics"], "imputer_statistics")
    means = _numeric_tuple(raw["scaler_means"], "scaler_means")
    scales = _numeric_tuple(raw["scaler_scales"], "scaler_scales")
    coefficients = _numeric_tuple(raw["coefficients"], "coefficients")
    if any(len(values) != dimensions for values in (
        imputer, means, scales, coefficients,
    )):
        raise ValueError("frozen artifact fitted coefficient dimensionality mismatch")
    if any(value <= 0 for value in scales):
        raise ValueError("frozen artifact scaler scales must be positive")

    training_row_count = _positive_int(
        raw["training_row_count"], "training_row_count"
    )
    next_forward = _positive_int(
        raw["next_forward_evidence_season"],
        "next_forward_evidence_season",
    )
    max_iterations = _positive_int(raw["max_iterations"], "max_iterations")
    random_state = _nonnegative_int(raw["random_state"], "random_state")
    regularization_c = _finite_number(raw["regularization_c"], "regularization_c")
    threshold = _finite_number(
        raw["classification_threshold"], "classification_threshold"
    )
    home_rate = _finite_number(
        raw["training_home_win_rate"], "training_home_win_rate"
    )
    if regularization_c <= 0 or not 0 <= threshold <= 1 or not 0 <= home_rate <= 1:
        raise ValueError("frozen artifact scalar model values are invalid")
    for field in (
        "dataset_fingerprint",
        "historical_evidence_status",
        "imputation",
        "scaling",
        "solver",
        "training_population",
    ):
        _nonempty_string(raw[field], field)
    _hash(raw["dataset_fingerprint"], "dataset_fingerprint")

    evidence_status: tuple[tuple[str, str], ...] = ()
    mature_policy = None
    routing_population = None
    if route is NFLMoneylineRoute.MATURE:
        mature_policy = _nonempty_string(
            raw["mature_eligibility_policy"], "mature_eligibility_policy"
        )
        evidence = raw["evidence_status"]
        if not isinstance(evidence, dict) or set(evidence) != {
            "2018_2024", "2025", "2026_plus",
        }:
            raise ValueError("mature artifact evidence status mismatch")
        evidence_status = tuple(
            (key, _nonempty_string(evidence[key], f"evidence_status.{key}"))
            for key in ("2018_2024", "2025", "2026_plus")
        )
        expected_imputation = "training-row median"
        expected_scaling = "training-row StandardScaler"
    else:
        routing_population = _nonempty_string(
            raw["routing_population"], "routing_population"
        )
        _nonempty_string(raw["retrospective_status"], "retrospective_status")
        expected_imputation = (
            "training-row SimpleImputer(strategy='median', "
            "add_indicator=False)"
        )
        expected_scaling = "training-row StandardScaler"

    if (
        regularization_c != 1.0
        or raw["solver"] != "lbfgs"
        or max_iterations != 5000
        or random_state != 42
        or threshold != 0.5
        or next_forward != 2026
        or raw["imputation"] != expected_imputation
        or raw["scaling"] != expected_scaling
    ):
        raise ValueError("frozen artifact preprocessing or model parameter drift")
    if model_fingerprint != expected_model_fingerprint:
        raise ValueError("frozen artifact identity differs from committed model")

    return FrozenNFLMoneylineArtifact(
        route=route,
        specification_version=expected_specification_version,
        specification_fingerprint=specification_fingerprint,
        feature_schema_version=expected_schema_version,
        feature_names=feature_names,
        target="home_win",
        training_seasons=training_seasons,
        training_population=raw["training_population"],
        training_row_count=training_row_count,
        training_home_win_rate=home_rate,
        dataset_fingerprint=raw["dataset_fingerprint"],
        regularization_c=regularization_c,
        solver=raw["solver"],
        max_iterations=max_iterations,
        random_state=random_state,
        imputation=raw["imputation"],
        scaling=raw["scaling"],
        classification_threshold=threshold,
        imputer_statistics=imputer,
        scaler_means=means,
        scaler_scales=scales,
        coefficients=coefficients,
        intercept=_finite_number(raw["intercept"], "intercept"),
        historical_evidence_status=raw["historical_evidence_status"],
        next_forward_evidence_season=next_forward,
        model_fingerprint=model_fingerprint,
        mature_eligibility_policy=mature_policy,
        routing_population=routing_population,
        evidence_status=evidence_status,
    )


def _numeric_tuple(value: Any, field: str) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return tuple(_finite_number(item, field) for item in value)


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return tuple(_nonempty_string(item, field) for item in value)


def _integer_tuple(value: Any, field: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return tuple(_positive_int(item, field) for item in value)


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must contain numeric values")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field} must contain finite values")
    return numeric


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value


def _hash(value: Any, field: str) -> str:
    text = _nonempty_string(value, field)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field} must be a lowercase SHA-256 fingerprint")
    return text


def _raise_nonfinite(value: str) -> None:
    raise ValueError(f"frozen artifact contains nonfinite JSON value: {value}")
