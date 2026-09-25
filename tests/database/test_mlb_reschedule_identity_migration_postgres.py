import os

import psycopg2
from psycopg2.errors import UniqueViolation
import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)


def test_migration_032_retains_only_the_intended_cardinality_changes(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            first_game, second_game = _create_games(cursor)

            cursor.execute(
                "INSERT INTO game_sources(game_id,source_name,external_game_id) "
                "VALUES(%s,'odds_api','old-event'),"
                "(%s,'odds_api','replacement-event')",
                (first_game, first_game),
            )
            cursor.execute(
                "SELECT external_game_id FROM game_sources "
                "WHERE game_id=%s AND source_name='odds_api' "
                "ORDER BY external_game_id",
                (first_game,),
            )
            assert cursor.fetchall() == [("old-event",), ("replacement-event",)]

            cursor.execute("SAVEPOINT non_odds_cardinality")
            cursor.execute(
                "INSERT INTO game_sources(game_id,source_name,external_game_id) "
                "VALUES(%s,'mlb_stats','824785')",
                (first_game,),
            )
            with pytest.raises(UniqueViolation):
                cursor.execute(
                    "INSERT INTO game_sources"
                    "(game_id,source_name,external_game_id) "
                    "VALUES(%s,'mlb_stats','replacement-mlb-id')",
                    (first_game,),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT non_odds_cardinality")

            cursor.execute("SAVEPOINT provider_identity")
            with pytest.raises(UniqueViolation):
                cursor.execute(
                    "INSERT INTO game_sources"
                    "(game_id,source_name,external_game_id) "
                    "VALUES(%s,'odds_api','old-event')",
                    (second_game,),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT provider_identity")

            cursor.execute(
                "SELECT pg_get_functiondef("
                "'protect_odds_snapshot_provenance'::regproc)"
            )
            function_definition = cursor.fetchone()[0].lower()
            assert "new.game_id is distinct from old.game_id" not in (
                function_definition
            )
            assert "provenance-bearing odds snapshots are immutable" in (
                function_definition
            )
        connection.rollback()
    finally:
        connection.close()


def _create_games(cursor) -> tuple[int, int]:
    cursor.execute(
        "INSERT INTO teams(team_name) VALUES"
        "('Prevention Home'),('Prevention Away') RETURNING team_id"
    )
    home_id, away_id = (row[0] for row in cursor.fetchall())
    cursor.execute(
        "INSERT INTO games(game_date,home_team_id,away_team_id) VALUES"
        "('2026-09-22T22:35:00Z',%s,%s),"
        "('2026-09-23T22:35:00Z',%s,%s) RETURNING game_id",
        (home_id, away_id, home_id, away_id),
    )
    first_game, second_game = (row[0] for row in cursor.fetchall())
    return first_game, second_game
