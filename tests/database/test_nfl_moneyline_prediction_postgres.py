import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
import pytest

import sportsmodel.nfl.moneyline_prediction_service as prediction_service
from sportsmodel.nfl.moneyline_prediction import (
    NFLMoneylinePredictionRunType,
    canonical_nfl_moneyline_probability_text,
)
from sportsmodel.nfl.moneyline_prediction_service import (
    _execute_nfl_moneyline_prediction_run,
    _prediction_set_fingerprint_from_records,
)


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
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT (SELECT COUNT(*) FROM nfl_moneyline_prediction_runs), "
                "(SELECT COUNT(*) FROM nfl_moneyline_game_predictions);"
            )
            before_dry_run = cursor.fetchone()
        dry_run = _execute_nfl_moneyline_prediction_run(
            season=2026,
            target_date=date(2099, 9, 10),
            slate_start_time=datetime(2099, 9, 10, tzinfo=timezone.utc),
            slate_end_time=datetime(2099, 9, 11, tzinfo=timezone.utc),
            run_type=NFLMoneylinePredictionRunType.OFFICIAL,
            run_key=None,
            dry_run=True,
            connection_factory=lambda: psycopg2.connect(
                initialized_nfl_test_database
            ),
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT (SELECT COUNT(*) FROM nfl_moneyline_prediction_runs), "
                "(SELECT COUNT(*) FROM nfl_moneyline_game_predictions);"
            )
            after_dry_run = cursor.fetchone()
        assert dry_run.dry_run
        assert len(dry_run.inference_results) == 1
        assert before_dry_run == after_dry_run == (0, 0)

        official_run = _create_run(connection, "official")
        prediction_id = _insert_prediction(
            connection, official_run, game_id, home_id, away_id, "official"
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE nfl_moneyline_prediction_runs
                SET prediction_count = 1,
                    source_data_as_of = (
                        SELECT MIN(source_data_as_of)
                        FROM nfl_moneyline_game_predictions
                        WHERE nfl_moneyline_prediction_run_id = %s
                    ),
                    source_snapshot_sha256 = %s, prediction_set_sha256 = %s,
                    status = 'completed', completed_at = clock_timestamp()
                WHERE nfl_moneyline_prediction_run_id = %s;
                """,
                (official_run, "6" * 64, "7" * 64, official_run),
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

        threshold_run = _create_run(connection, "preview")
        threshold_prediction = _insert_prediction(
            connection,
            threshold_run,
            game_id,
            home_id,
            away_id,
            "preview",
            probability=Decimal("0.4999999999999999"),
        )
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT model_home_win_probability, predicted_side "
                "FROM nfl_moneyline_game_predictions WHERE "
                "nfl_moneyline_game_prediction_id = %s;",
                (threshold_prediction,),
            )
            assert cursor.fetchone() == (
                Decimal("0.4999999999999999"),
                "away",
            )

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
        run_id = _create_run(
            connection,
            "preview",
            slate_start=kickoff - timedelta(days=1),
            slate_end=kickoff + timedelta(days=1),
        )
        with pytest.raises(psycopg2.errors.RaiseException, match="strictly before"):
            _insert_prediction(
                connection, run_id, game_id, home_id, away_id, "preview",
                kickoff=kickoff,
            )
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE nfl_games SET scheduled_start_time = "
                "clock_timestamp() - INTERVAL '1 second' "
                "WHERE game_id = %s RETURNING scheduled_start_time;",
                (game_id,),
            )
            post_kickoff = cursor.fetchone()[0]
            cursor.execute(
                "UPDATE games SET game_date = %s WHERE game_id = %s;",
                (post_kickoff, game_id),
            )
        connection.commit()
        run_id = _create_run(
            connection,
            "preview",
            slate_start=post_kickoff - timedelta(days=1),
            slate_end=post_kickoff + timedelta(days=1),
        )
        with pytest.raises(psycopg2.errors.RaiseException, match="strictly before"):
            _insert_prediction(
                connection, run_id, game_id, home_id, away_id, "preview",
                kickoff=post_kickoff,
            )
        connection.rollback()

        canonical_kickoff = datetime(
            2099, 9, 10, 20, tzinfo=timezone.utc
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE nfl_games SET scheduled_start_time = %s "
                "WHERE game_id = %s;",
                (canonical_kickoff, game_id),
            )
            cursor.execute(
                "UPDATE games SET game_date = %s WHERE game_id = %s;",
                (canonical_kickoff, game_id),
            )
        connection.commit()

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

        _assert_run_lifecycle_and_parent_coherence(
            connection, game_id, home_id, away_id
        )
    finally:
        connection.close()


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_nfl_prediction_locks_canonical_target_against_concurrent_mutation(
    initialized_nfl_test_database,
) -> None:
    first = psycopg2.connect(initialized_nfl_test_database)
    second = psycopg2.connect(initialized_nfl_test_database)
    try:
        game_id, home_id, away_id = _create_game(first)
        run_id = _create_run(first, "preview")
        _insert_prediction(first, run_id, game_id, home_id, away_id, "preview")

        with second.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '250ms';")
            with pytest.raises(psycopg2.errors.LockNotAvailable):
                cursor.execute(
                    "UPDATE nfl_games SET status = 'final', home_score = 1, "
                    "away_score = 0, overtime = FALSE WHERE game_id = %s;",
                    (game_id,),
                )
        second.rollback()
        first.commit()

        with second.cursor() as cursor:
            cursor.execute(
                "SELECT prediction.target_kickoff = nfl.scheduled_start_time, "
                "prediction.home_team_id = game.home_team_id, "
                "prediction.away_team_id = game.away_team_id, nfl.status "
                "FROM nfl_moneyline_game_predictions AS prediction "
                "JOIN nfl_games AS nfl ON nfl.game_id = prediction.game_id "
                "JOIN games AS game ON game.game_id = prediction.game_id "
                "WHERE prediction.nfl_moneyline_prediction_run_id = %s;",
                (run_id,),
            )
            assert cursor.fetchone() == (True, True, True, "unplayed")
        second.rollback()
    finally:
        first.close()
        second.close()


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_concurrent_identical_run_key_returns_one_completed_evidence_set(
    initialized_nfl_test_database,
) -> None:
    setup = psycopg2.connect(initialized_nfl_test_database)
    try:
        game_id, _, _ = _create_game(setup)
    finally:
        setup.close()
    run_key = uuid4()
    barrier = Barrier(2)

    def execute():
        barrier.wait()
        return _execute_nfl_moneyline_prediction_run(
            season=2026,
            target_date=date(2099, 9, 10),
            slate_start_time=datetime(2099, 9, 10, tzinfo=timezone.utc),
            slate_end_time=datetime(2099, 9, 11, tzinfo=timezone.utc),
            run_type=NFLMoneylinePredictionRunType.OFFICIAL,
            run_key=run_key,
            dry_run=False,
            connection_factory=lambda: psycopg2.connect(
                initialized_nfl_test_database
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: execute(), range(2)))

    assert results[0].run is not None
    assert results[1].run is not None
    assert results[0].run.prediction_run_id == results[1].run.prediction_run_id
    verification = psycopg2.connect(initialized_nfl_test_database)
    try:
        with verification.cursor() as cursor:
            cursor.execute(
                "SELECT run.status, run.target_count, run.prediction_count, "
                "run.prediction_set_sha256, prediction.game_id, "
                "prediction.selected_route, "
                "prediction.selected_model_specification_version, "
                "prediction.feature_vector_sha256, "
                "prediction.source_trace_sha256, "
                "prediction.model_home_win_probability, "
                "prediction.classification_threshold, "
                "prediction.predicted_side FROM "
                "nfl_moneyline_prediction_runs AS run JOIN "
                "nfl_moneyline_game_predictions AS prediction ON "
                "prediction.nfl_moneyline_prediction_run_id = "
                "run.nfl_moneyline_prediction_run_id WHERE run.run_key = %s;",
                (run_key,),
            )
            persisted = cursor.fetchone()
            assert persisted[:3] == ("completed", 1, 1)
            probability = persisted[9]
            threshold = persisted[10]
            assert persisted[11] == (
                "home" if probability >= threshold else "away"
            )
            reconstructed_hash = _prediction_set_fingerprint_from_records(({
                "game_id": persisted[4],
                "selected_route": persisted[5],
                "model_specification_version": persisted[6],
                "feature_vector_sha256": persisted[7],
                "source_trace_sha256": persisted[8],
                "model_home_win_probability": (
                    canonical_nfl_moneyline_probability_text(probability)
                ),
                "classification_threshold": (
                    canonical_nfl_moneyline_probability_text(threshold)
                ),
                "predicted_side": persisted[11],
            },))
            assert reconstructed_hash == persisted[3]
            cursor.execute(
                "SELECT COUNT(*) FROM nfl_moneyline_game_predictions "
                "WHERE game_id = %s;",
                (game_id,),
            )
            assert cursor.fetchone()[0] == 1
    finally:
        verification.close()


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_partial_official_transaction_rolls_back_all_children(
    initialized_nfl_test_database,
    monkeypatch,
) -> None:
    setup = psycopg2.connect(initialized_nfl_test_database)
    try:
        _create_game(setup)
        _create_game(setup)
    finally:
        setup.close()

    original_insert = prediction_service.insert_nfl_game_prediction
    insert_calls = 0

    def fail_second_insert(*args, **kwargs):
        nonlocal insert_calls
        insert_calls += 1
        if insert_calls == 2:
            raise RuntimeError("forced second prediction failure")
        return original_insert(*args, **kwargs)

    monkeypatch.setattr(
        prediction_service,
        "insert_nfl_game_prediction",
        fail_second_insert,
    )
    run_key = uuid4()

    with pytest.raises(RuntimeError, match="forced second prediction failure"):
        _execute_nfl_moneyline_prediction_run(
            season=2026,
            target_date=date(2099, 9, 10),
            slate_start_time=datetime(2099, 9, 10, tzinfo=timezone.utc),
            slate_end_time=datetime(2099, 9, 11, tzinfo=timezone.utc),
            run_type=NFLMoneylinePredictionRunType.OFFICIAL,
            run_key=run_key,
            dry_run=False,
            connection_factory=lambda: psycopg2.connect(
                initialized_nfl_test_database
            ),
        )

    assert insert_calls == 2
    verification = psycopg2.connect(initialized_nfl_test_database)
    try:
        with verification.cursor() as cursor:
            cursor.execute(
                "SELECT nfl_moneyline_prediction_run_id, status, "
                "target_count, prediction_count FROM "
                "nfl_moneyline_prediction_runs WHERE run_key = %s;",
                (run_key,),
            )
            run_id, status, target_count, prediction_count = cursor.fetchone()
            assert (status, target_count, prediction_count) == (
                "failed",
                2,
                0,
            )
            cursor.execute(
                "SELECT COUNT(*) FROM nfl_moneyline_game_predictions "
                "WHERE nfl_moneyline_prediction_run_id = %s;",
                (run_id,),
            )
            assert cursor.fetchone()[0] == 0
    finally:
        verification.close()


def _assert_run_lifecycle_and_parent_coherence(
    connection, game_id, home_id, away_id,
) -> None:
    with pytest.raises(psycopg2.errors.RaiseException, match="begin running"):
        with connection.cursor() as cursor:
            _insert_direct_terminal_run(cursor, "completed")
    connection.rollback()
    with pytest.raises(psycopg2.errors.RaiseException, match="begin running"):
        with connection.cursor() as cursor:
            _insert_direct_terminal_run(cursor, "failed")
    connection.rollback()

    run_id = _create_run(connection, "preview")
    with pytest.raises(psycopg2.errors.RaiseException, match="identity is immutable"):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE nfl_moneyline_prediction_runs SET target_count = 2 "
                "WHERE nfl_moneyline_prediction_run_id = %s;",
                (run_id,),
            )
    connection.rollback()

    wrong_season_run = _create_run(connection, "preview", season=2027)
    with pytest.raises(psycopg2.errors.RaiseException, match="season"):
        _insert_prediction(
            connection, wrong_season_run, game_id, home_id, away_id, "preview"
        )
    connection.rollback()

    outside_run = _create_run(
        connection,
        "preview",
        slate_start=datetime(2099, 9, 9, tzinfo=timezone.utc),
        slate_end=datetime(2099, 9, 10, tzinfo=timezone.utc),
    )
    with pytest.raises(psycopg2.errors.RaiseException, match="outside parent"):
        _insert_prediction(
            connection, outside_run, game_id, home_id, away_id, "preview"
        )
    connection.rollback()

    snapshot_run = _create_run(connection, "preview")
    with pytest.raises(psycopg2.errors.RaiseException, match="transaction snapshot"):
        _insert_prediction(
            connection, snapshot_run, game_id, home_id, away_id, "preview",
            source_data_as_of=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
    connection.rollback()

    source_run = _create_run(connection, "preview")
    prediction_id = _insert_prediction(
        connection, source_run, game_id, home_id, away_id, "preview",
        probability=Decimal("0.0523316383502806"),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT source_data_as_of, model_home_win_probability FROM "
            "nfl_moneyline_game_predictions WHERE "
            "nfl_moneyline_game_prediction_id = %s;",
            (prediction_id,),
        )
        child_source, stored_probability = cursor.fetchone()
    assert stored_probability == Decimal("0.0523316383502806")
    with pytest.raises(psycopg2.errors.RaiseException, match="source timestamp"):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE nfl_moneyline_prediction_runs
                SET prediction_count = 1, source_data_as_of = %s,
                    source_snapshot_sha256 = %s, prediction_set_sha256 = %s,
                    status = 'completed', completed_at = clock_timestamp()
                WHERE nfl_moneyline_prediction_run_id = %s;
                """,
                (
                    child_source + timedelta(seconds=1),
                    "6" * 64,
                    "7" * 64,
                    source_run,
                ),
            )
    connection.rollback()

    with pytest.raises(psycopg2.errors.CheckViolation):
        _create_run(connection, "official", target_count=0)
    connection.rollback()


def _insert_direct_terminal_run(cursor, status):
    terminal_values = {
        "completed": (1, 1, datetime.now(timezone.utc), "6" * 64, "7" * 64,
                      datetime.now(timezone.utc), None, None),
        "failed": (0, 0, None, None, None, None,
                   datetime.now(timezone.utc), "direct failure"),
    }[status]
    cursor.execute(
        """
        INSERT INTO nfl_moneyline_prediction_runs (
            run_key, request_sha256, run_type, evaluation_protocol_version,
            routing_contract_version, season, target_date, slate_start_time,
            slate_end_time, slate_fingerprint,
            early_model_specification_version, early_feature_schema_version,
            early_specification_fingerprint, early_model_fingerprint,
            mature_model_specification_version, mature_feature_schema_version,
            mature_specification_fingerprint, mature_model_fingerprint,
            target_count, prediction_count, status, source_data_as_of,
            source_snapshot_sha256, prediction_set_sha256, completed_at,
            failed_at, failure_message
        ) VALUES (
            %s, %s, 'preview', 'test-protocol', 'test-routing', 2026,
            '2099-09-10', '2099-09-10T00:00:00Z',
            '2099-09-11T00:00:00Z', %s,
            'early-model', 'early-schema', %s, %s,
            'mature-model', 'mature-schema', %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        );
        """,
        (
            uuid4(), "0" * 64, "1" * 64, "2" * 64, "4" * 64,
            "8" * 64, "a" * 64,
            terminal_values[0], terminal_values[1], status,
            terminal_values[2], terminal_values[3], terminal_values[4],
            terminal_values[5], terminal_values[6], terminal_values[7],
        ),
    )


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


def _create_run(
    connection, run_type, *, season=2026, target_count=1,
    slate_start=datetime(2099, 9, 10, tzinfo=timezone.utc),
    slate_end=datetime(2099, 9, 11, tzinfo=timezone.utc),
):
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
                '2099-09-10', %s, %s, %s,
                'early-model', 'early-schema', %s, %s,
                'mature-model', 'mature-schema', %s, %s, %s
            ) RETURNING nfl_moneyline_prediction_run_id;
            """,
            (
                uuid4(), "0" * 64, run_type, season,
                slate_start, slate_end, "1" * 64,
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
    source_data_as_of=None, probability=Decimal("0.6000000000000000"),
):
    kickoff = kickoff or datetime(2099, 9, 10, 20, tzinfo=timezone.utc)
    if route == "early":
        model, schema, specification = "early-model", "early-schema", "2" * 64
    else:
        model, schema, specification = "mature-model", "mature-schema", "8" * 64
        if model_fingerprint == "4" * 64:
            model_fingerprint = "a" * 64
    predicted_side = (
        "home" if probability >= Decimal("0.5000000000000000") else "away"
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT transaction_timestamp();")
        transaction_time = cursor.fetchone()[0]
        source_time = (
            transaction_time
            if source_data_as_of is None
            else source_data_as_of
        )
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
                %s, %s, %s, %s, %s, 'test-routing',
                %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, 0.55, 0.5,
                %s
            ) RETURNING nfl_moneyline_game_prediction_id;
            """,
            (
                run_id, run_type, game_id, kickoff, home_id, away_id, kickoff,
                source_time, home_count, away_count, route,
                model, schema, specification,
                model_fingerprint,
                Json({
                    "feature_schema_version": "early-schema",
                    "ordered_feature_names": ["x"],
                    "ordered_feature_values": [1.0],
                }),
                "3" * 64, Json({"channels": []}), "5" * 64, probability,
                predicted_side,
            ),
        )
        return cursor.fetchone()[0]
