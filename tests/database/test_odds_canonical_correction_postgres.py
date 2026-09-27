from datetime import datetime, timezone
import os

import psycopg2
from psycopg2.errors import CheckViolation, RaiseException, UniqueViolation
import pytest

from sportsmodel.ingest.game_matching import get_or_create_canonical_game


pytestmark = pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)

EVENT_ID = "eb299a5d0d8335166d9e1e71c9f27482"
OBSERVED_AT = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
COMMENCE_TIME = datetime(2026, 9, 27, 19, 5, tzinfo=timezone.utc)
ORIGINAL_TIME = COMMENCE_TIME
CORRECTED_STALE_TIME = datetime(
    2026, 9, 26, 23, 15, tzinfo=timezone.utc
)
ORIGINAL_CORRECTED_TIME = datetime(
    2026, 9, 25, 17, 5, tzinfo=timezone.utc
)


def _insert_incident_graph(cursor) -> dict[str, int]:
    cursor.execute(
        "INSERT INTO teams(team_name) VALUES"
        "('Chicago Cubs'),('Boston Red Sox') RETURNING team_id"
    )
    away_team_id, home_team_id = (row[0] for row in cursor.fetchall())

    cursor.execute(
        "INSERT INTO games(game_date,home_team_id,away_team_id) VALUES"
        "(%s,%s,%s),(%s,%s,%s) RETURNING game_id",
        (
            CORRECTED_STALE_TIME,
            home_team_id,
            away_team_id,
            ORIGINAL_TIME,
            home_team_id,
            away_team_id,
        ),
    )
    corrected_game_id, original_game_id = (
        row[0] for row in cursor.fetchall()
    )

    cursor.execute(
        "INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES"
        "(%s,'mlb_stats','824705'),(%s,'mlb_stats','824703'),"
        "(%s,'odds_api',%s)",
        (corrected_game_id, original_game_id, original_game_id, EVENT_ID),
    )

    cursor.execute(
        """
        INSERT INTO odds_ingestion_runs (
            sport, source_name, started_at, completed_at, status,
            games_returned, games_processed, selections_inserted,
            selections_skipped, target_date, snapshot_role, status_code,
            remaining_requests, used_requests, request_path,
            request_regions, request_markets, request_odds_format,
            request_started_at, response_received_at
        ) VALUES (
            'baseball_mlb', 'odds_api', %s, %s, 'completed',
            1, 1, 12, 0, '2026-09-27', 'manual', 200, 100, 1,
            '/v4/sports/baseball_mlb/odds', 'us', 'h2h', 'american',
            %s, %s
        ) RETURNING odds_ingestion_run_id
        """,
        (OBSERVED_AT, OBSERVED_AT, OBSERVED_AT, OBSERVED_AT),
    )
    run_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO odds_provider_event_observations (
            odds_ingestion_run_id, source_name, provider_sport_key,
            external_event_id, provider_commence_time,
            provider_home_team_name, provider_away_team_name, observed_at
        ) VALUES (
            %s, 'odds_api', 'baseball_mlb', %s, %s,
            'Boston Red Sox', 'Chicago Cubs', %s
        ) RETURNING odds_provider_event_observation_id
        """,
        (run_id, EVENT_ID, COMMENCE_TIME, OBSERVED_AT),
    )
    observation_id = cursor.fetchone()[0]

    for index in range(12):
        cursor.execute(
            "INSERT INTO sportsbooks(name) VALUES(%s) RETURNING sportsbook_id",
            (f"Incident Book {index + 1}",),
        )
        sportsbook_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO sportsbook_provider_identities (
                provider_name, provider_bookmaker_key, sportsbook_id
            ) VALUES ('odds_api', %s, %s)
            RETURNING sportsbook_provider_identity_id
            """,
            (f"incident_book_{index + 1}", sportsbook_id),
        )
        provider_identity_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO odds_market_snapshots (
                game_id, sportsbook_id, market_type, selection_name,
                line_value, price, snapshot_time, source_name,
                odds_ingestion_run_id, odds_provider_event_observation_id,
                sportsbook_provider_identity_id,
                bookmaker_title_at_observation, bookmaker_updated_at,
                market_updated_at, observed_at
            ) VALUES (
                %s, %s, 'h2h', %s, NULL, %s, %s, 'odds_api',
                %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                original_game_id,
                sportsbook_id,
                "Boston Red Sox" if index % 2 == 0 else "Chicago Cubs",
                -110 + index,
                OBSERVED_AT,
                run_id,
                observation_id,
                provider_identity_id,
                f"Incident Book {index + 1}",
                OBSERVED_AT,
                OBSERVED_AT,
                OBSERVED_AT,
            ),
        )

    return {
        "away_team_id": away_team_id,
        "home_team_id": home_team_id,
        "corrected_game_id": corrected_game_id,
        "original_game_id": original_game_id,
        "run_id": run_id,
        "observation_id": observation_id,
    }


def _apply_future_correction_state(cursor, graph: dict[str, int]) -> None:
    cursor.execute(
        "UPDATE games SET game_date=%s WHERE game_id=%s",
        (COMMENCE_TIME, graph["corrected_game_id"]),
    )
    cursor.execute(
        "UPDATE games SET game_date=%s WHERE game_id=%s",
        (ORIGINAL_CORRECTED_TIME, graph["original_game_id"]),
    )
    cursor.execute(
        "UPDATE game_sources SET game_id=%s "
        "WHERE source_name='odds_api' AND external_game_id=%s",
        (graph["corrected_game_id"], EVENT_ID),
    )


def _insert_correction(cursor, graph: dict[str, int]) -> None:
    cursor.execute(
        """
        INSERT INTO odds_provider_event_canonical_corrections (
            odds_provider_event_observation_id,
            original_game_id,
            corrected_game_id,
            correction_reason,
            evidence_reference
        ) VALUES (%s,%s,%s,%s,%s)
        """,
        (
            graph["observation_id"],
            graph["original_game_id"],
            graph["corrected_game_id"],
            "Correct cross-contaminated canonical identity",
            "MLB gamePk 824705 and reviewed Sep27 incident package",
        ),
    )


def test_sep27_incident_correction_preserves_all_acquisition_evidence(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            graph = _insert_incident_graph(cursor)
            cursor.execute(
                "SELECT * FROM odds_market_snapshots "
                "WHERE odds_provider_event_observation_id=%s ORDER BY 1",
                (graph["observation_id"],),
            )
            raw_snapshots_before = cursor.fetchall()
            cursor.execute(
                "SELECT * FROM odds_provider_event_observations WHERE "
                "odds_provider_event_observation_id=%s",
                (graph["observation_id"],),
            )
            observation_before = cursor.fetchone()
            cursor.execute(
                "SELECT * FROM odds_ingestion_runs WHERE "
                "odds_ingestion_run_id=%s",
                (graph["run_id"],),
            )
            run_before = cursor.fetchone()

            _apply_future_correction_state(cursor, graph)
            _insert_correction(cursor, graph)

            cursor.execute(
                "SELECT * FROM odds_market_snapshots "
                "WHERE odds_provider_event_observation_id=%s ORDER BY 1",
                (graph["observation_id"],),
            )
            assert cursor.fetchall() == raw_snapshots_before
            assert len(raw_snapshots_before) == 12

            cursor.execute(
                """
                SELECT raw_acquisition_game_id, effective_game_id,
                       snapshot_time, observed_at
                FROM odds_market_snapshots_effective
                WHERE odds_provider_event_observation_id=%s
                ORDER BY odds_market_snapshot_id
                """,
                (graph["observation_id"],),
            )
            effective_rows = cursor.fetchall()
            assert effective_rows == [
                (
                    graph["original_game_id"],
                    graph["corrected_game_id"],
                    OBSERVED_AT,
                    OBSERVED_AT,
                )
            ] * 12
            assert OBSERVED_AT.hour == 13  # Sep27 06:00 America/Los_Angeles.

            cursor.execute(
                "SELECT * FROM odds_provider_event_observations WHERE "
                "odds_provider_event_observation_id=%s",
                (graph["observation_id"],),
            )
            assert cursor.fetchone() == observation_before
            cursor.execute(
                "SELECT * FROM odds_ingestion_runs WHERE "
                "odds_ingestion_run_id=%s",
                (graph["run_id"],),
            )
            assert cursor.fetchone() == run_before

            resolved_game_id = get_or_create_canonical_game(
                cursor,
                source_name="odds_api",
                external_game_id=EVENT_ID,
                game_datetime=COMMENCE_TIME,
                home_team_id=graph["home_team_id"],
                away_team_id=graph["away_team_id"],
            )
            assert resolved_game_id == graph["corrected_game_id"]
            cursor.execute(
                "SELECT COUNT(*) FROM odds_market_snapshots WHERE "
                "odds_provider_event_observation_id=%s",
                (graph["observation_id"],),
            )
            assert cursor.fetchone()[0] == 12
        connection.rollback()
    finally:
        connection.close()


def test_correction_insert_rejects_invalid_or_ambiguous_identity(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            graph = _insert_incident_graph(cursor)

            cursor.execute("SAVEPOINT original_equals_corrected")
            with pytest.raises(CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO odds_provider_event_canonical_corrections (
                        odds_provider_event_observation_id, original_game_id,
                        corrected_game_id, correction_reason, evidence_reference
                    ) VALUES (%s,%s,%s,'invalid','test')
                    """,
                    (
                        graph["observation_id"],
                        graph["original_game_id"],
                        graph["original_game_id"],
                    ),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT original_equals_corrected")

            _apply_future_correction_state(cursor, graph)

            cursor.execute("SAVEPOINT original_mismatch")
            with pytest.raises(RaiseException, match="covered raw snapshots"):
                cursor.execute(
                    """
                    INSERT INTO odds_provider_event_canonical_corrections (
                        odds_provider_event_observation_id, original_game_id,
                        corrected_game_id, correction_reason, evidence_reference
                    ) VALUES (%s,%s,%s,'invalid','test')
                    """,
                    (
                        graph["observation_id"],
                        graph["corrected_game_id"],
                        graph["original_game_id"],
                    ),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT original_mismatch")

            cursor.execute(
                "INSERT INTO games(game_date,home_team_id,away_team_id) "
                "VALUES(%s,%s,%s) RETURNING game_id",
                (
                    COMMENCE_TIME,
                    graph["away_team_id"],
                    graph["home_team_id"],
                ),
            )
            reversed_game_id = cursor.fetchone()[0]
            cursor.execute("SAVEPOINT reversed_orientation")
            with pytest.raises(RaiseException, match="corrected game"):
                cursor.execute(
                    """
                    INSERT INTO odds_provider_event_canonical_corrections (
                        odds_provider_event_observation_id, original_game_id,
                        corrected_game_id, correction_reason, evidence_reference
                    ) VALUES (%s,%s,%s,'invalid','test')
                    """,
                    (
                        graph["observation_id"],
                        graph["original_game_id"],
                        reversed_game_id,
                    ),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT reversed_orientation")

            cursor.execute("SAVEPOINT missing_observation")
            with pytest.raises(RaiseException, match="does not exist"):
                cursor.execute(
                    """
                    INSERT INTO odds_provider_event_canonical_corrections (
                        odds_provider_event_observation_id, original_game_id,
                        corrected_game_id, correction_reason, evidence_reference
                    ) VALUES (999999999,%s,%s,'invalid','test')
                    """,
                    (graph["original_game_id"], graph["corrected_game_id"]),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT missing_observation")

            cursor.execute(
                """
                INSERT INTO odds_provider_event_observations (
                    odds_ingestion_run_id, source_name, provider_sport_key,
                    external_event_id, provider_commence_time,
                    provider_home_team_name, provider_away_team_name, observed_at
                ) VALUES (%s,'odds_api','baseball_mlb','unrelated-event',%s,
                    'Boston Red Sox','Chicago Cubs',%s)
                RETURNING odds_provider_event_observation_id
                """,
                (graph["run_id"], COMMENCE_TIME, OBSERVED_AT),
            )
            unrelated_observation_id = cursor.fetchone()[0]
            cursor.execute("SAVEPOINT unrelated_event")
            with pytest.raises(RaiseException, match="no covered odds snapshots"):
                cursor.execute(
                    """
                    INSERT INTO odds_provider_event_canonical_corrections (
                        odds_provider_event_observation_id, original_game_id,
                        corrected_game_id, correction_reason, evidence_reference
                    ) VALUES (%s,%s,%s,'invalid','test')
                    """,
                    (
                        unrelated_observation_id,
                        graph["original_game_id"],
                        graph["corrected_game_id"],
                    ),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT unrelated_event")

            cursor.execute(
                "INSERT INTO games(game_date,home_team_id,away_team_id) "
                "VALUES(%s,%s,%s) RETURNING game_id",
                (
                    COMMENCE_TIME,
                    graph["home_team_id"],
                    graph["away_team_id"],
                ),
            )
            ambiguous_game_id = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO game_sources(game_id,source_name,external_game_id) "
                "VALUES(%s,'mlb_stats','ambiguous-game')",
                (ambiguous_game_id,),
            )
            cursor.execute("SAVEPOINT ambiguous_identity")
            with pytest.raises(RaiseException, match="not the unique nearby"):
                _insert_correction(cursor, graph)
            cursor.execute("ROLLBACK TO SAVEPOINT ambiguous_identity")
        connection.rollback()
    finally:
        connection.close()


def test_correction_is_singleton_and_immutable(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            graph = _insert_incident_graph(cursor)
            _apply_future_correction_state(cursor, graph)
            _insert_correction(cursor, graph)

            cursor.execute("SAVEPOINT second_correction")
            with pytest.raises(UniqueViolation):
                _insert_correction(cursor, graph)
            cursor.execute("ROLLBACK TO SAVEPOINT second_correction")

            cursor.execute("SAVEPOINT correction_update")
            with pytest.raises(RaiseException, match="immutable"):
                cursor.execute(
                    "UPDATE odds_provider_event_canonical_corrections "
                    "SET correction_reason='changed' WHERE "
                    "odds_provider_event_observation_id=%s",
                    (graph["observation_id"],),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT correction_update")

            cursor.execute("SAVEPOINT correction_delete")
            with pytest.raises(RaiseException, match="immutable"):
                cursor.execute(
                    "DELETE FROM odds_provider_event_canonical_corrections "
                    "WHERE odds_provider_event_observation_id=%s",
                    (graph["observation_id"],),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT correction_delete")
        connection.rollback()
    finally:
        connection.close()
