from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sportsmodel.nfl.moneyline_inference import NFLMoneylineInferenceResult


NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION = (
    "nfl_moneyline_forward_0.1.0"
)


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


@dataclass(frozen=True)
class NFLMoneylinePredictionExecutionResult:
    dry_run: bool
    run: NFLMoneylinePredictionRun | None
    predictions: tuple[PersistedNFLMoneylinePrediction, ...]
    inference_results: tuple[NFLMoneylineInferenceResult, ...]
    slate_fingerprint: str
    source_snapshot_sha256: str
    prediction_set_sha256: str
