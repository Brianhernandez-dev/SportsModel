import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import psycopg2
import pytest

from sportsmodel.database.nfl_game_repository import (
    list_nfl_games_by_season,
    load_nfl_game_by_id,
)
from sportsmodel.database.nfl_team_game_statistics_repository import (
    list_nfl_team_game_statistics_for_game,
    list_nfl_team_game_statistics_for_team_season,
    load_nfl_team_game_statistics,
)
from sportsmodel.nfl.game_persistence import ingest_nflverse_games
from sportsmodel.nfl.team_statistics_persistence import (
    ingest_nflverse_team_game_statistics,
)
from sportsmodel.nfl.nflverse_parser import (
    build_nflverse_team_identity_index,
    parse_nflverse_team_records,
)


ROOT = Path(__file__).parents[2]
NFLVERSE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "nflverse" / "phase_1_source_rows.json"
)


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_migrations_and_nfl_game_ingestion_on_disposable_postgres(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        fixture_bytes = NFLVERSE_FIXTURE.read_bytes()
        fixture = json.loads(fixture_bytes.decode("utf-8-sig"))
        identities = build_nflverse_team_identity_index(
            parse_nflverse_team_records(fixture["teams"])
        )
        identities.update(TEN="2100", LAC="4400", DEN="1400")
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
            + ({
                "game_id": "2025_01_DAL_PHI", "season": "2025",
                "game_type": "REG", "week": "1", "gameday": "2025-09-04",
                "gametime": "20:20", "away_team": "DAL", "away_score": "20",
                "home_team": "PHI", "home_score": "24", "location": "Home",
                "overtime": "0",
            }, {
                "game_id": "2019_01_DEN_OAK", "season": "2019",
                "game_type": "REG", "week": "1", "gameday": "2019-09-09",
                "gametime": "22:20", "away_team": "DEN", "away_score": "16",
                "home_team": "OAK", "home_score": "24", "location": "Home",
                "overtime": "0",
            },)
        )
        digest = sha256(fixture_bytes).hexdigest()
        retrieved_at = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)

        first = ingest_nflverse_games(
            connection,
            rows=rows,
            team_identities=identities,
            source_asset=str(NFLVERSE_FIXTURE),
            source_sha256=digest,
            retrieved_at=retrieved_at,
        )
        second = ingest_nflverse_games(
            connection,
            rows=rows,
            team_identities=identities,
            source_asset=str(NFLVERSE_FIXTURE),
            source_sha256=digest,
            retrieved_at=retrieved_at,
        )
        scheduled = ingest_nflverse_games(
            connection,
            rows=rows,
            team_identities=identities,
            source_asset=str(NFLVERSE_FIXTURE),
            source_sha256=digest,
            retrieved_at=retrieved_at,
            season_from=2026,
            season_to=2026,
        )

        assert first.rows_inserted == 9
        assert second.rows_inserted == 0
        assert second.rows_updated == 9
        assert scheduled.rows_inserted == 1

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 23;")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT COUNT(*) FROM nfl_team_profiles;")
            assert cursor.fetchone()[0] == 32
            cursor.execute("SELECT COUNT(*) FROM nfl_games;")
            assert cursor.fetchone()[0] == 10
            cursor.execute("SELECT COUNT(*) FROM game_sources WHERE source_name = 'nflverse';")
            assert cursor.fetchone()[0] == 10
            cursor.execute("SELECT COUNT(*) FROM nfl_game_source_observations;")
            assert cursor.fetchone()[0] == 19
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
                SELECT raw_payload, raw_row_sha256
                FROM nfl_game_source_observations
                WHERE external_game_id = '2018_07_TEN_LAC'
                ORDER BY nfl_game_source_observation_id LIMIT 1;
                """
            )
            retained_payload, retained_hash = cursor.fetchone()
            expected_row = wembley_rows[0]
            expected_json = json.dumps(
                expected_row,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            assert retained_hash == sha256(expected_json.encode("utf-8")).hexdigest()
            assert retained_payload == expected_row
            assert retained_payload["gametime"] == "21:30"
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

        _assert_provider_independent_canonical_reads(connection)
        _assert_team_statistics_persistence(
            connection, fixture["team_stats"], identities, digest, retrieved_at
        )
        _assert_quarantine_continues_run(
            connection, identities, digest, retrieved_at, wembley_rows[0]
        )
        _assert_failed_run_is_durable_and_atomic(
            connection, identities, digest, retrieved_at
        )
        _assert_provider_identity_conflict_is_atomic(
            connection, identities, digest, retrieved_at
        )
    finally:
        connection.close()


def _assert_team_statistics_persistence(
    connection, rows, identities, digest, retrieved_at
) -> None:
    signed_rows = deepcopy(rows)
    signed_rows[0]["passing_yards"] = "-7"
    signed_rows[0]["rushing_yards"] = "-3"
    first = ingest_nflverse_team_game_statistics(
        connection, rows=signed_rows, team_identities=identities,
        source_asset="team-stats-first", source_sha256=digest,
        retrieved_at=retrieved_at)
    repeat = ingest_nflverse_team_game_statistics(
        connection, rows=signed_rows, team_identities=identities,
        source_asset="team-stats-repeat", source_sha256=digest,
        retrieved_at=retrieved_at)
    assert (first.rows_inserted, first.rows_updated) == (2, 0)
    assert (repeat.rows_inserted, repeat.rows_updated) == (0, 2)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT game_id FROM game_sources WHERE source_name = 'nflverse' "
            "AND external_game_id = '2025_01_DAL_PHI';")
        game_id = cursor.fetchone()[0]
        cursor.execute(
            "SELECT team_id FROM nfl_team_sources WHERE source_name = 'nflverse' "
            "AND external_team_id = '1200';")
        dal_id = cursor.fetchone()[0]
        signed = load_nfl_team_game_statistics(
            cursor, game_id=game_id, team_id=dal_id)
        assert signed.passing_yards == -7
        assert signed.rushing_yards == -3
    corrected = deepcopy(signed_rows[0])
    corrected["passing_yards"] = "-9"
    correction = ingest_nflverse_team_game_statistics(
        connection, rows=(corrected,), team_identities=identities,
        source_asset="team-stats-correction", source_sha256=digest,
        retrieved_at=retrieved_at)
    assert correction.rows_updated == 1
    with connection.cursor() as cursor:
        canonical = load_nfl_team_game_statistics(
            cursor, game_id=game_id, team_id=dal_id)
        assert canonical.passing_yards == -9
        assert len(list_nfl_team_game_statistics_for_game(
            cursor, game_id=game_id)) == 2
        assert len(list_nfl_team_game_statistics_for_team_season(
            cursor, team_id=dal_id, season=2025)) == 1
        cursor.execute("SELECT COUNT(*) FROM nfl_team_game_statistics;")
        assert cursor.fetchone()[0] == 2
        cursor.execute(
            "SELECT COUNT(*) FROM nfl_team_game_statistics_source_observations;")
        assert cursor.fetchone()[0] == 5
        cursor.execute(
            "SELECT raw_payload, raw_row_sha256 FROM "
            "nfl_team_game_statistics_source_observations "
            "WHERE nfl_ingestion_run_id = %s ORDER BY "
            "nfl_team_game_statistics_source_observation_id LIMIT 1;",
            (first.nfl_ingestion_run_id,))
        raw_payload, raw_hash = cursor.fetchone()
        expected_json = json.dumps(
            signed_rows[0], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert raw_payload == signed_rows[0]
        assert raw_hash == sha256(expected_json.encode("utf-8")).hexdigest()
    alias_row = dict(
        signed_rows[0], season="2019", week="1", team="OAK",
        opponent_team="DEN", game_id="2019_01_DEN_OAK")
    alias_result = ingest_nflverse_team_game_statistics(
        connection, rows=(alias_row,), team_identities=identities,
        source_asset="team-stats-oak-alias", source_sha256=digest,
        retrieved_at=retrieved_at)
    assert alias_result.rows_inserted == 1
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT profile.current_abbreviation, source.external_team_id "
            "FROM nfl_team_game_statistics stats "
            "JOIN nfl_team_profiles profile ON profile.team_id = stats.team_id "
            "JOIN nfl_team_sources source ON source.team_id = stats.team_id "
            "WHERE source.source_name = 'nflverse' AND stats.game_id = "
            "(SELECT game_id FROM game_sources WHERE source_name = 'nflverse' "
            "AND external_game_id = '2019_01_DEN_OAK');")
        assert cursor.fetchone() == ("LV", "2520")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "UPDATE nfl_team_game_statistics SET carries = -1 "
                "WHERE game_id = %s AND team_id = %s;", (game_id, dal_id))
    connection.rollback()
    bad = deepcopy(rows[1])
    bad["game_id"] = "2025_02_DAL_PHI"
    bad["week"] = "2"
    valid_but_rolled_back = deepcopy(rows[0])
    valid_but_rolled_back["passing_yards"] = "250"
    with pytest.raises(ValueError, match="No canonical NFL game"):
        ingest_nflverse_team_game_statistics(
            connection, rows=(valid_but_rolled_back, bad),
            team_identities=identities, source_asset="team-stats-failed",
            source_sha256=digest, retrieved_at=retrieved_at)
    with connection.cursor() as cursor:
        canonical = load_nfl_team_game_statistics(
            cursor, game_id=game_id, team_id=dal_id)
        assert canonical.passing_yards == -9
        cursor.execute(
            "SELECT status FROM nfl_ingestion_runs "
            "WHERE source_asset = 'team-stats-failed';")
        assert cursor.fetchone()[0] == "failed"
        cursor.execute(
            "SELECT COUNT(*) FROM nfl_team_game_statistics_source_observations o "
            "JOIN nfl_ingestion_runs r ON r.nfl_ingestion_run_id = o.nfl_ingestion_run_id "
            "WHERE r.source_asset = 'team-stats-failed';")
        assert cursor.fetchone()[0] == 0


def _assert_provider_independent_canonical_reads(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT game_id FROM game_sources
            WHERE source_name = 'nflverse'
              AND external_game_id = '2023_01_DET_KC';
            """
        )
        game_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO game_sources (game_id, source_name, external_game_id)
            VALUES (%s, 'second_provider', 'second-provider-event');
            """,
            (game_id,),
        )
        canonical = load_nfl_game_by_id(cursor, game_id=game_id)
        season_games = list_nfl_games_by_season(cursor, season=2023)
    connection.commit()
    assert canonical is not None
    assert canonical.game_id == game_id
    assert sum(game.game_id == game_id for game in season_games) == 1


def _assert_quarantine_continues_run(
    connection, identities, digest, retrieved_at, reviewed_row
) -> None:
    mismatch = deepcopy(reviewed_row)
    mismatch["gametime"] = "20:30"
    valid = {
        "game_id": "2024_02_ATL_JAX", "season": "2024",
        "game_type": "REG", "week": "2", "gameday": "2024-09-15",
        "gametime": "13:00", "away_team": "ATL", "away_score": "17",
        "home_team": "JAX", "home_score": "20", "location": "Home",
        "overtime": "0",
    }
    result = ingest_nflverse_games(
        connection,
        rows=(mismatch, valid),
        team_identities=identities,
        source_asset="quarantine-test",
        source_sha256=digest,
        retrieved_at=retrieved_at,
        season_from=2018,
        season_to=2024,
    )
    assert result.rows_processed == 2
    assert result.rows_quarantined == 1
    assert result.rows_inserted == 1
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT game_id, anomaly_state, raw_payload->>'gametime',
                   anomaly_reason, override_provenance
            FROM nfl_game_source_observations
            WHERE nfl_ingestion_run_id = %s
              AND external_game_id = '2018_07_TEN_LAC';
            """,
            (result.nfl_ingestion_run_id,),
        )
        game_id, state, raw_time, reason, provenance = cursor.fetchone()
        assert game_id is None
        assert state == "quarantined"
        assert raw_time == "20:30"
        assert "evidence mismatch" in reason
        assert "nflverse_2018_2025_coverage_audit.md" in provenance
        cursor.execute(
            """
            SELECT COUNT(*) FROM game_sources
            WHERE source_name = 'nflverse'
              AND external_game_id = '2024_02_ATL_JAX';
            """
        )
        assert cursor.fetchone()[0] == 1


def _assert_failed_run_is_durable_and_atomic(
    connection, identities, digest, retrieved_at
) -> None:
    valid = {
        "game_id": "2024_03_DAL_PHI", "season": "2024",
        "game_type": "REG", "week": "3", "gameday": "2024-09-22",
        "gametime": "13:00", "away_team": "DAL", "away_score": "21",
        "home_team": "PHI", "home_score": "24", "location": "Home",
        "overtime": "0",
    }
    malformed_id = "x" * 101
    malformed = dict(valid, game_id=malformed_id, week="4")
    with pytest.raises(psycopg2.errors.StringDataRightTruncation):
        ingest_nflverse_games(
            connection,
            rows=(valid, malformed),
            team_identities=identities,
            source_asset="failed-run-test",
            source_sha256=digest,
            retrieved_at=retrieved_at,
            season_from=2024,
            season_to=2024,
        )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT nfl_ingestion_run_id, status, error_message
            FROM nfl_ingestion_runs WHERE source_asset = 'failed-run-test';
            """
        )
        run_id, status, error_message = cursor.fetchone()
        assert status == "failed"
        assert "value too long" in error_message
        cursor.execute(
            "SELECT COUNT(*) FROM nfl_game_source_observations WHERE nfl_ingestion_run_id = %s;",
            (run_id,),
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            """
            SELECT COUNT(*) FROM game_sources
            WHERE source_name = 'nflverse'
              AND external_game_id = '2024_03_DAL_PHI';
            """
        )
        assert cursor.fetchone()[0] == 0
    subsequent = ingest_nflverse_games(
        connection,
        rows=(valid,),
        team_identities=identities,
        source_asset="post-failure-valid-test",
        source_sha256=digest,
        retrieved_at=retrieved_at,
        season_from=2024,
        season_to=2024,
    )
    assert subsequent.rows_inserted == 1


def _assert_provider_identity_conflict_is_atomic(
    connection, identities, digest, retrieved_at
) -> None:
    conflict = {
        "game_id": "2023_01_DET_KC", "season": "2023",
        "game_type": "REG", "week": "1", "gameday": "2023-09-07",
        "gametime": "20:20", "away_team": "DET", "away_score": "21",
        "home_team": "JAX", "home_score": "20", "location": "Home",
        "overtime": "0",
    }
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM nfl_games;")
        before = cursor.fetchone()[0]
    with pytest.raises(ValueError, match="conflicting matchup"):
        ingest_nflverse_games(
            connection,
            rows=(conflict,),
            team_identities=identities,
            source_asset="identity-conflict-test",
            source_sha256=digest,
            retrieved_at=retrieved_at,
            season_from=2023,
            season_to=2023,
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM nfl_games;")
        assert cursor.fetchone()[0] == before
        cursor.execute(
            """
            SELECT home.current_abbreviation, away.current_abbreviation
            FROM game_sources source
            JOIN games game ON game.game_id = source.game_id
            JOIN nfl_team_profiles home ON home.team_id = game.home_team_id
            JOIN nfl_team_profiles away ON away.team_id = game.away_team_id
            WHERE source.source_name = 'nflverse'
              AND source.external_game_id = '2023_01_DET_KC';
            """
        )
        assert cursor.fetchone() == ("KC", "DET")
