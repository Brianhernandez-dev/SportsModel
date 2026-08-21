from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg2.extras import Json

from sportsmodel.nfl.models import NflGame, NflGameStatus, NflSeasonType
from sportsmodel.nfl.moneyline_inference import NFLPredictedSide
from sportsmodel.nfl.moneyline_prediction import (
    NFLMoneylinePredictionRun,
    NFLMoneylinePredictionRunStatus,
    NFLMoneylinePredictionRunType,
)


def list_nfl_prediction_targets(
    cursor: Any,
    *,
    season: int,
    slate_start_time: datetime,
    slate_end_time: datetime,
) -> tuple[NflGame, ...]:
    cursor.execute(
        """
        SELECT nfl.game_id, nfl.season, nfl.season_type, nfl.week,
               nfl.week_label, nfl.scheduled_start_time, game.home_team_id,
               game.away_team_id, nfl.status, nfl.home_score, nfl.away_score,
               nfl.overtime, nfl.neutral_site
        FROM nfl_games nfl
        JOIN games game ON game.game_id = nfl.game_id
        WHERE nfl.season = %s
          AND nfl.season >= 2026
          AND nfl.status = 'unplayed'
          AND nfl.scheduled_start_time >= %s
          AND nfl.scheduled_start_time < %s
        ORDER BY nfl.scheduled_start_time, nfl.game_id;
        """,
        (season, slate_start_time, slate_end_time),
    )
    return tuple(_game_from_row(row) for row in cursor.fetchall())


def database_clock(cursor: Any) -> datetime:
    cursor.execute("SELECT clock_timestamp();")
    return cursor.fetchone()[0]


def list_nfl_team_abbreviations(
    cursor: Any, *, team_ids: tuple[int, ...],
) -> tuple[tuple[int, str], ...]:
    if not team_ids:
        return ()
    cursor.execute(
        """
        SELECT team_id, current_abbreviation
        FROM nfl_team_profiles
        WHERE team_id = ANY(%s)
        ORDER BY team_id;
        """,
        (list(team_ids),),
    )
    return tuple(cursor.fetchall())


def create_nfl_prediction_run(
    cursor: Any,
    *,
    run_key: UUID,
    request_sha256: str,
    run_type: NFLMoneylinePredictionRunType,
    evaluation_protocol_version: str,
    routing_contract_version: str,
    season: int,
    target_date: date,
    slate_start_time: datetime,
    slate_end_time: datetime,
    slate_fingerprint: str,
    early_artifact: Any,
    mature_artifact: Any,
    target_count: int,
) -> NFLMoneylinePredictionRun | None:
    cursor.execute(
        """
        INSERT INTO nfl_moneyline_prediction_runs (
            run_key, request_sha256, run_type, evaluation_protocol_version,
            routing_contract_version, season, target_date, slate_start_time,
            slate_end_time, slate_fingerprint,
            early_model_specification_version,
            early_feature_schema_version, early_specification_fingerprint,
            early_model_fingerprint, mature_model_specification_version,
            mature_feature_schema_version, mature_specification_fingerprint,
            mature_model_fingerprint, target_count
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (run_key) DO NOTHING
        RETURNING nfl_moneyline_prediction_run_id, run_key, request_sha256,
                  run_type, evaluation_protocol_version,
                  routing_contract_version, season, target_date,
                  slate_start_time, slate_end_time, slate_fingerprint,
                  early_model_specification_version,
                  early_feature_schema_version,
                  early_specification_fingerprint, early_model_fingerprint,
                  mature_model_specification_version,
                  mature_feature_schema_version,
                  mature_specification_fingerprint, mature_model_fingerprint,
                  target_count, prediction_count, status, source_data_as_of,
                  source_snapshot_sha256, prediction_set_sha256,
                  failure_message;
        """,
        (
            run_key, request_sha256, run_type.value,
            evaluation_protocol_version, routing_contract_version, season,
            target_date, slate_start_time, slate_end_time, slate_fingerprint,
            early_artifact.specification_version,
            early_artifact.feature_schema_version,
            early_artifact.specification_fingerprint,
            early_artifact.model_fingerprint,
            mature_artifact.specification_version,
            mature_artifact.feature_schema_version,
            mature_artifact.specification_fingerprint,
            mature_artifact.model_fingerprint,
            target_count,
        ),
    )
    row = cursor.fetchone()
    return None if row is None else _run_from_row(row)


def load_nfl_prediction_run_by_key(
    cursor: Any, *, run_key: UUID,
) -> NFLMoneylinePredictionRun | None:
    cursor.execute(
        _RUN_SELECT + " WHERE run_key = %s;",
        (run_key,),
    )
    row = cursor.fetchone()
    return None if row is None else _run_from_row(row)


def lock_nfl_prediction_run(
    cursor: Any, *, prediction_run_id: int,
) -> NFLMoneylinePredictionRun:
    cursor.execute(
        _RUN_SELECT
        + " WHERE nfl_moneyline_prediction_run_id = %s FOR UPDATE;",
        (prediction_run_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise LookupError("NFL Moneyline prediction run no longer exists")
    return _run_from_row(row)


def count_nfl_predictions_for_run(
    cursor: Any, *, prediction_run_id: int,
) -> int:
    cursor.execute(
        "SELECT COUNT(*) FROM nfl_moneyline_game_predictions "
        "WHERE nfl_moneyline_prediction_run_id = %s;",
        (prediction_run_id,),
    )
    return cursor.fetchone()[0]


def list_existing_official_nfl_game_ids(
    cursor: Any,
    *,
    evaluation_protocol_version: str,
    game_ids: tuple[int, ...],
) -> tuple[int, ...]:
    if not game_ids:
        return ()
    cursor.execute(
        """
        SELECT game_id
        FROM nfl_moneyline_game_predictions
        WHERE run_type = 'official'
          AND evaluation_protocol_version = %s
          AND game_id = ANY(%s)
        ORDER BY game_id;
        """,
        (evaluation_protocol_version, list(game_ids)),
    )
    return tuple(row[0] for row in cursor.fetchall())


def insert_nfl_game_prediction(
    cursor: Any,
    *,
    prediction_run_id: int,
    run_type: NFLMoneylinePredictionRunType,
    evaluation_protocol_version: str,
    inference: Any,
    neutral_site: bool,
    source_data_as_of: datetime,
    feature_payload: dict[str, Any],
    source_trace_payload: dict[str, Any],
    source_trace_sha256: str,
    model_home_win_probability: Decimal,
    frozen_route_home_baseline_probability: Decimal,
    classification_threshold: Decimal,
    predicted_side: NFLPredictedSide,
) -> tuple[int, datetime]:
    cursor.execute(
        """
        INSERT INTO nfl_moneyline_game_predictions (
            nfl_moneyline_prediction_run_id, run_type,
            evaluation_protocol_version, game_id, season, target_kickoff,
            home_team_id, away_team_id, neutral_site, feature_cutoff,
            source_data_as_of, home_current_prior_games,
            away_current_prior_games, selected_route,
            routing_contract_version, selected_model_specification_version,
            feature_schema_version, specification_fingerprint,
            model_fingerprint, feature_payload, feature_vector_sha256,
            source_trace_payload, source_trace_sha256, latest_source_kickoff,
            model_home_win_probability,
            frozen_route_home_baseline_probability,
            classification_threshold, predicted_side
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING nfl_moneyline_game_prediction_id, prediction_created_at;
        """,
        (
            prediction_run_id, run_type.value, evaluation_protocol_version,
            inference.game_id, inference.season, inference.target_kickoff,
            inference.home_team_id, inference.away_team_id, neutral_site,
            inference.feature_cutoff, source_data_as_of,
            inference.home_current_prior_games,
            inference.away_current_prior_games,
            inference.selected_route.value,
            inference.routing_contract_version,
            inference.model_specification_version,
            inference.feature_schema_version,
            inference.specification_fingerprint,
            inference.model_fingerprint, Json(feature_payload),
            inference.feature_vector_fingerprint, Json(source_trace_payload),
            source_trace_sha256, inference.latest_source_kickoff,
            model_home_win_probability,
            frozen_route_home_baseline_probability,
            classification_threshold, predicted_side.value,
        ),
    )
    return cursor.fetchone()


def complete_nfl_prediction_run(
    cursor: Any,
    *,
    prediction_run_id: int,
    source_data_as_of: datetime,
    source_snapshot_sha256: str,
    prediction_set_sha256: str,
    prediction_count: int,
) -> NFLMoneylinePredictionRun:
    cursor.execute(
        """
        UPDATE nfl_moneyline_prediction_runs
        SET source_data_as_of = %s,
            source_snapshot_sha256 = %s,
            prediction_set_sha256 = %s,
            prediction_count = %s,
            status = 'completed',
            completed_at = clock_timestamp()
        WHERE nfl_moneyline_prediction_run_id = %s AND status = 'running'
        RETURNING nfl_moneyline_prediction_run_id, run_key, request_sha256,
                  run_type, evaluation_protocol_version,
                  routing_contract_version, season, target_date,
                  slate_start_time, slate_end_time, slate_fingerprint,
                  early_model_specification_version,
                  early_feature_schema_version,
                  early_specification_fingerprint, early_model_fingerprint,
                  mature_model_specification_version,
                  mature_feature_schema_version,
                  mature_specification_fingerprint, mature_model_fingerprint,
                  target_count, prediction_count, status, source_data_as_of,
                  source_snapshot_sha256, prediction_set_sha256,
                  failure_message;
        """,
        (
            source_data_as_of, source_snapshot_sha256,
            prediction_set_sha256, prediction_count, prediction_run_id,
        ),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("NFL Moneyline run was not running at completion")
    return _run_from_row(row)


def fail_nfl_prediction_run(
    cursor: Any, *, prediction_run_id: int, failure_message: str,
) -> NFLMoneylinePredictionRun | None:
    cursor.execute(
        """
        UPDATE nfl_moneyline_prediction_runs
        SET status = 'failed', failed_at = clock_timestamp(),
            failure_message = %s, prediction_count = 0
        WHERE nfl_moneyline_prediction_run_id = %s AND status = 'running'
        RETURNING nfl_moneyline_prediction_run_id, run_key, request_sha256,
                  run_type, evaluation_protocol_version,
                  routing_contract_version, season, target_date,
                  slate_start_time, slate_end_time, slate_fingerprint,
                  early_model_specification_version,
                  early_feature_schema_version,
                  early_specification_fingerprint, early_model_fingerprint,
                  mature_model_specification_version,
                  mature_feature_schema_version,
                  mature_specification_fingerprint, mature_model_fingerprint,
                  target_count, prediction_count, status, source_data_as_of,
                  source_snapshot_sha256, prediction_set_sha256,
                  failure_message;
        """,
        (failure_message[:4000], prediction_run_id),
    )
    row = cursor.fetchone()
    return None if row is None else _run_from_row(row)


_RUN_SELECT = """
SELECT nfl_moneyline_prediction_run_id, run_key, request_sha256, run_type,
       evaluation_protocol_version, routing_contract_version, season,
       target_date, slate_start_time, slate_end_time, slate_fingerprint,
       early_model_specification_version, early_feature_schema_version,
       early_specification_fingerprint, early_model_fingerprint,
       mature_model_specification_version, mature_feature_schema_version,
       mature_specification_fingerprint, mature_model_fingerprint,
       target_count, prediction_count, status, source_data_as_of,
       source_snapshot_sha256, prediction_set_sha256, failure_message
FROM nfl_moneyline_prediction_runs
"""


def _run_from_row(row: tuple[Any, ...]) -> NFLMoneylinePredictionRun:
    return NFLMoneylinePredictionRun(
        prediction_run_id=row[0],
        run_key=row[1],
        request_sha256=row[2],
        run_type=NFLMoneylinePredictionRunType(row[3]),
        evaluation_protocol_version=row[4],
        routing_contract_version=row[5],
        season=row[6],
        target_date=row[7],
        slate_start_time=row[8],
        slate_end_time=row[9],
        slate_fingerprint=row[10],
        early_model_specification_version=row[11],
        early_feature_schema_version=row[12],
        early_specification_fingerprint=row[13],
        early_model_fingerprint=row[14],
        mature_model_specification_version=row[15],
        mature_feature_schema_version=row[16],
        mature_specification_fingerprint=row[17],
        mature_model_fingerprint=row[18],
        target_count=row[19],
        prediction_count=row[20],
        status=NFLMoneylinePredictionRunStatus(row[21]),
        source_data_as_of=row[22],
        source_snapshot_sha256=row[23],
        prediction_set_sha256=row[24],
        failure_message=row[25],
    )


def _game_from_row(row: tuple[Any, ...]) -> NflGame:
    return NflGame(
        game_id=row[0], season=row[1], season_type=NflSeasonType(row[2]),
        week=row[3], week_label=row[4], scheduled_start_time=row[5],
        home_team_id=row[6], away_team_id=row[7],
        status=NflGameStatus(row[8]), home_score=row[9], away_score=row[10],
        overtime=row[11], neutral_site=row[12],
    )
