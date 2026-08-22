import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
from psycopg2.errors import RaiseException
import pytest

from sportsmodel.ingest.odds_api_parser import parse_odds_api_h2h_response
from sportsmodel.ingest.odds_provenance import (
    create_provider_event_observation,
    resolve_provider_sportsbook,
)
from sportsmodel.nfl.odds_identity import resolve_and_persist_nfl_odds_event
from sportsmodel.nfl.official_pregame_evidence import (
    IncompatibleNflEvidenceLinkageError,
    MissingNflEventMappingError,
    NflObservationNotPregameError,
    NflSelectionDoesNotBelongToGameError,
    create_official_nfl_pregame_evidence,
)


ROOT = Path(__file__).parents[2]
EVENT_FIXTURE = ROOT / "tests" / "fixtures" / "odds_api" / "nfl_h2h.json"
KICKOFF = datetime(2099, 9, 11, 0, 20, tzinfo=timezone.utc)


def _event(*, event_id="nfl-official-event", commence_time=KICKOFF):
    parsed = parse_odds_api_h2h_response(
        json.loads(EVENT_FIXTURE.read_text(encoding="utf-8")),
        expected_sport_key="americanfootball_nfl",
    )[0]
    return replace(parsed, event_id=event_id, commence_time=commence_time)


def _team_id(cursor, abbreviation: str) -> int:
    cursor.execute(
        "SELECT team_id FROM nfl_team_profiles WHERE current_abbreviation = %s",
        (abbreviation,),
    )
    return cursor.fetchone()[0]


def _insert_nfl_game(cursor, *, kickoff=KICKOFF, home="KC", away="DEN") -> int:
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
        VALUES (%s, 2099, 'regular', 1, 'Week 1', %s, FALSE, 'unplayed')
        """,
        (game_id, kickoff),
    )
    return game_id


def _insert_completed_run(cursor, *, observed_at: datetime) -> int:
    cursor.execute(
        """
        INSERT INTO odds_ingestion_runs (
            sport, source_name, snapshot_role, status, request_path,
            request_regions, request_markets, request_odds_format,
            request_started_at, response_received_at, status_code
        )
        VALUES (
            'americanfootball_nfl', 'odds_api', 'manual', 'running',
            '/v4/sports/americanfootball_nfl/odds',
            'us', 'h2h', 'american', %s, %s, 200
        )
        RETURNING odds_ingestion_run_id
        """,
        (observed_at - timedelta(seconds=1), observed_at),
    )
    return cursor.fetchone()[0]


def _finish_run(cursor, run_id: int) -> None:
    cursor.execute(
        """
        UPDATE odds_ingestion_runs
        SET status = 'completed',
            completed_at = CURRENT_TIMESTAMP,
            games_returned = 1,
            games_processed = 1,
            selections_inserted = 1,
            selections_skipped = 0
        WHERE odds_ingestion_run_id = %s
        """,
        (run_id,),
    )


def _insert_quote(
    cursor,
    *,
    game_id: int,
    mapping_id: int | None,
    observed_at: datetime,
    selection_name: str,
    event_id: str,
    commence_time: datetime = KICKOFF,
    snapshot_game_id: int | None = None,
    provider_update_time: datetime | None = None,
) -> int:
    run_id = _insert_completed_run(cursor, observed_at=observed_at)
    event = _event(event_id=event_id, commence_time=commence_time)
    event_observation_id = create_provider_event_observation(
        cursor,
        ingestion_run_id=run_id,
        provider_name="odds_api",
        event=event,
        observed_at=observed_at,
        nfl_provider_event_mapping_id=mapping_id,
    )
    book = resolve_provider_sportsbook(
        cursor,
        provider_name="odds_api",
        provider_bookmaker_key="betmgm",
        bookmaker_title="BetMGM",
    )
    cursor.execute(
        """
        INSERT INTO odds_market_snapshots (
            odds_ingestion_run_id,
            odds_provider_event_observation_id,
            game_id,
            sportsbook_provider_identity_id,
            sportsbook_id,
            market_type,
            selection_name,
            price,
            snapshot_time,
            source_name,
            bookmaker_title_at_observation,
            bookmaker_updated_at,
            market_updated_at,
            observed_at
        )
        VALUES (
            %s, %s, %s, %s, %s, 'h2h', %s, -145, %s,
            'odds_api', 'BetMGM', %s, %s, %s
        )
        RETURNING odds_market_snapshot_id
        """,
        (
            run_id,
            event_observation_id,
            snapshot_game_id or game_id,
            book.sportsbook_provider_identity_id,
            book.sportsbook_id,
            selection_name,
            observed_at,
            provider_update_time,
            provider_update_time,
            observed_at,
        ),
    )
    snapshot_id = cursor.fetchone()[0]
    _finish_run(cursor, run_id)
    return snapshot_id


def _build_quote(
    cursor,
    *,
    observed_at: datetime,
    selection_name="Kansas City Chiefs",
    commence_time=KICKOFF,
    with_mapping=True,
    snapshot_game_id=None,
    event_id="nfl-official-event",
    provider_update_time=None,
):
    game_id = _insert_nfl_game(cursor)
    event = _event(event_id=event_id, commence_time=commence_time)
    mapping = (
        resolve_and_persist_nfl_odds_event(cursor, event)
        if with_mapping
        else None
    )
    snapshot_id = _insert_quote(
        cursor,
        game_id=game_id,
        mapping_id=(mapping.provider_event_mapping_id if mapping else None),
        observed_at=observed_at,
        selection_name=selection_name,
        event_id=event_id,
        commence_time=commence_time,
        snapshot_game_id=snapshot_game_id,
        provider_update_time=provider_update_time,
    )
    return game_id, mapping, snapshot_id


@pytest.mark.parametrize(
    ("offset_seconds", "accepted"),
    [(-1, True), (0, False), (1, False)],
)
def test_database_enforces_strict_canonical_kickoff_boundary(
    initialized_nfl_test_database,
    offset_seconds,
    accepted,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            unused_game, unused_mapping, snapshot_id = _build_quote(
                cursor,
                observed_at=KICKOFF + timedelta(seconds=offset_seconds),
            )
            home_team_id = _team_id(cursor, "KC")
            if accepted:
                evidence = create_official_nfl_pregame_evidence(
                    cursor,
                    odds_market_snapshot_id=snapshot_id,
                    canonical_selection_team_id=home_team_id,
                )
                assert evidence.trusted_observed_at == KICKOFF - timedelta(seconds=1)
                assert evidence.canonical_kickoff_at_qualification == KICKOFF
            else:
                with pytest.raises(NflObservationNotPregameError):
                    create_official_nfl_pregame_evidence(
                        cursor,
                        odds_market_snapshot_id=snapshot_id,
                        canonical_selection_team_id=home_team_id,
                    )
                with pytest.raises(RaiseException, match="strictly before"):
                    cursor.execute(
                        """
                        INSERT INTO nfl_official_pregame_evidence (
                            odds_market_snapshot_id,
                            canonical_selection_team_id
                        ) VALUES (%s, %s)
                        """,
                        (snapshot_id, home_team_id),
                    )
        connection.rollback()
    finally:
        connection.close()


def test_provider_timestamps_cannot_admit_a_late_observation(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            unused_game, unused_mapping, snapshot_id = _build_quote(
                cursor,
                observed_at=KICKOFF + timedelta(seconds=1),
                commence_time=KICKOFF + timedelta(minutes=10),
                provider_update_time=KICKOFF - timedelta(hours=1),
            )
            with pytest.raises(NflObservationNotPregameError):
                create_official_nfl_pregame_evidence(
                    cursor,
                    odds_market_snapshot_id=snapshot_id,
                    canonical_selection_team_id=_team_id(cursor, "KC"),
                )
        connection.rollback()
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("selection_name", "abbreviation"),
    [("Kansas City Chiefs", "KC"), ("Denver Broncos", "DEN")],
)
def test_home_and_away_selection_identity_round_trip(
    initialized_nfl_test_database,
    selection_name,
    abbreviation,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            game_id, unused_mapping, snapshot_id = _build_quote(
                cursor,
                observed_at=KICKOFF - timedelta(minutes=1),
                selection_name=selection_name,
            )
            selection_team_id = _team_id(cursor, abbreviation)
            evidence = create_official_nfl_pregame_evidence(
                cursor,
                odds_market_snapshot_id=snapshot_id,
                canonical_selection_team_id=selection_team_id,
            )
            assert evidence.game_id == game_id
            assert evidence.canonical_selection_team_id == selection_team_id
            assert evidence.provider_selection_name == selection_name
        connection.rollback()
    finally:
        connection.close()


def test_database_rejects_wrong_selection_and_wrong_game(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            game_id = _insert_nfl_game(cursor)
            event = _event()
            mapping = resolve_and_persist_nfl_odds_event(cursor, event)
            wrong_game_id = _insert_nfl_game(
                cursor,
                home="BUF",
                away="MIA",
            )
            snapshot_id = _insert_quote(
                cursor,
                game_id=game_id,
                mapping_id=mapping.provider_event_mapping_id,
                observed_at=KICKOFF - timedelta(minutes=1),
                selection_name="Kansas City Chiefs",
                event_id=event.event_id,
                snapshot_game_id=wrong_game_id,
            )
            with pytest.raises(IncompatibleNflEvidenceLinkageError):
                create_official_nfl_pregame_evidence(
                    cursor,
                    odds_market_snapshot_id=snapshot_id,
                    canonical_selection_team_id=_team_id(cursor, "KC"),
                )
            with pytest.raises(RaiseException, match="canonical game linkage"):
                cursor.execute(
                    """
                    INSERT INTO nfl_official_pregame_evidence (
                        odds_market_snapshot_id, canonical_selection_team_id
                    ) VALUES (%s, %s)
                    """,
                    (snapshot_id, _team_id(cursor, "KC")),
                )
        connection.rollback()
    finally:
        connection.close()

    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            unused_game, unused_mapping, snapshot_id = _build_quote(
                cursor,
                observed_at=KICKOFF - timedelta(minutes=1),
            )
            wrong_team_id = _team_id(cursor, "BUF")
            with pytest.raises(NflSelectionDoesNotBelongToGameError):
                create_official_nfl_pregame_evidence(
                    cursor,
                    odds_market_snapshot_id=snapshot_id,
                    canonical_selection_team_id=wrong_team_id,
                )
            with pytest.raises(RaiseException, match="canonical selection"):
                cursor.execute(
                    """
                    INSERT INTO nfl_official_pregame_evidence (
                        odds_market_snapshot_id, canonical_selection_team_id
                    ) VALUES (%s, %s)
                    """,
                    (snapshot_id, wrong_team_id),
                )
        connection.rollback()
    finally:
        connection.close()


def test_missing_event_mapping_is_rejected(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            unused_game, unused_mapping, snapshot_id = _build_quote(
                cursor,
                observed_at=KICKOFF - timedelta(minutes=1),
                with_mapping=False,
            )
            with pytest.raises(MissingNflEventMappingError):
                create_official_nfl_pregame_evidence(
                    cursor,
                    odds_market_snapshot_id=snapshot_id,
                    canonical_selection_team_id=_team_id(cursor, "KC"),
                )
            with pytest.raises(RaiseException, match="canonical NFL event mapping"):
                cursor.execute(
                    """
                    INSERT INTO nfl_official_pregame_evidence (
                        odds_market_snapshot_id, canonical_selection_team_id
                    ) VALUES (%s, %s)
                    """,
                    (snapshot_id, _team_id(cursor, "KC")),
                )
        connection.rollback()
    finally:
        connection.close()


def test_official_evidence_is_immutable_and_later_quote_is_distinct(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            game_id = _insert_nfl_game(cursor)
            event = _event()
            mapping = resolve_and_persist_nfl_odds_event(cursor, event)
            first_snapshot = _insert_quote(
                cursor,
                game_id=game_id,
                mapping_id=mapping.provider_event_mapping_id,
                observed_at=KICKOFF - timedelta(minutes=2),
                selection_name="Kansas City Chiefs",
                event_id=event.event_id,
            )
            second_snapshot = _insert_quote(
                cursor,
                game_id=game_id,
                mapping_id=mapping.provider_event_mapping_id,
                observed_at=KICKOFF - timedelta(minutes=1),
                selection_name="Kansas City Chiefs",
                event_id=event.event_id,
            )
            home_team_id = _team_id(cursor, "KC")
            first = create_official_nfl_pregame_evidence(
                cursor,
                odds_market_snapshot_id=first_snapshot,
                canonical_selection_team_id=home_team_id,
            )
            replay = create_official_nfl_pregame_evidence(
                cursor,
                odds_market_snapshot_id=first_snapshot,
                canonical_selection_team_id=home_team_id,
            )
            second = create_official_nfl_pregame_evidence(
                cursor,
                odds_market_snapshot_id=second_snapshot,
                canonical_selection_team_id=home_team_id,
            )
            assert replay == first
            assert second.nfl_official_pregame_evidence_id != first.nfl_official_pregame_evidence_id
            assert second.trusted_observed_at > first.trusted_observed_at
        connection.commit()

        for statement in (
            "UPDATE nfl_official_pregame_evidence SET american_price = -150 ",
            "DELETE FROM nfl_official_pregame_evidence ",
        ):
            with pytest.raises(RaiseException, match="immutable"):
                with connection.cursor() as cursor:
                    cursor.execute(
                        statement + "WHERE nfl_official_pregame_evidence_id = %s",
                        (first.nfl_official_pregame_evidence_id,),
                    )
            connection.rollback()
    finally:
        connection.close()


def test_current_kickoff_is_snapshotted_and_later_change_does_not_rewrite_it(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    changed_before = KICKOFF - timedelta(minutes=5)
    changed_after = KICKOFF + timedelta(hours=1)
    try:
        with connection.cursor() as cursor:
            game_id, unused_mapping, snapshot_id = _build_quote(
                cursor,
                observed_at=KICKOFF - timedelta(minutes=10),
            )
            cursor.execute(
                "UPDATE nfl_games SET scheduled_start_time = %s WHERE game_id = %s",
                (changed_before, game_id),
            )
            evidence = create_official_nfl_pregame_evidence(
                cursor,
                odds_market_snapshot_id=snapshot_id,
                canonical_selection_team_id=_team_id(cursor, "KC"),
            )
            assert evidence.canonical_kickoff_at_qualification == changed_before
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE nfl_games SET scheduled_start_time = %s WHERE game_id = %s",
                (changed_after, game_id),
            )
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT canonical_kickoff_at_qualification
                FROM nfl_official_pregame_evidence
                WHERE nfl_official_pregame_evidence_id = %s
                """,
                (evidence.nfl_official_pregame_evidence_id,),
            )
            assert cursor.fetchone()[0] == changed_before
    finally:
        connection.close()
