import os
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

from sportsmodel.database.moneyline_daily_workflow_repository import (
    load_moneyline_daily_official_evidence_counts,
)
from sportsmodel.ingest.game_matching import (
    CanonicalGameIdentityConflictError,
    get_or_create_canonical_game,
)


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_mlb_cross_source_identity_is_schedule_drift_and_doubleheader_safe(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        home_team_id, away_team_id = _create_teams(connection, "Single")
        scheduled_time = datetime(
            2026, 9, 14, 23, 30, tzinfo=timezone.utc
        )
        canonical_game_id = _create_game_with_source(
            connection,
            game_datetime=scheduled_time,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            source_name="mlb_stats",
            external_game_id="900001",
        )

        with connection.cursor() as cursor:
            matched_game_id = get_or_create_canonical_game(
                cursor,
                source_name="odds_api",
                external_game_id="single-event",
                game_datetime=scheduled_time + timedelta(hours=2),
                home_team_id=home_team_id,
                away_team_id=away_team_id,
            )
        connection.commit()

        assert matched_game_id == canonical_game_id

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT game_id FROM game_sources "
                "WHERE source_name = 'odds_api' "
                "AND external_game_id = 'single-event';"
            )
            assert cursor.fetchone() == (canonical_game_id,)

        double_home_id, double_away_id = _create_teams(
            connection, "Double"
        )
        _create_game_with_source(
            connection,
            game_datetime=scheduled_time,
            home_team_id=double_home_id,
            away_team_id=double_away_id,
            source_name="mlb_stats",
            external_game_id="900002",
        )
        _create_game_with_source(
            connection,
            game_datetime=scheduled_time + timedelta(hours=4),
            home_team_id=double_home_id,
            away_team_id=double_away_id,
            source_name="mlb_stats",
            external_game_id="900003",
        )

        with connection.cursor() as cursor:
            with pytest.raises(
                CanonicalGameIdentityConflictError,
                match="doubleheader or schedule identity is ambiguous",
            ):
                get_or_create_canonical_game(
                    cursor,
                    source_name="odds_api",
                    external_game_id="ambiguous-event",
                    game_datetime=scheduled_time + timedelta(hours=6),
                    home_team_id=double_home_id,
                    away_team_id=double_away_id,
                )
        connection.rollback()

        stale_home_id, stale_away_id = _create_teams(connection, "Stale")
        authoritative_game_id = _create_game_with_source(
            connection,
            game_datetime=scheduled_time,
            home_team_id=stale_home_id,
            away_team_id=stale_away_id,
            source_name="mlb_stats",
            external_game_id="900004",
        )
        stale_game_id = _create_game_with_source(
            connection,
            game_datetime=scheduled_time + timedelta(minutes=1),
            home_team_id=stale_home_id,
            away_team_id=stale_away_id,
            source_name="odds_api",
            external_game_id="stale-event",
        )

        with connection.cursor() as cursor:
            with pytest.raises(
                CanonicalGameIdentityConflictError,
                match=(
                    f"maps to {stale_game_id}, "
                    f"candidate={authoritative_game_id}"
                ),
            ):
                get_or_create_canonical_game(
                    cursor,
                    source_name="odds_api",
                    external_game_id="stale-event",
                    game_datetime=scheduled_time + timedelta(minutes=1),
                    home_team_id=stale_home_id,
                    away_team_id=stale_away_id,
                )
        connection.rollback()
    finally:
        connection.close()


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_failed_evaluation_evidence_counts_require_exact_linkage(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO moneyline_prediction_runs (
                    target_date, model_version, feature_schema_version,
                    model_artifact_sha256, started_at, completed_at,
                    status, games_received, predictions_created,
                    games_skipped, run_type
                ) VALUES (
                    %s, 'model', 'schema', %s,
                    clock_timestamp(), clock_timestamp(),
                    'completed', 15, 15, 0, 'official'
                ) RETURNING moneyline_prediction_run_id;
                """,
                (date(2026, 9, 13), "a" * 64),
            )
            prediction_run_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO odds_ingestion_runs (
                    sport, source_name, started_at, completed_at, status,
                    games_returned, games_processed, selections_inserted,
                    selections_skipped, target_date, snapshot_role,
                    status_code, remaining_requests, used_requests
                ) VALUES (
                    'baseball_mlb', 'odds_api', clock_timestamp(),
                    clock_timestamp(), 'completed', 15, 15, 270, 0,
                    %s, 'entry', 200, 425, 75
                ) RETURNING odds_ingestion_run_id;
                """,
                (date(2026, 9, 13),),
            )
            odds_run_id = cursor.fetchone()[0]
        connection.commit()

        with connection.cursor() as cursor:
            counts = load_moneyline_daily_official_evidence_counts(
                cursor,
                target_date=date(2026, 9, 13),
                sport="baseball_mlb",
                prediction_run_id=prediction_run_id,
                odds_ingestion_run_id=odds_run_id,
            )

        assert counts.prediction_runs == 1
        assert counts.entry_odds_runs == 1
        assert counts.linked_prediction_runs == 1
        assert counts.linked_entry_odds_runs == 1
        assert counts.market_evaluations == 0
        assert counts.paper_candidates == 0
        assert counts.settlements == 0
    finally:
        connection.close()


def _create_teams(connection, label: str) -> tuple[int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO teams (team_name) VALUES (%s) RETURNING team_id;",
            (f"{label} Home",),
        )
        home_team_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO teams (team_name) VALUES (%s) RETURNING team_id;",
            (f"{label} Away",),
        )
        away_team_id = cursor.fetchone()[0]
    connection.commit()
    return home_team_id, away_team_id


def _create_game_with_source(
    connection,
    *,
    game_datetime: datetime,
    home_team_id: int,
    away_team_id: int,
    source_name: str,
    external_game_id: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO games (game_date, home_team_id, away_team_id)
            VALUES (%s, %s, %s) RETURNING game_id;
            """,
            (game_datetime, home_team_id, away_team_id),
        )
        game_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO game_sources (
                game_id, source_name, external_game_id
            ) VALUES (%s, %s, %s);
            """,
            (game_id, source_name, external_game_id),
        )
    connection.commit()
    return game_id
