import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
from psycopg2.errors import ForeignKeyViolation, RaiseException
import pytest

from sportsmodel.ingest.odds_api_parser import parse_odds_api_h2h_response
from sportsmodel.ingest.odds_provenance import create_provider_event_observation
from sportsmodel.nfl.odds_identity import (
    CanonicalNflGameNotFoundError,
    NflProviderEventConflictError,
    resolve_and_persist_nfl_odds_event,
    resolve_nfl_odds_event,
)


ROOT = Path(__file__).parents[2]
EVENT_FIXTURE = ROOT / "tests" / "fixtures" / "odds_api" / "nfl_h2h.json"
TEAM_FIXTURE = ROOT / "tests" / "fixtures" / "odds_api" / "nfl_team_identities.json"
OBSERVED_AT = datetime(2026, 9, 10, 22, tzinfo=timezone.utc)


def _event():
    return parse_odds_api_h2h_response(
        json.loads(EVENT_FIXTURE.read_text(encoding="utf-8")),
        expected_sport_key="americanfootball_nfl",
    )[0]


def _team_id(cursor, abbreviation: str) -> int:
    cursor.execute(
        "SELECT team_id FROM nfl_team_profiles WHERE current_abbreviation = %s",
        (abbreviation,),
    )
    return cursor.fetchone()[0]


def _insert_nfl_game(cursor, *, kickoff=None, home="KC", away="DEN") -> int:
    kickoff = kickoff or _event().commence_time
    home_team_id = _team_id(cursor, home)
    away_team_id = _team_id(cursor, away)
    cursor.execute(
        """
        INSERT INTO games (game_date, home_team_id, away_team_id)
        VALUES (%s, %s, %s)
        RETURNING game_id
        """,
        (kickoff, home_team_id, away_team_id),
    )
    game_id = cursor.fetchone()[0]
    cursor.execute(
        """
        INSERT INTO nfl_games (
            game_id, season, season_type, week, week_label,
            scheduled_start_time, neutral_site, status
        )
        VALUES (%s, 2026, 'regular', 1, 'Week 1', %s, FALSE, 'unplayed')
        """,
        (game_id, kickoff),
    )
    return game_id


def _insert_run(cursor, *, sport="americanfootball_nfl") -> int:
    cursor.execute(
        """
        INSERT INTO odds_ingestion_runs (
            sport, source_name, snapshot_role, status, request_path,
            request_regions, request_markets, request_odds_format,
            request_started_at, response_received_at, status_code
        )
        VALUES (
            %s, 'odds_api', 'manual', 'running', %s,
            'us', 'h2h', 'american', %s, %s, 200
        )
        RETURNING odds_ingestion_run_id
        """,
        (
            sport,
            f"/v4/sports/{sport}/odds",
            OBSERVED_AT - timedelta(seconds=1),
            OBSERVED_AT,
        ),
    )
    return cursor.fetchone()[0]


def test_all_32_odds_api_team_identities_resolve_to_active_canonical_teams(
    initialized_nfl_test_database,
) -> None:
    expected = {
        item["provider_team_name"]: item["abbreviation"]
        for item in json.loads(TEAM_FIXTURE.read_text(encoding="utf-8"))
    }
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT source.external_team_id, profile.current_abbreviation
                FROM nfl_team_sources AS source
                JOIN nfl_team_profiles AS profile ON profile.team_id = source.team_id
                WHERE source.source_name = 'odds_api'
                  AND profile.is_active IS TRUE
                """
            )
            actual = dict(cursor.fetchall())
        assert actual == expected

        with pytest.raises(RaiseException, match="immutable"):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO nfl_team_sources (
                        team_id, source_name, external_team_id, source_team_name
                    )
                    VALUES (%s, 'odds_api', 'Kansas City', 'Kansas City')
                    """,
                    (_team_id(cursor, "KC"),),
                )
        connection.rollback()
    finally:
        connection.close()


def test_provider_event_mapping_is_existing_only_idempotent_and_retains_reissues(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            before = None
            cursor.execute("SELECT COUNT(*) FROM nfl_games")
            before = cursor.fetchone()[0]
            with pytest.raises(CanonicalNflGameNotFoundError):
                resolve_nfl_odds_event(cursor, _event())
            cursor.execute("SELECT COUNT(*) FROM nfl_games")
            assert cursor.fetchone()[0] == before

            game_id = _insert_nfl_game(cursor)
            first = resolve_and_persist_nfl_odds_event(cursor, _event())
            replay = resolve_and_persist_nfl_odds_event(cursor, _event())
            reissue = resolve_and_persist_nfl_odds_event(
                cursor,
                replace(_event(), event_id="nfl-event-reissue"),
            )

            assert first.game_id == game_id
            assert replay.provider_event_mapping_id == first.provider_event_mapping_id
            assert reissue.game_id == game_id
            assert reissue.provider_event_mapping_id != first.provider_event_mapping_id
            cursor.execute(
                "SELECT COUNT(*) FROM nfl_odds_provider_event_mappings WHERE game_id = %s",
                (game_id,),
            )
            assert cursor.fetchone()[0] == 2

            with pytest.raises(NflProviderEventConflictError):
                resolve_nfl_odds_event(
                    cursor,
                    replace(
                        _event(),
                        home_team="Denver Broncos",
                        away_team="Kansas City Chiefs",
                    ),
                )
        connection.rollback()
    finally:
        connection.close()


def test_nfl_mapping_links_only_coherent_nfl_run_event_and_game(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            game_id = _insert_nfl_game(cursor)
            mapping = resolve_and_persist_nfl_odds_event(cursor, _event())
            run_id = _insert_run(cursor)
            observation_id = create_provider_event_observation(
                cursor,
                ingestion_run_id=run_id,
                provider_name="odds_api",
                event=_event(),
                observed_at=OBSERVED_AT,
                nfl_provider_event_mapping_id=mapping.provider_event_mapping_id,
            )
            cursor.execute(
                """
                SELECT mapping.game_id, event.provider_sport_key
                FROM odds_provider_event_observations AS event
                JOIN nfl_odds_provider_event_mappings AS mapping
                  ON mapping.nfl_odds_provider_event_mapping_id
                    = event.nfl_odds_provider_event_mapping_id
                WHERE event.odds_provider_event_observation_id = %s
                """,
                (observation_id,),
            )
            assert cursor.fetchone() == (game_id, "americanfootball_nfl")
        connection.commit()

        with connection.cursor() as cursor:
            mlb_run_id = _insert_run(cursor, sport="baseball_mlb")
            with pytest.raises(ForeignKeyViolation):
                create_provider_event_observation(
                    cursor,
                    ingestion_run_id=mlb_run_id,
                    provider_name="odds_api",
                    event=_event(),
                    observed_at=OBSERVED_AT,
                    nfl_provider_event_mapping_id=mapping.provider_event_mapping_id,
                )
        connection.rollback()
    finally:
        connection.close()


def test_database_rejects_mlb_game_reversed_teams_and_mapping_mutation(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            game_id = _insert_nfl_game(cursor)
            mapping = resolve_and_persist_nfl_odds_event(cursor, _event())
        connection.commit()

        with pytest.raises(ForeignKeyViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO nfl_odds_provider_event_mappings (
                        provider_name, provider_sport_key, external_event_id,
                        game_id, canonical_home_team_id, canonical_away_team_id,
                        provider_home_team_name, provider_away_team_name,
                        canonical_kickoff, first_provider_commence_time
                    )
                    SELECT 'odds_api', 'americanfootball_nfl', 'reversed',
                           %s, away_team_id, home_team_id,
                           'Denver Broncos', 'Kansas City Chiefs', %s, %s
                    FROM games WHERE game_id = %s
                    """,
                    (game_id, _event().commence_time, _event().commence_time, game_id),
                )
        connection.rollback()

        with pytest.raises(ForeignKeyViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO nfl_odds_provider_event_mappings (
                        provider_name, provider_sport_key, external_event_id,
                        game_id, canonical_home_team_id, canonical_away_team_id,
                        provider_home_team_name, provider_away_team_name,
                        canonical_kickoff, first_provider_commence_time
                    )
                    SELECT 'odds_api', 'americanfootball_nfl', 'wrong-name',
                           %s, home_team_id, away_team_id,
                           'Kansas City', 'Denver Broncos', %s, %s
                    FROM games WHERE game_id = %s
                    """,
                    (game_id, _event().commence_time, _event().commence_time, game_id),
                )
        connection.rollback()

        with pytest.raises(ForeignKeyViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE games
                    SET home_team_id = away_team_id,
                        away_team_id = home_team_id
                    WHERE game_id = %s
                    """,
                    (game_id,),
                )
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO teams (team_name) VALUES ('MLB Provider Home') RETURNING team_id"
            )
            mlb_home = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO teams (team_name) VALUES ('MLB Provider Away') RETURNING team_id"
            )
            mlb_away = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO games (game_date, home_team_id, away_team_id)
                VALUES (%s, %s, %s) RETURNING game_id
                """,
                (_event().commence_time, mlb_home, mlb_away),
            )
            mlb_game_id = cursor.fetchone()[0]
            with pytest.raises(ForeignKeyViolation):
                cursor.execute(
                    """
                    INSERT INTO nfl_odds_provider_event_mappings (
                        provider_name, provider_sport_key, external_event_id,
                        game_id, canonical_home_team_id, canonical_away_team_id,
                        provider_home_team_name, provider_away_team_name,
                        canonical_kickoff, first_provider_commence_time
                    ) VALUES (
                        'odds_api', 'americanfootball_nfl', 'mlb-game',
                        %s, %s, %s, 'MLB Provider Home', 'MLB Provider Away', %s, %s
                    )
                    """,
                    (
                        mlb_game_id,
                        mlb_home,
                        mlb_away,
                        _event().commence_time,
                        _event().commence_time,
                    ),
                )
        connection.rollback()

        with pytest.raises(RaiseException, match="immutable"):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE nfl_odds_provider_event_mappings SET external_event_id = 'moved' "
                    "WHERE nfl_odds_provider_event_mapping_id = %s",
                    (mapping.provider_event_mapping_id,),
                )
        connection.rollback()

        with pytest.raises(RaiseException, match="immutable"):
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM nfl_odds_provider_event_mappings "
                    "WHERE nfl_odds_provider_event_mapping_id = %s",
                    (mapping.provider_event_mapping_id,),
                )
        connection.rollback()
    finally:
        connection.close()
