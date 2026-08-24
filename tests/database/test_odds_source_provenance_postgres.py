from datetime import date, datetime, timedelta, timezone

import psycopg2
from psycopg2.errors import ForeignKeyViolation, RaiseException, UniqueViolation
import pytest

from sportsmodel.ingest.odds_api import (
    create_ingestion_run,
    record_ingestion_response,
    save_market_selection,
)
from sportsmodel.ingest.odds_api_parser import (
    ODDS_API_MLB_SPORT_KEY,
    ODDS_API_NFL_SPORT_KEY,
    OddsApiEvent,
)
from sportsmodel.ingest.odds_provenance import (
    ProviderIdentityConflictError,
    create_provider_event_observation,
    resolve_provider_sportsbook,
)


OBSERVED_AT = datetime(
    2026,
    9,
    10,
    22,
    tzinfo=timezone.utc,
)
COMMENCE_TIME = datetime(
    2026,
    9,
    11,
    0,
    20,
    tzinfo=timezone.utc,
)


def _event(*, sport: str, event_id: str = "provider-event-1") -> OddsApiEvent:
    return OddsApiEvent(
        event_id=event_id,
        sport_key=sport,
        commence_time=COMMENCE_TIME,
        home_team="Provider Home",
        away_team="Provider Away",
        bookmakers=(),
    )


def _insert_provenance_run(cursor, *, sport: str) -> int:
    cursor.execute(
        """
        INSERT INTO odds_ingestion_runs (
            sport,
            source_name,
            snapshot_role,
            status,
            request_path,
            request_regions,
            request_markets,
            request_odds_format,
            request_started_at,
            response_received_at,
            status_code,
            remaining_requests,
            used_requests
        )
        VALUES (
            %s,
            'odds_api',
            'manual',
            'running',
            %s,
            'us',
            'h2h',
            'american',
            %s,
            %s,
            200,
            487,
            13
        )
        RETURNING odds_ingestion_run_id;
        """,
        (
            sport,
            f"/v4/sports/{sport}/odds",
            OBSERVED_AT - timedelta(seconds=1),
            OBSERVED_AT,
        ),
    )
    return cursor.fetchone()[0]


def _insert_game(cursor) -> int:
    cursor.execute(
        "INSERT INTO teams (team_name) VALUES ('Provider Away') "
        "RETURNING team_id;"
    )
    away_team_id = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO teams (team_name) VALUES ('Provider Home') "
        "RETURNING team_id;"
    )
    home_team_id = cursor.fetchone()[0]
    cursor.execute(
        """
        INSERT INTO games (game_date, home_team_id, away_team_id)
        VALUES (%s, %s, %s)
        RETURNING game_id;
        """,
        (COMMENCE_TIME, home_team_id, away_team_id),
    )
    return cursor.fetchone()[0]


def _persist_quote_graph(cursor) -> tuple[int, int, int, int]:
    run_id = _insert_provenance_run(
        cursor,
        sport=ODDS_API_MLB_SPORT_KEY,
    )
    event_observation_id = create_provider_event_observation(
        cursor,
        ingestion_run_id=run_id,
        provider_name="odds_api",
        event=_event(sport=ODDS_API_MLB_SPORT_KEY),
        observed_at=OBSERVED_AT,
    )
    identity = resolve_provider_sportsbook(
        cursor,
        provider_name="odds_api",
        provider_bookmaker_key="fanduel",
        bookmaker_title="FanDuel",
    )
    game_id = _insert_game(cursor)
    save_market_selection(
        cursor=cursor,
        ingestion_run_id=run_id,
        event_observation_id=event_observation_id,
        game_id=game_id,
        sportsbook_provider_identity_id=(
            identity.sportsbook_provider_identity_id
        ),
        sportsbook_id=identity.sportsbook_id,
        market_type="h2h",
        selection_name="Provider Home",
        line_value=None,
        price=-110,
        snapshot_time=OBSERVED_AT,
        bookmaker_title="FanDuel",
        bookmaker_updated_at=OBSERVED_AT - timedelta(seconds=2),
        market_updated_at=OBSERVED_AT - timedelta(seconds=3),
    )
    cursor.execute(
        "SELECT MAX(odds_market_snapshot_id) FROM odds_market_snapshots;"
    )
    snapshot_id = cursor.fetchone()[0]
    return (
        run_id,
        event_observation_id,
        identity.sportsbook_provider_identity_id,
        snapshot_id,
    )


def test_historical_mlb_evidence_remains_honestly_unknown(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    odds_provider_event_observation_id,
                    sportsbook_provider_identity_id,
                    bookmaker_title_at_observation,
                    bookmaker_updated_at,
                    market_updated_at,
                    observed_at
                FROM odds_market_snapshots
                WHERE selection_name = 'Legacy Home';
                """
            )
            assert cursor.fetchone() == (None, None, None, None, None, None)
            cursor.execute(
                """
                SELECT request_path, request_started_at, response_received_at
                FROM odds_ingestion_runs
                WHERE source_name = 'legacy_backfill';
                """
            )
            assert cursor.fetchone() == (None, None, None)
            cursor.execute(
                "SELECT sportsbook_id FROM sportsbooks "
                "WHERE name = 'Legacy Book';"
            )
            legacy_sportsbook_id = cursor.fetchone()[0]
            attached_identity = resolve_provider_sportsbook(
                cursor,
                provider_name="odds_api",
                provider_bookmaker_key="legacy_book",
                bookmaker_title="Legacy Book",
            )
            assert attached_identity.sportsbook_id == legacy_sportsbook_id
            cursor.execute(
                "SELECT sportsbook_id FROM odds_market_snapshots "
                "WHERE selection_name = 'Legacy Home';"
            )
            assert cursor.fetchone()[0] == legacy_sportsbook_id
        connection.commit()
    finally:
        connection.close()


def test_mlb_run_records_secret_free_request_and_response_context(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        run_id = create_ingestion_run(
            connection,
            target_date=date(2026, 8, 21),
            snapshot_role="manual",
        )
        response_time = record_ingestion_response(
            connection,
            ingestion_run_id=run_id,
            status_code=200,
            remaining_requests=487,
            used_requests=13,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    sport,
                    source_name,
                    request_path,
                    request_regions,
                    request_markets,
                    request_odds_format,
                    request_commence_time_from,
                    request_commence_time_to,
                    request_started_at,
                    response_received_at,
                    status_code,
                    remaining_requests,
                    used_requests
                FROM odds_ingestion_runs
                WHERE odds_ingestion_run_id = %s;
                """,
                (run_id,),
            )
            row = cursor.fetchone()

        assert row[:6] == (
            "baseball_mlb",
            "odds_api",
            "/v4/sports/baseball_mlb/odds",
            "us",
            "h2h",
            "american",
        )
        assert row[6] == datetime(2026, 8, 21, 7, tzinfo=timezone.utc)
        assert row[7] == datetime(
            2026,
            8,
            22,
            6,
            59,
            59,
            tzinfo=timezone.utc,
        )
        assert row[8] <= response_time == row[9]
        assert row[10:] == (200, 487, 13)
        assert "key" not in row[2].lower()
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("first_sport", "second_sport"),
    (
        (ODDS_API_MLB_SPORT_KEY, ODDS_API_NFL_SPORT_KEY),
        (ODDS_API_NFL_SPORT_KEY, ODDS_API_MLB_SPORT_KEY),
    ),
)
def test_provider_key_is_shared_across_sports_in_either_observation_order(
    initialized_nfl_test_database,
    first_sport: str,
    second_sport: str,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            first_run = _insert_provenance_run(
                cursor,
                sport=first_sport,
            )
            create_provider_event_observation(
                cursor,
                ingestion_run_id=first_run,
                provider_name="odds_api",
                event=_event(
                    sport=first_sport,
                    event_id="first-event",
                ),
                observed_at=OBSERVED_AT,
            )
            first = resolve_provider_sportsbook(
                cursor,
                provider_name="odds_api",
                provider_bookmaker_key="fanduel",
                bookmaker_title="FanDuel",
            )
            second_run = _insert_provenance_run(
                cursor,
                sport=second_sport,
            )
            create_provider_event_observation(
                cursor,
                ingestion_run_id=second_run,
                provider_name="odds_api",
                event=_event(
                    sport=second_sport,
                    event_id="second-event",
                ),
                observed_at=OBSERVED_AT,
            )
            renamed = resolve_provider_sportsbook(
                cursor,
                provider_name="odds_api",
                provider_bookmaker_key="fanduel",
                bookmaker_title="FanDuel Sportsbook",
            )
            cursor.execute(
                "SELECT COUNT(*) FROM sportsbook_provider_identities "
                "WHERE provider_name = 'odds_api' "
                "AND provider_bookmaker_key = 'fanduel';"
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT COUNT(*) FROM sportsbooks "
                "WHERE name = 'FanDuel Sportsbook';"
            )
            assert cursor.fetchone()[0] == 0
        connection.commit()

        assert first == renamed
    finally:
        connection.close()


def test_distinct_provider_keys_remain_distinct_provider_identities(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            fanduel = resolve_provider_sportsbook(
                cursor,
                provider_name="odds_api",
                provider_bookmaker_key="fanduel",
                bookmaker_title="FanDuel",
            )
            draftkings = resolve_provider_sportsbook(
                cursor,
                provider_name="odds_api",
                provider_bookmaker_key="draftkings",
                bookmaker_title="DraftKings",
            )
            cursor.execute(
                "SELECT COUNT(*) FROM sportsbook_provider_identities "
                "WHERE provider_name = 'odds_api' "
                "AND provider_bookmaker_key IN ('fanduel', 'draftkings');"
            )
            identity_count = cursor.fetchone()[0]
        connection.commit()

        assert fanduel.sportsbook_provider_identity_id != (
            draftkings.sportsbook_provider_identity_id
        )
        assert fanduel.sportsbook_id != draftkings.sportsbook_id
        assert identity_count == 2
    finally:
        connection.close()


def test_conflicting_provider_key_for_existing_book_fails_closed(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            resolve_provider_sportsbook(
                cursor,
                provider_name="odds_api",
                provider_bookmaker_key="fanduel",
                bookmaker_title="FanDuel",
            )
            with pytest.raises(
                ProviderIdentityConflictError,
                match="already mapped",
            ):
                resolve_provider_sportsbook(
                    cursor,
                    provider_name="odds_api",
                    provider_bookmaker_key="draftkings",
                    bookmaker_title="FanDuel",
                )
    finally:
        connection.rollback()
        connection.close()


def test_provider_event_sport_must_match_ingestion_run(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            run_id = _insert_provenance_run(
                cursor,
                sport=ODDS_API_MLB_SPORT_KEY,
            )
            with pytest.raises(ForeignKeyViolation):
                create_provider_event_observation(
                    cursor,
                    ingestion_run_id=run_id,
                    provider_name="odds_api",
                    event=_event(sport=ODDS_API_NFL_SPORT_KEY),
                    observed_at=OBSERVED_AT,
                )
        connection.rollback()
    finally:
        connection.close()


def test_new_source_graph_and_terminal_run_are_immutable(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            run_id, event_id, identity_id, snapshot_id = (
                _persist_quote_graph(cursor)
            )
        connection.commit()

        immutable_updates = (
            (
                "UPDATE sportsbook_provider_identities "
                "SET provider_bookmaker_key = 'changed' "
                "WHERE sportsbook_provider_identity_id = %s",
                identity_id,
            ),
            (
                "UPDATE odds_provider_event_observations "
                "SET external_event_id = 'changed' "
                "WHERE odds_provider_event_observation_id = %s",
                event_id,
            ),
            (
                "UPDATE odds_market_snapshots SET price = -120 "
                "WHERE odds_market_snapshot_id = %s",
                snapshot_id,
            ),
        )
        for query, row_id in immutable_updates:
            with pytest.raises(RaiseException):
                with connection.cursor() as cursor:
                    cursor.execute(query, (row_id,))
            connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE odds_ingestion_runs
                SET status = 'completed',
                    completed_at = CURRENT_TIMESTAMP,
                    games_returned = 1,
                    games_processed = 1,
                    selections_inserted = 1,
                    selections_skipped = 0
                WHERE odds_ingestion_run_id = %s;
                """,
                (run_id,),
            )
        connection.commit()

        with pytest.raises(RaiseException):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE odds_ingestion_runs SET games_processed = 2 "
                    "WHERE odds_ingestion_run_id = %s",
                    (run_id,),
                )
        connection.rollback()
    finally:
        connection.close()


def test_new_quote_source_graph_round_trips_exact_provider_facts(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            run_id, unused_event_id, unused_identity_id, snapshot_id = (
                _persist_quote_graph(cursor)
            )
            cursor.execute(
                """
                SELECT
                    run.source_name,
                    run.sport,
                    event.external_event_id,
                    event.provider_commence_time,
                    event.provider_home_team_name,
                    event.provider_away_team_name,
                    identity.provider_bookmaker_key,
                    snapshot.bookmaker_title_at_observation,
                    snapshot.bookmaker_updated_at,
                    snapshot.market_updated_at,
                    snapshot.observed_at,
                    snapshot.odds_ingestion_run_id
                FROM odds_market_snapshots AS snapshot
                JOIN odds_ingestion_runs AS run
                  ON run.odds_ingestion_run_id
                    = snapshot.odds_ingestion_run_id
                JOIN odds_provider_event_observations AS event
                  ON event.odds_provider_event_observation_id
                    = snapshot.odds_provider_event_observation_id
                JOIN sportsbook_provider_identities AS identity
                  ON identity.sportsbook_provider_identity_id
                    = snapshot.sportsbook_provider_identity_id
                WHERE snapshot.odds_market_snapshot_id = %s;
                """,
                (snapshot_id,),
            )
            row = cursor.fetchone()
        connection.commit()

        assert row == (
            "odds_api",
            ODDS_API_MLB_SPORT_KEY,
            "provider-event-1",
            COMMENCE_TIME,
            "Provider Home",
            "Provider Away",
            "fanduel",
            "FanDuel",
            OBSERVED_AT - timedelta(seconds=2),
            OBSERVED_AT - timedelta(seconds=3),
            OBSERVED_AT,
            run_id,
        )
    finally:
        connection.close()


def test_duplicate_quote_contract_in_one_observation_is_rejected(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            run_id, event_id, identity_id, unused_snapshot_id = (
                _persist_quote_graph(cursor)
            )
            cursor.execute(
                "SELECT sportsbook_id FROM sportsbook_provider_identities "
                "WHERE sportsbook_provider_identity_id = %s",
                (identity_id,),
            )
            sportsbook_id = cursor.fetchone()[0]
            cursor.execute(
                "SELECT game_id FROM odds_market_snapshots "
                "WHERE odds_ingestion_run_id = %s LIMIT 1",
                (run_id,),
            )
            game_id = cursor.fetchone()[0]
            with pytest.raises(UniqueViolation):
                save_market_selection(
                    cursor=cursor,
                    ingestion_run_id=run_id,
                    event_observation_id=event_id,
                    game_id=game_id,
                    sportsbook_provider_identity_id=identity_id,
                    sportsbook_id=sportsbook_id,
                    market_type="h2h",
                    selection_name="Provider Home",
                    line_value=None,
                    price=-105,
                    snapshot_time=OBSERVED_AT,
                    bookmaker_title="FanDuel",
                    bookmaker_updated_at=None,
                    market_updated_at=None,
                )
        connection.rollback()
    finally:
        connection.close()
