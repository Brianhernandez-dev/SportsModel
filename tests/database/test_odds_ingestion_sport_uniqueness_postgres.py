from datetime import date

import psycopg2
from psycopg2.errors import UniqueViolation
import pytest

from sportsmodel.analysis.moneyline_early_entry_service import (
    _load_late_night_odds_run_id,
)
from sportsmodel.ingest.odds_api_parser import (
    ODDS_API_MLB_SPORT_KEY,
    ODDS_API_NFL_SPORT_KEY,
)


TARGET_DATE = date(2026, 9, 13)


def _insert_run(
    cursor,
    *,
    sport: str,
    role: str,
    status: str = "completed",
) -> int:
    cursor.execute(
        """
        INSERT INTO odds_ingestion_runs (
            sport,
            source_name,
            target_date,
            snapshot_role,
            status,
            completed_at
        )
        VALUES (
            %s,
            'odds_api_test_fixture',
            %s,
            %s,
            %s,
            CASE WHEN %s = 'running' THEN NULL ELSE CURRENT_TIMESTAMP END
        )
        RETURNING odds_ingestion_run_id;
        """,
        (sport, TARGET_DATE, role, status, status),
    )
    return cursor.fetchone()[0]


def test_mlb_scheduled_duplicate_is_rejected(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            _insert_run(
                cursor,
                sport=ODDS_API_MLB_SPORT_KEY,
                role="morning",
            )
        connection.commit()

        with pytest.raises(UniqueViolation):
            with connection.cursor() as cursor:
                _insert_run(
                    cursor,
                    sport=ODDS_API_MLB_SPORT_KEY,
                    role="morning",
                )
        connection.rollback()
    finally:
        connection.close()


def test_nfl_scheduled_duplicate_is_rejected(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            _insert_run(
                cursor,
                sport=ODDS_API_NFL_SPORT_KEY,
                role="morning",
            )
        connection.commit()

        with pytest.raises(UniqueViolation):
            with connection.cursor() as cursor:
                _insert_run(
                    cursor,
                    sport=ODDS_API_NFL_SPORT_KEY,
                    role="morning",
                )
        connection.rollback()
    finally:
        connection.close()


def test_same_scheduled_identity_is_allowed_across_sports(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            mlb_run_id = _insert_run(
                cursor,
                sport=ODDS_API_MLB_SPORT_KEY,
                role="late_night",
            )
            nfl_run_id = _insert_run(
                cursor,
                sport=ODDS_API_NFL_SPORT_KEY,
                role="late_night",
            )
        connection.commit()

        assert mlb_run_id != nfl_run_id
    finally:
        connection.close()


def test_manual_runs_remain_repeatable_within_one_sport(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            first = _insert_run(
                cursor,
                sport=ODDS_API_MLB_SPORT_KEY,
                role="manual",
            )
            second = _insert_run(
                cursor,
                sport=ODDS_API_MLB_SPORT_KEY,
                role="manual",
            )
        connection.commit()

        assert first != second
    finally:
        connection.close()


def test_existing_mlb_data_remains_and_mlb_lookup_ignores_newer_nfl_run(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM odds_ingestion_runs
                WHERE sport = %s;
                """,
                (ODDS_API_MLB_SPORT_KEY,),
            )
            assert cursor.fetchone()[0] >= 1

            mlb_run_id = _insert_run(
                cursor,
                sport=ODDS_API_MLB_SPORT_KEY,
                role="late_night",
            )
            _insert_run(
                cursor,
                sport=ODDS_API_NFL_SPORT_KEY,
                role="late_night",
            )
            selected = _load_late_night_odds_run_id(
                cursor,
                target_date=TARGET_DATE,
            )
        connection.commit()

        assert selected == mlb_run_id
    finally:
        connection.close()
