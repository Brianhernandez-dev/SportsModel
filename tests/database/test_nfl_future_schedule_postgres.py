import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import psycopg2

from sportsmodel.nfl.future_schedule import (
    build_future_schedule_plan,
    persist_future_schedule,
)


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "nflverse" / "phase_1_source_rows.json"
RETRIEVED_AT = datetime(2026, 8, 22, 17, 8, 36, tzinfo=timezone.utc)


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _row(**changes):
    result = dict(_fixture()["schedule_cases"][-1]["row"])
    result.update(changes)
    return result


def _plan(connection, rows):
    with connection.cursor() as cursor:
        return build_future_schedule_plan(
            cursor,
            schedule_rows=rows,
            team_rows=_fixture()["teams"],
            season=2026,
        )


def test_future_schedule_insert_update_and_idempotent_skip(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    digest = sha256(FIXTURE.read_bytes()).hexdigest()
    try:
        first_plan = _plan(connection, [_row()])
        assert first_plan.ready and first_plan.count("new") == 1
        first = persist_future_schedule(
            connection,
            plan=first_plan,
            source_asset=str(FIXTURE),
            source_sha256=digest,
            retrieved_at=RETRIEVED_AT,
        )
        assert (first.rows_inserted, first.rows_updated, first.rows_skipped) == (
            1, 0, 0
        )

        exact_plan = _plan(connection, [_row()])
        assert exact_plan.ready and exact_plan.count("existing") == 1
        exact = persist_future_schedule(
            connection,
            plan=exact_plan,
            source_asset=str(FIXTURE),
            source_sha256=digest,
            retrieved_at=RETRIEVED_AT,
        )
        assert exact.nfl_ingestion_run_id is None
        assert exact.rows_skipped == 1

        changed_row = _row(gametime="20:25")
        update_plan = _plan(connection, [changed_row])
        assert update_plan.ready and update_plan.count("update") == 1
        updated = persist_future_schedule(
            connection,
            plan=update_plan,
            source_asset=str(FIXTURE),
            source_sha256=digest,
            retrieved_at=RETRIEVED_AT,
        )
        assert (updated.rows_inserted, updated.rows_updated) == (0, 1)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT nfl.status, nfl.season_type,
                       nfl.scheduled_start_time,
                       source.external_game_id,
                       observation.raw_payload->>'gametime'
                FROM nfl_games AS nfl
                JOIN game_sources AS source ON source.game_id = nfl.game_id
                JOIN nfl_game_source_observations AS observation
                  ON observation.game_id = nfl.game_id
                WHERE source.source_name = 'nflverse'
                  AND source.external_game_id = '2026_01_NE_SEA'
                ORDER BY observation.nfl_game_source_observation_id DESC
                LIMIT 1
                """
            )
            status, season_type, kickoff, external_id, provider_time = (
                cursor.fetchone()
            )
            assert status == "unplayed"
            assert season_type == "regular"
            assert kickoff.tzinfo is not None
            assert external_id == "2026_01_NE_SEA"
            assert provider_time == "20:25"

        conflicting_plan = _plan(
            connection,
            [changed_row | {"home_team": "NE", "away_team": "SEA"}],
        )
        assert not conflicting_plan.ready
        assert {issue.category for issue in conflicting_plan.issues} == {
            "source_identity_conflict"
        }
    finally:
        connection.close()


def test_existing_canonical_game_without_source_identity_blocks_duplicate(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT team_id FROM nfl_team_sources WHERE source_name='nflverse' AND external_team_id='4600'"
            )
            home_id = cursor.fetchone()[0]
            cursor.execute(
                "SELECT team_id FROM nfl_team_sources WHERE source_name='nflverse' AND external_team_id='3200'"
            )
            away_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO games (game_date, home_team_id, away_team_id)
                VALUES ('2026-09-10 00:20:00+00', %s, %s)
                RETURNING game_id
                """,
                (home_id, away_id),
            )
            game_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO nfl_games (
                    game_id, season, season_type, week, week_label,
                    scheduled_start_time, neutral_site, status
                ) VALUES (
                    %s, 2026, 'regular', 1, 'Regular Season',
                    '2026-09-10 00:20:00+00', FALSE, 'unplayed'
                )
                """,
                (game_id,),
            )
        connection.commit()

        plan = _plan(connection, [_row()])
        assert not plan.ready
        assert {issue.category for issue in plan.issues} == {
            "canonical_game_without_source_identity"
        }
    finally:
        connection.close()
