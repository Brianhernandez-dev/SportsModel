import os
from copy import deepcopy
from datetime import datetime, timezone

import psycopg2
import pytest

from sportsmodel.nfl.historical_backfill import (
    build_nflverse_historical_backfill_plan,
)
from sportsmodel.nfl.historical_backfill_cli import (
    AssetProvenance,
    PreparedHistoricalBackfill,
)
from sportsmodel.nfl.historical_backfill_persistence import (
    audit_historical_backfill_integrity,
    persist_validated_historical_backfill,
)
from sportsmodel.nfl.team_statistics_persistence import (
    ingest_nflverse_team_game_statistics,
)


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_historical_orchestration_is_idempotent_on_disposable_postgres(
    initialized_nfl_test_database,
):
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        prepared = _prepared_snapshot()
        first = persist_validated_historical_backfill(
            connection, prepared=prepared
        )
        assert (first.schedule.rows_processed, first.schedule.rows_inserted,
                first.schedule.rows_updated, first.schedule.rows_quarantined) == (2, 2, 0, 0)
        assert (first.team_statistics.processed,
                first.team_statistics.inserted,
                first.team_statistics.updated) == (4, 4, 0)
        assert first.integrity.ready
        game_ids_before, statistic_id, observation_count = _stable_ids(connection)

        second = persist_validated_historical_backfill(
            connection, prepared=prepared
        )
        assert (second.schedule.rows_inserted, second.schedule.rows_updated) == (0, 2)
        assert (second.team_statistics.inserted,
                second.team_statistics.updated) == (0, 4)
        assert second.integrity.ready
        game_ids_after, statistic_id_after, observations_after = _stable_ids(connection)
        assert game_ids_after == game_ids_before
        assert statistic_id_after == statistic_id
        assert observations_after == observation_count + 4

        original = prepared.plan.accepted_team_statistics_rows[0]
        corrected = deepcopy(original)
        corrected["passing_yards"] = str(int(original["passing_yards"]) + 7)
        correction = ingest_nflverse_team_game_statistics(
            connection, rows=(corrected,),
            team_identities=prepared.team_identities,
            source_asset="disposable-correction-proof",
            source_sha256="c" * 64,
            retrieved_at=datetime(2026, 8, 15, 6, tzinfo=timezone.utc),
        )
        assert (correction.rows_inserted, correction.rows_updated) == (0, 1)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT nfl_team_game_statistics_id, passing_yards
                FROM nfl_team_game_statistics
                WHERE nfl_team_game_statistics_id = %s
            """, (statistic_id,))
            assert cursor.fetchone() == (statistic_id, int(corrected["passing_yards"]))
            cursor.execute("SELECT COUNT(*) FROM nfl_team_game_statistics")
            assert cursor.fetchone()[0] == 4
            cursor.execute(
                "SELECT COUNT(*) FROM nfl_team_game_statistics_source_observations"
            )
            assert cursor.fetchone()[0] == observations_after + 1

        restore = ingest_nflverse_team_game_statistics(
            connection, rows=(original,),
            team_identities=prepared.team_identities,
            source_asset="disposable-correction-proof-restore",
            source_sha256="d" * 64,
            retrieved_at=datetime(2026, 8, 15, 7, tzinfo=timezone.utc),
        )
        assert restore.rows_updated == 1
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT passing_yards
                FROM nfl_team_game_statistics
                WHERE nfl_team_game_statistics_id = %s
            """, (statistic_id,))
            assert cursor.fetchone()[0] == int(original["passing_yards"])
        run_ids = (
            second.schedule.nfl_ingestion_run_id,
            *(item.ingestion.nfl_ingestion_run_id
              for item in second.team_statistics.annual_results),
        )
        final_audit = audit_historical_backfill_integrity(
            connection, season_from=2018, season_to=2018,
            run_ids=run_ids,
            schedule_run_id=second.schedule.nfl_ingestion_run_id,
            expected_game_count=2, expected_statistics_count=4,
            team_identities=prepared.team_identities,
        )
        assert final_audit.ready
    finally:
        connection.close()


def _prepared_snapshot():
    identities = {"TEN": "2100", "LAC": "4400", "PHI": "3700", "JAX": "2250"}
    schedules = (
        _schedule("2018_07_TEN_LAC", 7, "2018-10-21", "TEN", "LAC", 19, 20),
        _schedule("2018_08_PHI_JAX", 8, "2018-10-28", "PHI", "JAX", 24, 18),
    )
    stats = (
        _stat("2018_07_TEN_LAC", 7, "TEN", "LAC", 150),
        _stat("2018_07_TEN_LAC", 7, "LAC", "TEN", 200),
        _stat("2018_08_PHI_JAX", 8, "PHI", "JAX", 250),
        _stat("2018_08_PHI_JAX", 8, "JAX", "PHI", 175),
    )
    plan = build_nflverse_historical_backfill_plan(
        schedules, stats, team_identities=identities,
        season_from=2018, season_to=2018,
    )
    assert plan.is_valid
    provenance = (
        AssetProvenance("schedules", None, "compact-schedule.csv", 1, 2,
                        "a" * 64, "2026-08-15T05:36:29Z"),
        AssetProvenance("teams", None, "compact-teams.csv", 1, 4,
                        "b" * 64, "2026-08-15T05:36:29Z"),
        AssetProvenance("team_statistics", 2018, "compact-stats-2018.csv", 1, 4,
                        "c" * 64, "2026-08-15T05:36:29Z"),
    )
    return PreparedHistoricalBackfill(
        report={
            "backfill_ready": True,
            "reconciliation": {"issue_count": 0},
            "approved_schedule_contract": None,
            "provenance": [{"retrieved_at": "2026-08-15T05:36:29Z"}],
        },
        plan=plan, team_identities=identities, provenance=provenance,
    )


def _schedule(game_id, week, gameday, away, home, away_score, home_score):
    return {
        "game_id": game_id, "season": "2018", "game_type": "REG",
        "week": str(week), "gameday": gameday, "gametime": "21:30",
        "away_team": away, "away_score": str(away_score),
        "home_team": home, "home_score": str(home_score),
        "location": "Neutral", "overtime": "0",
    }


def _stat(game_id, week, team, opponent, passing_yards):
    return {
        "game_id": game_id, "season": "2018", "season_type": "REG",
        "week": str(week), "team": team, "opponent_team": opponent,
        "completions": "20", "attempts": "30",
        "passing_yards": str(passing_yards), "passing_tds": "2",
        "passing_interceptions": "1", "sacks_suffered": "2",
        "carries": "20", "rushing_yards": "80", "rushing_tds": "1",
        "fumbles_lost_total": "0", "penalties": "5", "penalty_yards": "40",
    }


def _stable_ids(connection):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT external_game_id, game_id FROM game_sources
            WHERE source_name = 'nflverse' ORDER BY external_game_id
        """)
        games = tuple(cursor.fetchall())
        cursor.execute("""
            SELECT nfl_team_game_statistics_id
            FROM nfl_team_game_statistics ORDER BY nfl_team_game_statistics_id LIMIT 1
        """)
        statistic_id = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM nfl_team_game_statistics_source_observations")
        observations = cursor.fetchone()[0]
    return games, statistic_id, observations
