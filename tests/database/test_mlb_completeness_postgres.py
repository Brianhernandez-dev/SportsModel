"""PostgreSQL regression coverage for MLB feature-history selection."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg2
import pytest

from sportsmodel.database.mlb_completeness_repository import (
    FEATURE_TEAM_GAME_LIMIT,
    MLB_SOURCE_NAME,
    _load_required_feature_game_pks,
)


pytestmark = pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)


class _NonClosingConnection:
    """Let the query share a rollback-only setup transaction."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def cursor(self):
        return self._connection.cursor()

    def close(self) -> None:
        pass


def _disposable_database_url() -> str:
    database_url = os.environ["SPORTSMODEL_TEST_DATABASE_URL"]
    if os.getenv("SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB") != "1":
        pytest.skip(
            "PostgreSQL integration test requires explicit disposable-DB "
            "authorization"
        )

    application_url = os.getenv("DATABASE_URL")
    if application_url and application_url == database_url:
        pytest.fail(
            "SPORTSMODEL_TEST_DATABASE_URL must differ from DATABASE_URL"
        )

    parameters = psycopg2.extensions.parse_dsn(database_url)
    if (
        parameters.get("host") not in {"127.0.0.1", "localhost"}
        or parameters.get("port") != "55432"
        or parameters.get("dbname") != "sportsmodel_test"
    ):
        pytest.fail(
            "MLB completeness SQL test requires the proven loopback "
            "sportsmodel_test target on port 55432"
        )

    return database_url


def test_required_feature_games_use_exact_timestamp_and_window() -> None:
    database_url = _disposable_database_url()
    connection = psycopg2.connect(database_url)
    cutoff = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    label = uuid4().hex
    first_game_pk = 910_000_000
    history_game_pks = tuple(
        first_game_pk + index
        for index in range(FEATURE_TEAM_GAME_LIMIT + 1)
    )
    exact_cutoff_game_pk = first_game_pk + 10_000
    future_target_game_pk = first_game_pk + 10_001

    try:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute(
                "INSERT INTO teams (team_name) VALUES (%s) "
                "RETURNING team_id",
                (f"Completeness Home {label}",),
            )
            home_team_id = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO teams (team_name) VALUES (%s) "
                "RETURNING team_id",
                (f"Completeness Away {label}",),
            )
            away_team_id = cursor.fetchone()[0]

            game_rows = [
                (
                    cutoff - timedelta(minutes=index + 1),
                    game_pk,
                )
                for index, game_pk in enumerate(history_game_pks)
            ]
            game_rows.extend(
                (
                    (cutoff, exact_cutoff_game_pk),
                    (cutoff + timedelta(hours=6), future_target_game_pk),
                )
            )

            for game_time, game_pk in game_rows:
                cursor.execute(
                    """
                    INSERT INTO games (
                        game_date, home_team_id, away_team_id
                    ) VALUES (%s, %s, %s)
                    RETURNING game_id
                    """,
                    (game_time, home_team_id, away_team_id),
                )
                game_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO game_sources (
                        game_id, source_name, external_game_id
                    ) VALUES (%s, %s, %s)
                    """,
                    (game_id, MLB_SOURCE_NAME, str(game_pk)),
                )

        required_game_pks = _load_required_feature_game_pks(
            team_ids=(home_team_id,),
            cutoff_time=cutoff,
            connection_factory=lambda: _NonClosingConnection(connection),
        )

        assert len(required_game_pks) == FEATURE_TEAM_GAME_LIMIT
        assert history_game_pks[0] in required_game_pks
        assert history_game_pks[100] in required_game_pks
        assert history_game_pks[FEATURE_TEAM_GAME_LIMIT - 1] in (
            required_game_pks
        )
        assert history_game_pks[FEATURE_TEAM_GAME_LIMIT] not in (
            required_game_pks
        )
        assert exact_cutoff_game_pk not in required_game_pks
        assert future_target_game_pk not in required_game_pks
    finally:
        connection.rollback()
        connection.close()
