import os
from datetime import datetime, timezone
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
import pytest


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_nfl_forward_prediction_constraints_and_append_only_evidence(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        game_id, home_id, away_id = _create_game(connection)
        official_run = _create_run(connection, "official")
        prediction_id = _insert_prediction(
            connection, official_run, game_id, home_id, away_id, "official"
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE nfl_moneyline_prediction_runs
                SET prediction_count = 1, source_data_as_of = clock_timestamp(),
                    source_snapshot_sha256 = %s, prediction_set_sha256 = %s,
                    status = 'completed', completed_at = clock_timestamp()
                WHERE nfl_moneyline_prediction_run_id = %s;
                """,
                ("6" * 64, "7" * 64, official_run),
            )
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT feature_payload, source_trace_payload,
                       feature_vector_sha256, prediction_created_at < target_kickoff
                FROM nfl_moneyline_game_predictions
                WHERE nfl_moneyline_game_prediction_id = %s;
                """,
                (prediction_id,),
            )
            feature, trace, vector_sha, pregame = cursor.fetchone()
        assert feature == {
            "feature_schema_version": "early-schema",
            "ordered_feature_names": ["x"],
            "ordered_feature_values": [1.0],
        }
        assert trace == {"channels": []}
        assert vector_sha == "3" * 64
        assert pregame is True

        second_official_run = _create_run(connection, "official")
        with pytest.raises(psycopg2.errors.UniqueViolation):
            _insert_prediction(
                connection, second_official_run, game_id,
                home_id, away_id, "official",
            )
        connection.rollback()

        preview_one = _create_run(connection, "preview")
        _insert_prediction(
            connection, preview_one, game_id, home_id, away_id, "preview"
        )
        connection.commit()
        preview_two = _create_run(connection, "preview")
        _insert_prediction(
            connection, preview_two, game_id, home_id, away_id, "preview"
        )
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM nfl_moneyline_game_predictions "
                "WHERE game_id = %s AND run_type = 'preview';",
                (game_id,),
            )
            assert cursor.fetchone()[0] == 2

        with pytest.raises(psycopg2.errors.RaiseException):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE nfl_moneyline_game_predictions SET neutral_site = TRUE "
                    "WHERE nfl_moneyline_game_prediction_id = %s;",
                    (prediction_id,),
                )
        connection.rollback()
        with pytest.raises(psycopg2.errors.RaiseException):
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM nfl_moneyline_game_predictions "
                    "WHERE nfl_moneyline_game_prediction_id = %s;",
                    (prediction_id,),
                )
        connection.rollback()
        with pytest.raises(psycopg2.errors.RaiseException):
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM nfl_moneyline_prediction_runs "
                    "WHERE nfl_moneyline_prediction_run_id = %s;",
                    (official_run,),
                )
        connection.rollback()
    finally:
        connection.close()


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_nfl_forward_prediction_rejects_time_route_identity_and_run_drift(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        game_id, home_id, away_id = _create_game(connection)

        for route, home_count, away_count in (
            ("mature", 2, 3),
            ("early", 3, 3),
        ):
            run_id = _create_run(connection, "preview")
            with pytest.raises(psycopg2.errors.CheckViolation):
                _insert_prediction(
                    connection, run_id, game_id, home_id, away_id, "preview",
                    route=route, home_count=home_count, away_count=away_count,
                )
            connection.rollback()

        run_id = _create_run(connection, "preview")
        with pytest.raises(psycopg2.errors.RaiseException, match="identity mismatch"):
            _insert_prediction(
                connection, run_id, game_id, home_id, away_id, "preview",
                model_fingerprint="9" * 64,
            )
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE nfl_games SET scheduled_start_time = clock_timestamp() "
                "WHERE game_id = %s RETURNING scheduled_start_time;",
                (game_id,),
            )
            kickoff = cursor.fetchone()[0]
            cursor.execute(
                "UPDATE games SET game_date = %s WHERE game_id = %s;",
                (kickoff, game_id),
            )
        connection.commit()
        run_id = _create_run(connection, "preview")
        with pytest.raises(psycopg2.errors.RaiseException, match="strictly before"):
            _insert_prediction(
                connection, run_id, game_id, home_id, away_id, "preview",
                kickoff=kickoff,
            )
        connection.rollback()

        run_id = _create_run(connection, "preview", target_count=1)
        with pytest.raises(psycopg2.errors.RaiseException, match="count"):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE nfl_moneyline_prediction_runs
                    SET prediction_count = 1,
                        source_data_as_of = clock_timestamp(),
                        source_snapshot_sha256 = %s,
                        prediction_set_sha256 = %s,
                        status = 'completed', completed_at = clock_timestamp()
                    WHERE nfl_moneyline_prediction_run_id = %s;
                    """,
                    ("6" * 64, "7" * 64, run_id),
                )
        connection.rollback()

        with pytest.raises(psycopg2.errors.CheckViolation):
            _create_run(connection, "preview", season=2025)
        connection.rollback()
    finally:
        connection.close()


def _create_game(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO teams (team_name) VALUES (%s) RETURNING team_id;",
            (f"Home {uuid4()}",),
        )
        home_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO teams (team_name) VALUES (%s) RETURNING team_id;",
            (f"Away {uuid4()}",),
        )
        away_id = cursor.fetchone()[0]
        kickoff = datetime(2099, 9, 10, 20, tzinfo=timezone.utc)
        cursor.execute(
            """
            INSERT INTO games (game_date, home_team_id, away_team_id)
            VALUES (%s, %s, %s) RETURNING game_id;
            """,
            (kickoff, home_id, away_id),
        )
        game_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO nfl_games (
                game_id, season, season_type, week, week_label,
                scheduled_start_time, neutral_site, status,
                home_score, away_score, overtime
            ) VALUES (%s, 2026, 'regular', 1, 'Week 1', %s, FALSE,
                      'unplayed', NULL, NULL, NULL);
            """,
            (game_id, kickoff),
        )
    connection.commit()
    return game_id, home_id, away_id


def _create_run(connection, run_type, *, season=2026, target_count=1):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO nfl_moneyline_prediction_runs (
                run_key, request_sha256, run_type,
                evaluation_protocol_version, routing_contract_version,
                season, target_date, slate_start_time, slate_end_time,
                slate_fingerprint, early_model_specification_version,
                early_feature_schema_version, early_specification_fingerprint,
                early_model_fingerprint, mature_model_specification_version,
                mature_feature_schema_version, mature_specification_fingerprint,
                mature_model_fingerprint, target_count
            ) VALUES (
                %s, %s, %s, 'test-protocol', 'test-routing', %s,
                '2026-09-10', '2099-09-10T00:00:00Z',
                '2099-09-11T00:00:00Z', %s,
                'early-model', 'early-schema', %s, %s,
                'mature-model', 'mature-schema', %s, %s, %s
            ) RETURNING nfl_moneyline_prediction_run_id;
            """,
            (
                uuid4(), "0" * 64, run_type, season, "1" * 64,
                "2" * 64, "4" * 64, "8" * 64, "a" * 64, target_count,
            ),
        )
        run_id = cursor.fetchone()[0]
    connection.commit()
    return run_id


def _insert_prediction(
    connection, run_id, game_id, home_id, away_id, run_type,
    *, route="early", home_count=0, away_count=0,
    model_fingerprint="4" * 64, kickoff=None,
):
    kickoff = kickoff or datetime(2099, 9, 10, 20, tzinfo=timezone.utc)
    if route == "early":
        model, schema, specification = "early-model", "early-schema", "2" * 64
    else:
        model, schema, specification = "mature-model", "mature-schema", "8" * 64
        if model_fingerprint == "4" * 64:
            model_fingerprint = "a" * 64
    with connection.cursor() as cursor:
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
                source_trace_payload, source_trace_sha256,
                latest_source_kickoff, model_home_win_probability,
                frozen_route_home_baseline_probability,
                classification_threshold, predicted_side
            ) VALUES (
                %s, %s, 'test-protocol', %s, 2026, %s, %s, %s, FALSE,
                %s, clock_timestamp(), %s, %s, %s, 'test-routing',
                %s, %s, %s, %s, %s, %s, %s, %s, NULL, 0.6, 0.55, 0.5,
                'home'
            ) RETURNING nfl_moneyline_game_prediction_id;
            """,
            (
                run_id, run_type, game_id, kickoff, home_id, away_id, kickoff,
                home_count, away_count, route, model, schema, specification,
                model_fingerprint,
                Json({
                    "feature_schema_version": "early-schema",
                    "ordered_feature_names": ["x"],
                    "ordered_feature_values": [1.0],
                }),
                "3" * 64, Json({"channels": []}), "5" * 64,
            ),
        )
        return cursor.fetchone()[0]
