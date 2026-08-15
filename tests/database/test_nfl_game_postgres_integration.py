import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import psycopg2
import pytest

from sportsmodel.database.migrations import (
    apply_pending_migrations,
    discover_migrations,
    ensure_schema_migrations_table,
)
from sportsmodel.nfl.game_persistence import ingest_nflverse_games
from sportsmodel.nfl.nflverse_parser import (
    build_nflverse_team_identity_index,
    parse_nflverse_team_records,
)


ROOT = Path(__file__).parents[2]
FOUNDATION = (
    ROOT / "tests" / "fixtures" / "database" / "sportsmodel_foundation_schema.sql"
)
NFLVERSE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "nflverse" / "phase_1_source_rows.json"
)


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_migrations_and_nfl_game_ingestion_on_disposable_postgres() -> None:
    connection = psycopg2.connect(os.environ["SPORTSMODEL_TEST_DATABASE_URL"])
    try:
        with connection.cursor() as cursor:
            cursor.execute(FOUNDATION.read_text(encoding="utf-8-sig"))
        connection.commit()
        ensure_schema_migrations_table(connection)
        connection.commit()
        migrations = discover_migrations()
        assert apply_pending_migrations(connection, migrations[:5]) == 5
        # Migration 007 assumes at least one legacy odds snapshot exists so
        # MIN/MAX(snapshot_time) can satisfy its NOT NULL started_at backfill.
        # Reconstruct that approved legacy state without changing migration 007.
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO teams (team_name) VALUES ('Legacy Away') RETURNING team_id;"
            )
            away_team_id = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO teams (team_name) VALUES ('Legacy Home') RETURNING team_id;"
            )
            home_team_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO games (game_date, home_team_id, away_team_id)
                VALUES ('2025-01-01T00:00:00Z', %s, %s) RETURNING game_id;
                """,
                (home_team_id, away_team_id),
            )
            legacy_game_id = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO sportsbooks (name) VALUES ('Legacy Book') RETURNING sportsbook_id;"
            )
            sportsbook_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO odds_market_snapshots (
                    game_id, sportsbook_id, market_type, selection_name,
                    price, snapshot_time
                ) VALUES (%s, %s, 'h2h', 'Legacy Home', -110,
                          '2025-01-01T00:00:00Z');
                """,
                (legacy_game_id, sportsbook_id),
            )
        connection.commit()
        assert apply_pending_migrations(connection, migrations) == 18

        fixture_bytes = NFLVERSE_FIXTURE.read_bytes()
        fixture = json.loads(fixture_bytes.decode("utf-8-sig"))
        identities = build_nflverse_team_identity_index(
            parse_nflverse_team_records(fixture["teams"])
        )
        identities.update(TEN="2100", LAC="4400")
        wembley_rows = (
            {
                "game_id": "2018_07_TEN_LAC", "season": "2018",
                "game_type": "REG", "week": "7", "gameday": "2018-10-21",
                "gametime": "21:30", "away_team": "TEN", "away_score": "19",
                "home_team": "LAC", "home_score": "20", "location": "Neutral",
                "overtime": "0",
            },
            {
                "game_id": "2018_08_PHI_JAX", "season": "2018",
                "game_type": "REG", "week": "8", "gameday": "2018-10-28",
                "gametime": "21:30", "away_team": "PHI", "away_score": "24",
                "home_team": "JAX", "home_score": "18", "location": "Neutral",
                "overtime": "0",
            },
        )
        rows = (
            tuple(case["row"] for case in fixture["schedule_cases"])
            + wembley_rows
        )
        digest = sha256(fixture_bytes).hexdigest()
        retrieved_at = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)

        with connection.cursor() as cursor:
            first = ingest_nflverse_games(
                cursor,
                rows=rows,
                team_identities=identities,
                source_asset=str(NFLVERSE_FIXTURE),
                source_sha256=digest,
                retrieved_at=retrieved_at,
            )
            second = ingest_nflverse_games(
                cursor,
                rows=rows,
                team_identities=identities,
                source_asset=str(NFLVERSE_FIXTURE),
                source_sha256=digest,
                retrieved_at=retrieved_at,
            )
            scheduled = ingest_nflverse_games(
                cursor,
                rows=rows,
                team_identities=identities,
                source_asset=str(NFLVERSE_FIXTURE),
                source_sha256=digest,
                retrieved_at=retrieved_at,
                season_from=2026,
                season_to=2026,
            )
        connection.commit()

        assert first.rows_inserted == 7
        assert second.rows_inserted == 0
        assert second.rows_updated == 7
        assert scheduled.rows_inserted == 1

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 23;")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT COUNT(*) FROM nfl_team_profiles;")
            assert cursor.fetchone()[0] == 32
            cursor.execute("SELECT COUNT(*) FROM nfl_games;")
            assert cursor.fetchone()[0] == 8
            cursor.execute("SELECT COUNT(*) FROM game_sources WHERE source_name = 'nflverse';")
            assert cursor.fetchone()[0] == 8
            cursor.execute("SELECT COUNT(*) FROM nfl_game_source_observations;")
            assert cursor.fetchone()[0] == 15
            cursor.execute(
                """
                SELECT observation.provider_gametime,
                       observation.raw_payload->>'gametime',
                       observation.anomaly_state,
                       nfl.scheduled_start_time
                FROM nfl_game_source_observations observation
                JOIN nfl_games nfl ON nfl.game_id = observation.game_id
                WHERE observation.external_game_id = '2018_07_TEN_LAC'
                LIMIT 1;
                """
            )
            provider_time, raw_time, state, canonical_time = cursor.fetchone()
            assert provider_time == raw_time == "21:30"
            assert state == "overridden"
            assert canonical_time.hour == 13  # 09:30 Eastern in UTC
            cursor.execute(
                """
                SELECT status, home_score, away_score, overtime
                FROM nfl_games nfl
                JOIN game_sources source ON source.game_id = nfl.game_id
                WHERE source.source_name = 'nflverse'
                  AND source.external_game_id = '2026_01_NE_SEA';
                """
            )
            assert cursor.fetchone() == ("unplayed", None, None, None)
            cursor.execute(
                """
                SELECT COUNT(*) FROM game_sources
                WHERE source_name = 'nflverse'
                  AND external_game_id LIKE '2022%BUF%CIN%';
                """
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT team_name FROM teams WHERE team_id = 5;")
            assert cursor.fetchone()[0] == "Athletics"
    finally:
        connection.close()
