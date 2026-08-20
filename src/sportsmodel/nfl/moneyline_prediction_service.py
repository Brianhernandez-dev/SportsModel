from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID

from psycopg2.errors import DeadlockDetected, SerializationFailure

from sportsmodel.database.connection import get_connection
from sportsmodel.database.nfl_moneyline_prediction_repository import (
    complete_nfl_prediction_run,
    count_nfl_predictions_for_run,
    create_nfl_prediction_run,
    database_clock,
    fail_nfl_prediction_run,
    insert_nfl_game_prediction,
    list_existing_official_nfl_game_ids,
    list_nfl_prediction_targets,
    load_nfl_prediction_run_by_key,
    lock_nfl_prediction_run,
)
from sportsmodel.database.nfl_team_game_statistics_repository import (
    CursorNflTeamHistoryRepository,
)
from sportsmodel.nfl.features import NFLFeatureDataProvider
from sportsmodel.nfl.moneyline_frozen import (
    FrozenNFLMoneylineArtifact,
    fingerprint_payload,
    load_frozen_nfl_early_artifact,
    load_frozen_nfl_mature_artifact,
)
from sportsmodel.nfl.moneyline_inference import (
    NFLMoneylineInferenceResult,
    NFLPredictedSide,
    infer_nfl_moneyline,
)
from sportsmodel.nfl.moneyline_prediction import (
    NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION,
    NFLMoneylinePredictionExecutionResult,
    NFLMoneylinePredictionRunStatus,
    NFLMoneylinePredictionRunType,
    PersistedNFLMoneylinePrediction,
    canonical_nfl_moneyline_probability_text,
    canonicalize_nfl_moneyline_probability,
)
from sportsmodel.nfl.moneyline_routing import (
    NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
)


ConnectionFactory = Callable[[], Any]
ArtifactLoader = Callable[[], FrozenNFLMoneylineArtifact]
InferenceRunner = Callable[..., NFLMoneylineInferenceResult]
_MAX_CONCURRENCY_ATTEMPTS = 3
_RETRYABLE_CONCURRENCY_ERRORS = (SerializationFailure, DeadlockDetected)


@dataclass(frozen=True)
class _PreparedPrediction:
    feature_payload: dict[str, Any]
    source_trace_payload: dict[str, Any]
    source_trace_sha256: str
    model_home_win_probability: Decimal
    frozen_route_home_baseline_probability: Decimal
    classification_threshold: Decimal
    predicted_side: NFLPredictedSide


def execute_nfl_moneyline_prediction_run(
    *,
    season: int,
    target_date: date,
    slate_start_time: datetime,
    slate_end_time: datetime,
    run_type: NFLMoneylinePredictionRunType,
    run_key: UUID | None,
    dry_run: bool,
) -> NFLMoneylinePredictionExecutionResult:
    """Execute the strict production path with committed inference identities."""

    return _execute_nfl_moneyline_prediction_run(
        season=season,
        target_date=target_date,
        slate_start_time=slate_start_time,
        slate_end_time=slate_end_time,
        run_type=run_type,
        run_key=run_key,
        dry_run=dry_run,
        connection_factory=get_connection,
        early_artifact_loader=load_frozen_nfl_early_artifact,
        mature_artifact_loader=load_frozen_nfl_mature_artifact,
        inference_runner=infer_nfl_moneyline,
    )


def _execute_nfl_moneyline_prediction_run(
    *,
    season: int,
    target_date: date,
    slate_start_time: datetime,
    slate_end_time: datetime,
    run_type: NFLMoneylinePredictionRunType,
    run_key: UUID | None,
    dry_run: bool,
    connection_factory: ConnectionFactory = get_connection,
    early_artifact_loader: ArtifactLoader = load_frozen_nfl_early_artifact,
    mature_artifact_loader: ArtifactLoader = load_frozen_nfl_mature_artifact,
    inference_runner: InferenceRunner = infer_nfl_moneyline,
) -> NFLMoneylinePredictionExecutionResult:
    """Internal dependency-injected path used by focused tests."""

    for attempt in range(1, _MAX_CONCURRENCY_ATTEMPTS + 1):
        try:
            return _execute_nfl_moneyline_prediction_run_once(
                season=season,
                target_date=target_date,
                slate_start_time=slate_start_time,
                slate_end_time=slate_end_time,
                run_type=run_type,
                run_key=run_key,
                dry_run=dry_run,
                connection_factory=connection_factory,
                early_artifact_loader=early_artifact_loader,
                mature_artifact_loader=mature_artifact_loader,
                inference_runner=inference_runner,
            )
        except _RETRYABLE_CONCURRENCY_ERRORS:
            if attempt == _MAX_CONCURRENCY_ATTEMPTS:
                raise

    raise AssertionError("unreachable NFL prediction concurrency retry state")


def _execute_nfl_moneyline_prediction_run_once(
    *,
    season: int,
    target_date: date,
    slate_start_time: datetime,
    slate_end_time: datetime,
    run_type: NFLMoneylinePredictionRunType,
    run_key: UUID | None,
    dry_run: bool,
    connection_factory: ConnectionFactory,
    early_artifact_loader: ArtifactLoader,
    mature_artifact_loader: ArtifactLoader,
    inference_runner: InferenceRunner,
) -> NFLMoneylinePredictionExecutionResult:
    """Infer one explicit UTC slate and optionally persist it atomically."""

    _validate_request(
        season=season,
        slate_start_time=slate_start_time,
        slate_end_time=slate_end_time,
        run_key=run_key,
        dry_run=dry_run,
    )
    early_artifact = early_artifact_loader()
    mature_artifact = mature_artifact_loader()

    if dry_run:
        return _execute_dry_run(
            season=season,
            slate_start_time=slate_start_time,
            slate_end_time=slate_end_time,
            run_type=run_type,
            early_artifact=early_artifact,
            mature_artifact=mature_artifact,
            connection_factory=connection_factory,
            inference_runner=inference_runner,
        )

    assert run_key is not None
    preflight = connection_factory()
    prediction_run_id: int | None = None
    expected_slate_fingerprint: str
    expected_target_count: int
    try:
        with preflight.cursor() as cursor:
            existing = load_nfl_prediction_run_by_key(
                cursor, run_key=run_key,
            )
            if existing is not None:
                _verify_existing_run_request(
                    existing=existing,
                    season=season,
                    target_date=target_date,
                    slate_start_time=slate_start_time,
                    slate_end_time=slate_end_time,
                    run_type=run_type,
                    early_artifact=early_artifact,
                    mature_artifact=mature_artifact,
                )
                if existing.status is NFLMoneylinePredictionRunStatus.COMPLETED:
                    return _completed_execution_result(existing)
                _require_recoverable_running_run(cursor, existing)
                prediction_run_id = existing.prediction_run_id
                expected_slate_fingerprint = existing.slate_fingerprint
                expected_target_count = existing.target_count
            else:
                targets = list_nfl_prediction_targets(
                    cursor,
                    season=season,
                    slate_start_time=slate_start_time,
                    slate_end_time=slate_end_time,
                )
                expected_slate_fingerprint = _slate_fingerprint(targets)
                expected_target_count = len(targets)
                if (
                    run_type is NFLMoneylinePredictionRunType.OFFICIAL
                    and expected_target_count == 0
                ):
                    raise ValueError(
                        "official NFL prediction slate must contain at least one target"
                    )
                request_sha = _request_fingerprint(
                    season=season,
                    target_date=target_date,
                    slate_start_time=slate_start_time,
                    slate_end_time=slate_end_time,
                    run_type=run_type,
                    slate_fingerprint=expected_slate_fingerprint,
                    early_artifact=early_artifact,
                    mature_artifact=mature_artifact,
                )
                created = create_nfl_prediction_run(
                    cursor,
                    run_key=run_key,
                    request_sha256=request_sha,
                    run_type=run_type,
                    evaluation_protocol_version=(
                        NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION
                    ),
                    routing_contract_version=(
                        NFL_MONEYLINE_ROUTING_CONTRACT_VERSION
                    ),
                    season=season,
                    target_date=target_date,
                    slate_start_time=slate_start_time,
                    slate_end_time=slate_end_time,
                    slate_fingerprint=expected_slate_fingerprint,
                    early_artifact=early_artifact,
                    mature_artifact=mature_artifact,
                    target_count=expected_target_count,
                )
                if created is None:
                    existing = load_nfl_prediction_run_by_key(
                        cursor, run_key=run_key,
                    )
                    if existing is None:
                        raise RuntimeError(
                            "run_key conflict did not expose an existing run"
                        )
                    _verify_existing_run_request(
                        existing=existing,
                        season=season,
                        target_date=target_date,
                        slate_start_time=slate_start_time,
                        slate_end_time=slate_end_time,
                        run_type=run_type,
                        early_artifact=early_artifact,
                        mature_artifact=mature_artifact,
                    )
                    if (
                        existing.slate_fingerprint
                        != expected_slate_fingerprint
                        or existing.target_count != expected_target_count
                    ):
                        raise ValueError(
                            "run_key is already bound to a different slate identity"
                        )
                    if existing.status is NFLMoneylinePredictionRunStatus.COMPLETED:
                        return _completed_execution_result(existing)
                    _require_recoverable_running_run(cursor, existing)
                    prediction_run_id = existing.prediction_run_id
                else:
                    prediction_run_id = created.prediction_run_id
        preflight.commit()
    except Exception:
        preflight.rollback()
        raise
    finally:
        preflight.close()

    assert prediction_run_id is not None
    try:
        return _execute_write_transaction(
            prediction_run_id=prediction_run_id,
            season=season,
            slate_start_time=slate_start_time,
            slate_end_time=slate_end_time,
            run_type=run_type,
            expected_slate_fingerprint=expected_slate_fingerprint,
            expected_target_count=expected_target_count,
            early_artifact=early_artifact,
            mature_artifact=mature_artifact,
            connection_factory=connection_factory,
            inference_runner=inference_runner,
        )
    except _RETRYABLE_CONCURRENCY_ERRORS:
        raise
    except Exception as error:
        _retain_failed_run(
            prediction_run_id=prediction_run_id,
            failure_message=f"{type(error).__name__}: {error}",
            connection_factory=connection_factory,
        )
        raise


def _execute_write_transaction(
    *,
    prediction_run_id: int,
    season: int,
    slate_start_time: datetime,
    slate_end_time: datetime,
    run_type: NFLMoneylinePredictionRunType,
    expected_slate_fingerprint: str,
    expected_target_count: int,
    early_artifact: FrozenNFLMoneylineArtifact,
    mature_artifact: FrozenNFLMoneylineArtifact,
    connection_factory: ConnectionFactory,
    inference_runner: InferenceRunner,
) -> NFLMoneylinePredictionExecutionResult:
    connection = connection_factory()
    try:
        connection.set_session(isolation_level="REPEATABLE READ")
        with connection.cursor() as cursor:
            locked = lock_nfl_prediction_run(
                cursor, prediction_run_id=prediction_run_id,
            )
            if locked.status is NFLMoneylinePredictionRunStatus.COMPLETED:
                connection.rollback()
                return _completed_execution_result(locked)
            if locked.status is not NFLMoneylinePredictionRunStatus.RUNNING:
                raise RuntimeError("NFL Moneyline run is not recoverable")
            targets = list_nfl_prediction_targets(
                cursor,
                season=season,
                slate_start_time=slate_start_time,
                slate_end_time=slate_end_time,
            )
            slate_sha = _slate_fingerprint(targets)
            if (
                slate_sha != expected_slate_fingerprint
                or len(targets) != expected_target_count
            ):
                raise RuntimeError(
                    "canonical NFL slate changed after run creation"
                )
            now = database_clock(cursor)
            late_ids = tuple(
                game.game_id
                for game in targets
                if game.scheduled_start_time <= now
            )
            if late_ids:
                raise ValueError(
                    "NFL predictions must be created strictly before kickoff; "
                    f"late game IDs: {late_ids}"
                )
            if run_type is NFLMoneylinePredictionRunType.OFFICIAL:
                official_ids = list_existing_official_nfl_game_ids(
                    cursor,
                    evaluation_protocol_version=(
                        NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION
                    ),
                    game_ids=tuple(game.game_id for game in targets),
                )
                if official_ids:
                    raise ValueError(
                        "official NFL observations already exist for game IDs: "
                        f"{official_ids}"
                    )
            cursor.execute("SELECT transaction_timestamp();")
            source_data_as_of = cursor.fetchone()[0]
            inference_results = _infer_targets(
                cursor=cursor,
                targets=targets,
                early_artifact=early_artifact,
                mature_artifact=mature_artifact,
                inference_runner=inference_runner,
            )
            payloads = tuple(
                _prediction_payloads(inference)
                for inference in inference_results
            )
            source_snapshot_sha = _source_snapshot_fingerprint(
                inference_results, payloads
            )
            prediction_set_sha = _prediction_set_fingerprint(
                inference_results, payloads
            )
            persisted: list[PersistedNFLMoneylinePrediction] = []
            for game, inference, payload in zip(
                targets, inference_results, payloads, strict=True
            ):
                prediction_id, prediction_created_at = (
                    insert_nfl_game_prediction(
                        cursor,
                        prediction_run_id=prediction_run_id,
                        run_type=run_type,
                        evaluation_protocol_version=(
                            NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION
                        ),
                        inference=inference,
                        neutral_site=game.neutral_site,
                        source_data_as_of=source_data_as_of,
                        feature_payload=payload.feature_payload,
                        source_trace_payload=payload.source_trace_payload,
                        source_trace_sha256=payload.source_trace_sha256,
                        model_home_win_probability=(
                            payload.model_home_win_probability
                        ),
                        frozen_route_home_baseline_probability=(
                            payload.frozen_route_home_baseline_probability
                        ),
                        classification_threshold=payload.classification_threshold,
                        predicted_side=payload.predicted_side,
                    )
                )
                persisted.append(PersistedNFLMoneylinePrediction(
                    prediction_id=prediction_id,
                    prediction_created_at=prediction_created_at,
                    inference=inference,
                    feature_payload=payload.feature_payload,
                    source_trace_payload=payload.source_trace_payload,
                    source_trace_sha256=payload.source_trace_sha256,
                    model_home_win_probability=(
                        payload.model_home_win_probability
                    ),
                    frozen_route_home_baseline_probability=(
                        payload.frozen_route_home_baseline_probability
                    ),
                    classification_threshold=payload.classification_threshold,
                    predicted_side=payload.predicted_side,
                ))
            completed = complete_nfl_prediction_run(
                cursor,
                prediction_run_id=prediction_run_id,
                source_data_as_of=source_data_as_of,
                source_snapshot_sha256=source_snapshot_sha,
                prediction_set_sha256=prediction_set_sha,
                prediction_count=len(persisted),
            )
        connection.commit()
        return NFLMoneylinePredictionExecutionResult(
            dry_run=False,
            run=completed,
            predictions=tuple(persisted),
            inference_results=inference_results,
            slate_fingerprint=slate_sha,
            source_snapshot_sha256=source_snapshot_sha,
            prediction_set_sha256=prediction_set_sha,
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _execute_dry_run(
    *,
    season: int,
    slate_start_time: datetime,
    slate_end_time: datetime,
    run_type: NFLMoneylinePredictionRunType,
    early_artifact: FrozenNFLMoneylineArtifact,
    mature_artifact: FrozenNFLMoneylineArtifact,
    connection_factory: ConnectionFactory,
    inference_runner: InferenceRunner,
) -> NFLMoneylinePredictionExecutionResult:
    connection = connection_factory()
    try:
        connection.set_session(
            isolation_level="REPEATABLE READ", read_only=True
        )
        with connection.cursor() as cursor:
            targets = list_nfl_prediction_targets(
                cursor,
                season=season,
                slate_start_time=slate_start_time,
                slate_end_time=slate_end_time,
            )
            now = database_clock(cursor)
            if any(game.scheduled_start_time <= now for game in targets):
                raise ValueError(
                    "NFL predictions must be created strictly before kickoff"
                )
            if run_type is NFLMoneylinePredictionRunType.OFFICIAL:
                official_ids = list_existing_official_nfl_game_ids(
                    cursor,
                    evaluation_protocol_version=(
                        NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION
                    ),
                    game_ids=tuple(game.game_id for game in targets),
                )
                if official_ids:
                    raise ValueError(
                        "official NFL observations already exist for game IDs: "
                        f"{official_ids}"
                    )
            inferences = _infer_targets(
                cursor=cursor,
                targets=targets,
                early_artifact=early_artifact,
                mature_artifact=mature_artifact,
                inference_runner=inference_runner,
            )
            payloads = tuple(_prediction_payloads(item) for item in inferences)
            slate_sha = _slate_fingerprint(targets)
            source_sha = _source_snapshot_fingerprint(inferences, payloads)
            prediction_sha = _prediction_set_fingerprint(inferences, payloads)
        connection.rollback()
        return NFLMoneylinePredictionExecutionResult(
            dry_run=True,
            run=None,
            predictions=(),
            inference_results=inferences,
            slate_fingerprint=slate_sha,
            source_snapshot_sha256=source_sha,
            prediction_set_sha256=prediction_sha,
        )
    finally:
        connection.close()


def _infer_targets(
    *,
    cursor: Any,
    targets: tuple[Any, ...],
    early_artifact: FrozenNFLMoneylineArtifact,
    mature_artifact: FrozenNFLMoneylineArtifact,
    inference_runner: InferenceRunner,
) -> tuple[NFLMoneylineInferenceResult, ...]:
    repository = CursorNflTeamHistoryRepository(cursor)
    return tuple(
        inference_runner(
            game,
            provider=NFLFeatureDataProvider(game, repository=repository),
            early_artifact_loader=lambda: early_artifact,
            mature_artifact_loader=lambda: mature_artifact,
        )
        for game in targets
    )


def _prediction_payloads(
    inference: NFLMoneylineInferenceResult,
) -> _PreparedPrediction:
    feature_payload = {
        "feature_schema_version": inference.feature_schema_version,
        "ordered_feature_names": list(inference.ordered_feature_names),
        "ordered_feature_values": list(inference.ordered_feature_values),
    }
    if fingerprint_payload(feature_payload) != inference.feature_vector_fingerprint:
        raise ValueError("inference feature-vector fingerprint drift")
    source_trace = {
        "channels": [
            {
                "side": channel.side,
                "channel": channel.channel,
                "games": [
                    {
                        "game_id": game.game_id,
                        "kickoff": _utc_text(game.kickoff),
                        "season": game.season,
                        "season_type": game.season_type,
                    }
                    for game in channel.games
                ],
            }
            for channel in inference.source_trace
        ]
    }
    probability = canonicalize_nfl_moneyline_probability(
        inference.model_home_win_probability
    )
    baseline = canonicalize_nfl_moneyline_probability(
        inference.frozen_empirical_home_baseline
    )
    threshold = canonicalize_nfl_moneyline_probability(
        inference.classification_threshold
    )
    predicted_side = (
        NFLPredictedSide.HOME
        if probability >= threshold
        else NFLPredictedSide.AWAY
    )
    return _PreparedPrediction(
        feature_payload=feature_payload,
        source_trace_payload=source_trace,
        source_trace_sha256=fingerprint_payload(source_trace),
        model_home_win_probability=probability,
        frozen_route_home_baseline_probability=baseline,
        classification_threshold=threshold,
        predicted_side=predicted_side,
    )


def _slate_fingerprint(targets: tuple[Any, ...]) -> str:
    return fingerprint_payload({
        "games": [
            {
                "game_id": game.game_id,
                "season": game.season,
                "season_type": game.season_type.value,
                "kickoff": _utc_text(game.scheduled_start_time),
                "home_team_id": game.home_team_id,
                "away_team_id": game.away_team_id,
                "neutral_site": game.neutral_site,
            }
            for game in targets
        ]
    })


def _source_snapshot_fingerprint(inferences, payloads) -> str:
    return fingerprint_payload({
        "games": [
            {
                "game_id": inference.game_id,
                "source_trace_sha256": payload.source_trace_sha256,
            }
            for inference, payload in zip(inferences, payloads, strict=True)
        ]
    })


def _prediction_set_fingerprint(inferences, payloads) -> str:
    records = tuple(
        {
                "game_id": inference.game_id,
                "selected_route": inference.selected_route.value,
                "model_specification_version": (
                    inference.model_specification_version
                ),
                "feature_vector_sha256": (
                    inference.feature_vector_fingerprint
                ),
                "source_trace_sha256": payload.source_trace_sha256,
                "model_home_win_probability": (
                    canonical_nfl_moneyline_probability_text(
                        payload.model_home_win_probability
                    )
                ),
                "classification_threshold": (
                    canonical_nfl_moneyline_probability_text(
                        payload.classification_threshold
                    )
                ),
                "predicted_side": payload.predicted_side.value,
        }
        for inference, payload in zip(inferences, payloads, strict=True)
    )
    return _prediction_set_fingerprint_from_records(records)


def _prediction_set_fingerprint_from_records(
    records: tuple[dict[str, Any], ...],
) -> str:
    """Hash records reconstructed from the persisted canonical values."""

    return fingerprint_payload({
        "evaluation_protocol_version": NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION,
        "predictions": list(records),
    })


def _request_fingerprint(
    *,
    season: int,
    target_date: date,
    slate_start_time: datetime,
    slate_end_time: datetime,
    run_type: NFLMoneylinePredictionRunType,
    slate_fingerprint: str,
    early_artifact: FrozenNFLMoneylineArtifact,
    mature_artifact: FrozenNFLMoneylineArtifact,
) -> str:
    return fingerprint_payload({
        "run_type": run_type.value,
        "evaluation_protocol_version": (
            NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION
        ),
        "routing_contract_version": NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
        "season": season,
        "target_date": target_date.isoformat(),
        "slate_start_time": _utc_text(slate_start_time),
        "slate_end_time": _utc_text(slate_end_time),
        "slate_fingerprint": slate_fingerprint,
        "early": _artifact_identity(early_artifact),
        "mature": _artifact_identity(mature_artifact),
    })


def _artifact_identity(artifact: FrozenNFLMoneylineArtifact) -> dict[str, str]:
    return {
        "model_specification_version": artifact.specification_version,
        "feature_schema_version": artifact.feature_schema_version,
        "specification_fingerprint": artifact.specification_fingerprint,
        "model_fingerprint": artifact.model_fingerprint,
    }


def _verify_existing_run_request(
    *,
    existing,
    season: int,
    target_date: date,
    slate_start_time: datetime,
    slate_end_time: datetime,
    run_type: NFLMoneylinePredictionRunType,
    early_artifact: FrozenNFLMoneylineArtifact,
    mature_artifact: FrozenNFLMoneylineArtifact,
) -> None:
    expected_request_sha = _request_fingerprint(
        season=season,
        target_date=target_date,
        slate_start_time=slate_start_time,
        slate_end_time=slate_end_time,
        run_type=run_type,
        slate_fingerprint=existing.slate_fingerprint,
        early_artifact=early_artifact,
        mature_artifact=mature_artifact,
    )
    early_identity = _artifact_identity(early_artifact)
    mature_identity = _artifact_identity(mature_artifact)
    if (
        existing.request_sha256 != expected_request_sha
        or existing.run_type is not run_type
        or existing.evaluation_protocol_version
        != NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION
        or existing.routing_contract_version
        != NFL_MONEYLINE_ROUTING_CONTRACT_VERSION
        or existing.season != season
        or existing.target_date != target_date
        or existing.slate_start_time != slate_start_time
        or existing.slate_end_time != slate_end_time
        or existing.early_model_specification_version
        != early_identity["model_specification_version"]
        or existing.early_feature_schema_version
        != early_identity["feature_schema_version"]
        or existing.early_specification_fingerprint
        != early_identity["specification_fingerprint"]
        or existing.early_model_fingerprint
        != early_identity["model_fingerprint"]
        or existing.mature_model_specification_version
        != mature_identity["model_specification_version"]
        or existing.mature_feature_schema_version
        != mature_identity["feature_schema_version"]
        or existing.mature_specification_fingerprint
        != mature_identity["specification_fingerprint"]
        or existing.mature_model_fingerprint
        != mature_identity["model_fingerprint"]
    ):
        raise ValueError("run_key is already bound to a different request identity")


def _require_recoverable_running_run(cursor: Any, existing: Any) -> None:
    if existing.status is NFLMoneylinePredictionRunStatus.FAILED:
        raise ValueError("failed run_key cannot be reused; supply a new run_key")
    if existing.status is not NFLMoneylinePredictionRunStatus.RUNNING:
        raise RuntimeError("run_key has an unknown non-recoverable status")
    if count_nfl_predictions_for_run(
        cursor,
        prediction_run_id=existing.prediction_run_id,
    ) != 0:
        raise RuntimeError(
            "running run_key has committed child predictions and cannot be "
            "recovered safely"
        )


def _completed_execution_result(existing: Any) -> NFLMoneylinePredictionExecutionResult:
    return NFLMoneylinePredictionExecutionResult(
        dry_run=False,
        run=existing,
        predictions=(),
        inference_results=(),
        slate_fingerprint=existing.slate_fingerprint,
        source_snapshot_sha256=existing.source_snapshot_sha256 or "",
        prediction_set_sha256=existing.prediction_set_sha256 or "",
    )


def _retain_failed_run(
    *, prediction_run_id: int, failure_message: str,
    connection_factory: ConnectionFactory,
) -> None:
    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            fail_nfl_prediction_run(
                cursor,
                prediction_run_id=prediction_run_id,
                failure_message=failure_message,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _validate_request(
    *, season: int, slate_start_time: datetime, slate_end_time: datetime,
    run_key: UUID | None, dry_run: bool,
) -> None:
    if season < 2026:
        raise ValueError("NFL forward prediction season must be 2026 or later")
    for value, name in (
        (slate_start_time, "slate_start_time"),
        (slate_end_time, "slate_end_time"),
    ):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware UTC")
        if value.utcoffset().total_seconds() != 0:
            raise ValueError(f"{name} must use an explicit UTC offset")
    if slate_start_time >= slate_end_time:
        raise ValueError("slate_start_time must precede slate_end_time")
    if not dry_run and run_key is None:
        raise ValueError("run_key is required for a persisted run")


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
