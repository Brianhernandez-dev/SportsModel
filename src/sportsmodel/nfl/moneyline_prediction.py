from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from enum import StrEnum
import math
from typing import Any
from uuid import UUID

from sportsmodel.nfl.moneyline_inference import (
    NFLMoneylineInferenceResult,
    NFLPredictedSide,
)


NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION = (
    "nfl_moneyline_forward_0.1.0"
)
NFL_MONEYLINE_PROBABILITY_QUANTUM = Decimal("0.0000000000000001")


def canonicalize_nfl_moneyline_probability(
    value: float | Decimal,
) -> Decimal:
    """Return the persisted 16-place probability using round-half-even."""

    if isinstance(value, bool):
        raise TypeError("NFL Moneyline probability must be numeric")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NFL Moneyline probability must be finite")
    try:
        decimal_value = Decimal(str(value))
        if not decimal_value.is_finite():
            raise ValueError("NFL Moneyline probability must be finite")
        canonical = decimal_value.quantize(
            NFL_MONEYLINE_PROBABILITY_QUANTUM,
            rounding=ROUND_HALF_EVEN,
        )
    except (InvalidOperation, ValueError) as error:
        raise ValueError("NFL Moneyline probability cannot be canonicalized") from error
    if not Decimal("0") <= canonical <= Decimal("1"):
        raise ValueError("NFL Moneyline probability must be between zero and one")
    return canonical


def canonical_nfl_moneyline_probability_text(
    value: float | Decimal,
) -> str:
    """Serialize exactly as the NUMERIC(18,16) database representation."""

    return format(canonicalize_nfl_moneyline_probability(value), ".16f")


class NFLMoneylinePredictionRunType(StrEnum):
    OFFICIAL = "official"
    PREVIEW = "preview"


class NFLMoneylinePredictionRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class NFLMoneylinePredictionRun:
    prediction_run_id: int
    run_key: UUID
    request_sha256: str
    run_type: NFLMoneylinePredictionRunType
    evaluation_protocol_version: str
    routing_contract_version: str
    season: int
    target_date: date
    slate_start_time: datetime
    slate_end_time: datetime
    slate_fingerprint: str
    early_model_specification_version: str
    early_feature_schema_version: str
    early_specification_fingerprint: str
    early_model_fingerprint: str
    mature_model_specification_version: str
    mature_feature_schema_version: str
    mature_specification_fingerprint: str
    mature_model_fingerprint: str
    target_count: int
    prediction_count: int
    status: NFLMoneylinePredictionRunStatus
    source_data_as_of: datetime | None
    source_snapshot_sha256: str | None
    prediction_set_sha256: str | None
    failure_message: str | None


@dataclass(frozen=True)
class PersistedNFLMoneylinePrediction:
    prediction_id: int
    prediction_created_at: datetime
    inference: NFLMoneylineInferenceResult
    feature_payload: dict[str, Any]
    source_trace_payload: dict[str, Any]
    source_trace_sha256: str
    model_home_win_probability: Decimal
    frozen_route_home_baseline_probability: Decimal
    classification_threshold: Decimal
    predicted_side: NFLPredictedSide


@dataclass(frozen=True)
class NFLMoneylinePredictionExecutionResult:
    dry_run: bool
    run: NFLMoneylinePredictionRun | None
    predictions: tuple[PersistedNFLMoneylinePrediction, ...]
    inference_results: tuple[NFLMoneylineInferenceResult, ...]
    slate_fingerprint: str
    source_snapshot_sha256: str
    prediction_set_sha256: str
