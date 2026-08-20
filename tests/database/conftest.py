"""Shared initialization for explicit disposable PostgreSQL integration tests."""

import os
from pathlib import Path

import psycopg2
import pytest

from sportsmodel.database.migrations import (
    apply_pending_migrations,
    discover_migrations,
    ensure_schema_migrations_table,
)


ROOT = Path(__file__).parents[2]
FOUNDATION = (
    ROOT / "tests" / "fixtures" / "database" / "sportsmodel_foundation_schema.sql"
)


@pytest.fixture
def initialized_nfl_test_database() -> str:
    """Recreate the schema only in the explicitly configured disposable DB."""

    database_url = _require_destructive_test_database_configuration()
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA public CASCADE")
            cursor.execute("CREATE SCHEMA public")
            cursor.execute(FOUNDATION.read_text(encoding="utf-8-sig"))
        connection.commit()
        ensure_schema_migrations_table(connection)
        connection.commit()
        migrations = discover_migrations()
        assert apply_pending_migrations(connection, migrations[:5]) == 5
        _create_legacy_migration_state(connection)
        assert apply_pending_migrations(connection, migrations) == len(migrations) - 5
    finally:
        connection.close()
    return database_url


def _require_destructive_test_database_configuration() -> str:
    """Require both explicit protections before any database connection."""

    database_url = os.getenv("SPORTSMODEL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires disposable SPORTSMODEL_TEST_DATABASE_URL")
    if os.getenv("SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB") != "1":
        pytest.skip(
            "destructive disposable database initialization requires "
            "SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB=1"
        )
    application_url = os.getenv("DATABASE_URL")
    if application_url and database_url == application_url:
        pytest.skip(
            "SPORTSMODEL_TEST_DATABASE_URL must differ from application "
            "DATABASE_URL before destructive initialization"
        )
    return database_url


def _create_legacy_migration_state(connection) -> None:
    """Reconstruct the approved pre-migration-007 snapshot requirement."""

    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO teams (team_name) VALUES ('Legacy Away') RETURNING team_id"
        )
        away_team_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO teams (team_name) VALUES ('Legacy Home') RETURNING team_id"
        )
        home_team_id = cursor.fetchone()[0]
        cursor.execute("""
            INSERT INTO games (game_date, home_team_id, away_team_id)
            VALUES ('2025-01-01T00:00:00Z', %s, %s) RETURNING game_id
        """, (home_team_id, away_team_id))
        legacy_game_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO sportsbooks (name) VALUES ('Legacy Book') "
            "RETURNING sportsbook_id"
        )
        sportsbook_id = cursor.fetchone()[0]
        cursor.execute("""
            INSERT INTO odds_market_snapshots (
                game_id, sportsbook_id, market_type, selection_name,
                price, snapshot_time
            ) VALUES (%s, %s, 'h2h', 'Legacy Home', -110,
                      '2025-01-01T00:00:00Z')
        """, (legacy_game_id, sportsbook_id))
    connection.commit()
