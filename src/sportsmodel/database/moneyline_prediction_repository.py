from datetime import date, datetime
import re
from typing import Any

from sportsmodel.models.moneyline_prediction import (
    MoneylineGamePrediction,
)


SHA256_PATTERN = re.compile(
    r"^[0-9a-f]{64}$"
)


def create_moneyline_prediction_run(
    connection: Any,
    *,
    target_date: date,
    model_version: str,
    feature_schema_version: str,
    model_artifact_sha256: str,
    model_training_cutoff: datetime | None,
) -> int:
    """
    Create and commit a running Moneyline prediction audit record.

    The initial record is committed separately so a later prediction
    failure remains visible.
    """

    if not model_version.strip():
        raise ValueError(
            "Model version cannot be empty."
        )

    if not feature_schema_version.strip():
        raise ValueError(
            "Feature schema version cannot be empty."
        )

    if not SHA256_PATTERN.fullmatch(
        model_artifact_sha256
    ):
        raise ValueError(
            "Model artifact hash must be a lowercase SHA-256 value."
        )

    if (
        model_training_cutoff is not None
        and (
            model_training_cutoff.tzinfo is None
            or model_training_cutoff.utcoffset() is None
        )
    ):
        raise ValueError(
            "Model training cutoff must be timezone-aware."
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO moneyline_prediction_runs (
                target_date,
                model_version,
                feature_schema_version,
                model_artifact_sha256,
                model_training_cutoff,
                status
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                'running'
            )
            RETURNING moneyline_prediction_run_id;
            """,
            (
                target_date,
                model_version.strip(),
                feature_schema_version.strip(),
                model_artifact_sha256,
                model_training_cutoff,
            ),
        )

        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Prediction run insert returned no row."
        )

    connection.commit()

    return row[0]


def insert_moneyline_game_prediction(
    cursor: Any,
    prediction: MoneylineGamePrediction,
) -> int:
    """
    Insert and return one immutable Moneyline prediction snapshot.
    """

    cursor.execute(
        """
        INSERT INTO moneyline_game_predictions (
            moneyline_prediction_run_id,
            game_id,
            mlb_game_id,
            game_start_time,
            prediction_time,
            home_team_id,
            away_team_id,
            home_starting_pitcher_id,
            away_starting_pitcher_id,
            home_starting_pitcher_mlb_id,
            away_starting_pitcher_mlb_id,
            home_starter_features_available,
            away_starter_features_available,
            starter_coverage,
            missing_raw_value_count,
            home_win_probability,
            away_win_probability,
            predicted_team_id,
            predicted_probability
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        RETURNING moneyline_game_prediction_id;
        """,
        (
            prediction.moneyline_prediction_run_id,
            prediction.game_id,
            prediction.mlb_game_id,
            prediction.game_start_time,
            prediction.prediction_time,
            prediction.home_team_id,
            prediction.away_team_id,
            prediction.home_starting_pitcher_id,
            prediction.away_starting_pitcher_id,
            prediction.home_starting_pitcher_mlb_id,
            prediction.away_starting_pitcher_mlb_id,
            prediction.home_starter_features_available,
            prediction.away_starter_features_available,
            prediction.starter_coverage,
            prediction.missing_raw_value_count,
            prediction.home_win_probability,
            prediction.away_win_probability,
            prediction.predicted_team_id,
            prediction.predicted_probability,
        ),
    )

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Moneyline prediction insert returned no row."
        )

    return row[0]


def mark_moneyline_prediction_run_completed(
    cursor: Any,
    *,
    moneyline_prediction_run_id: int,
    games_received: int,
    predictions_created: int,
    games_skipped: int,
) -> None:
    """
    Mark a Moneyline prediction run as completed.
    """

    _validate_run_counts(
        games_received=games_received,
        predictions_created=predictions_created,
        games_skipped=games_skipped,
    )

    cursor.execute(
        """
        UPDATE moneyline_prediction_runs
        SET
            completed_at = CURRENT_TIMESTAMP,
            status = 'completed',
            games_received = %s,
            predictions_created = %s,
            games_skipped = %s,
            error_message = NULL
        WHERE moneyline_prediction_run_id = %s;
        """,
        (
            games_received,
            predictions_created,
            games_skipped,
            moneyline_prediction_run_id,
        ),
    )


def mark_moneyline_prediction_run_failed(
    connection: Any,
    *,
    moneyline_prediction_run_id: int,
    games_received: int,
    predictions_created: int,
    games_skipped: int,
    error_message: str,
) -> None:
    """
    Record a failed prediction run after prediction writes roll back.
    """

    _validate_run_counts(
        games_received=games_received,
        predictions_created=predictions_created,
        games_skipped=games_skipped,
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE moneyline_prediction_runs
            SET
                completed_at = CURRENT_TIMESTAMP,
                status = 'failed',
                games_received = %s,
                predictions_created = %s,
                games_skipped = %s,
                error_message = %s
            WHERE moneyline_prediction_run_id = %s;
            """,
            (
                games_received,
                predictions_created,
                games_skipped,
                error_message,
                moneyline_prediction_run_id,
            ),
        )

    connection.commit()


def _validate_run_counts(
    *,
    games_received: int,
    predictions_created: int,
    games_skipped: int,
) -> None:
    if any(
        count < 0
        for count in (
            games_received,
            predictions_created,
            games_skipped,
        )
    ):
        raise ValueError(
            "Prediction run counts cannot be negative."
        )

    if (
        predictions_created
        + games_skipped
        > games_received
    ):
        raise ValueError(
            "Created and skipped counts cannot exceed games received."
        )
