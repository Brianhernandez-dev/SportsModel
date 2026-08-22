import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest

from sportsmodel.ingest.odds_api_parser import parse_odds_api_h2h_response
from sportsmodel.ingest.odds_provenance import resolve_provider_sportsbook
from sportsmodel.nfl import manual_odds_capture as capture
from sportsmodel.nfl import manual_odds_capture_cli as cli
from sportsmodel.nfl.odds_identity import resolve_and_persist_nfl_odds_event


ROOT = Path(__file__).parents[2]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "odds_api"
    / "nfl_h2h_multi_event_response.json"
)
TARGET_DATE = datetime(2026, 9, 13, tzinfo=timezone.utc).date()


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _response(body=None) -> capture.NflProviderResponse:
    fixture = _fixture()
    return capture.NflProviderResponse(
        status_code=fixture["status_code"],
        headers=fixture["headers"],
        body=json.dumps(fixture["body"] if body is None else body),
    )


def _team_id(cursor, abbreviation: str) -> int:
    cursor.execute(
        "SELECT team_id FROM nfl_team_profiles WHERE current_abbreviation = %s",
        (abbreviation,),
    )
    return cursor.fetchone()[0]


def _insert_game(
    cursor,
    *,
    kickoff: datetime,
    home: str,
    away: str,
    week: int,
) -> int:
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
        VALUES (%s, 2026, 'regular', %s, %s, %s, FALSE, 'unplayed')
        """,
        (game_id, week, f"Week {week}", kickoff),
    )
    return game_id


def _insert_fixture_schedule(cursor) -> tuple[int, int]:
    mia_buf = _insert_game(
        cursor,
        kickoff=datetime(2026, 9, 13, 17, tzinfo=timezone.utc),
        home="MIA",
        away="BUF",
        week=1,
    )
    kc_den = _insert_game(
        cursor,
        kickoff=datetime(2026, 9, 13, 20, 25, tzinfo=timezone.utc),
        home="KC",
        away="DEN",
        week=1,
    )
    return mia_buf, kc_den


def test_mock_cli_persists_complete_auditable_capture_graph(
    initialized_nfl_test_database,
    monkeypatch,
    capsys,
) -> None:
    setup = psycopg2.connect(initialized_nfl_test_database)
    try:
        with setup.cursor() as cursor:
            expected_games = _insert_fixture_schedule(cursor)
        setup.commit()
    finally:
        setup.close()

    monkeypatch.setenv("SPORTSMODEL_TEST_DATABASE_URL", initialized_nfl_test_database)
    monkeypatch.setenv("SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert cli.main(
        [
            "--mock-fixture",
            str(FIXTURE),
            "--target-date",
            TARGET_DATE.isoformat(),
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "SportsModel NFL H2H Capture - MOCK" in output
    assert "Requests remaining: 487" in output
    assert "Requests used: 13" in output

    verification = psycopg2.connect(initialized_nfl_test_database)
    try:
        with verification.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    odds_ingestion_run_id,
                    sport,
                    source_name,
                    snapshot_role,
                    status,
                    request_regions,
                    request_markets,
                    request_odds_format,
                    status_code,
                    remaining_requests,
                    used_requests,
                    games_returned,
                    games_processed,
                    selections_inserted,
                    response_received_at IS NOT NULL
                FROM odds_ingestion_runs
                WHERE sport = 'americanfootball_nfl'
                """
            )
            run = cursor.fetchone()
            assert run[1:] == (
                "americanfootball_nfl",
                "odds_api",
                "entry",
                "completed",
                "us",
                "h2h",
                "american",
                200,
                487,
                13,
                2,
                2,
                8,
                True,
            )
            run_id = run[0]

            for table, expected, predicate in (
                (
                    "nfl_odds_provider_event_mappings",
                    2,
                    "provider_sport_key = 'americanfootball_nfl'",
                ),
                ("sportsbook_provider_identities", 2, "provider_name = 'odds_api'"),
                ("odds_provider_event_observations", 2, "odds_ingestion_run_id = %s"),
                ("odds_market_snapshots", 8, "odds_ingestion_run_id = %s"),
                ("nfl_official_pregame_evidence", 8, "odds_ingestion_run_id = %s"),
            ):
                parameters = (run_id,) if "%s" in predicate else ()
                cursor.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {predicate}",
                    parameters,
                )
                assert cursor.fetchone()[0] == expected

            cursor.execute(
                """
                SELECT DISTINCT game_id
                FROM nfl_official_pregame_evidence
                ORDER BY game_id
                """
            )
            assert tuple(row[0] for row in cursor.fetchall()) == tuple(
                sorted(expected_games)
            )
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM nfl_official_pregame_evidence AS evidence
                JOIN games AS game ON game.game_id = evidence.game_id
                WHERE evidence.trusted_observed_at
                        < evidence.canonical_kickoff_at_qualification
                  AND evidence.canonical_selection_team_id
                        IN (game.home_team_id, game.away_team_id)
                  AND evidence.odds_ingestion_run_id = %s
                """,
                (run_id,),
            )
            assert cursor.fetchone()[0] == 8
    finally:
        verification.close()


def test_duplicate_completed_capture_is_rejected_before_provider_call(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    calls = []
    try:
        with connection.cursor() as cursor:
            _insert_fixture_schedule(cursor)
        connection.commit()

        first = capture.execute_manual_nfl_capture(
            connection,
            target_date=TARGET_DATE,
            provider_call=lambda request: calls.append(request) or _response(),
        )
        assert first.games_processed == 2

        second_calls = []
        with pytest.raises(capture.DuplicateNflCaptureReservationError):
            capture.execute_manual_nfl_capture(
                connection,
                target_date=TARGET_DATE,
                provider_call=lambda request: second_calls.append(request) or _response(),
            )
        assert len(calls) == 1
        assert second_calls == []
    finally:
        connection.close()


@pytest.mark.parametrize(
    "failure_kind",
    ["unknown_team", "missing_game", "ambiguous_game", "kickoff_drift"],
)
def test_mapping_failures_are_auditable_and_create_no_invalid_evidence(
    initialized_nfl_test_database,
    failure_kind,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    body = _fixture()["body"]
    calls = []
    try:
        with connection.cursor() as cursor:
            if failure_kind == "missing_game":
                _insert_game(
                    cursor,
                    kickoff=datetime(2026, 9, 13, 20, 25, tzinfo=timezone.utc),
                    home="KC",
                    away="DEN",
                    week=1,
                )
            elif failure_kind == "ambiguous_game":
                _insert_fixture_schedule(cursor)
                _insert_game(
                    cursor,
                    kickoff=datetime(2026, 9, 13, 20, 25, tzinfo=timezone.utc),
                    home="KC",
                    away="DEN",
                    week=2,
                )
            elif failure_kind == "kickoff_drift":
                _insert_game(
                    cursor,
                    kickoff=datetime(2026, 9, 13, 17, 20, tzinfo=timezone.utc),
                    home="MIA",
                    away="BUF",
                    week=1,
                )
            else:
                _insert_fixture_schedule(cursor)
                body[0]["home_team"] = "Miami Football Team"
                for book in body[0]["bookmakers"]:
                    for outcome in book["markets"][0]["outcomes"]:
                        if outcome["name"] == "Miami Dolphins":
                            outcome["name"] = "Miami Football Team"
        connection.commit()

        with pytest.raises(capture.NflCaptureProcessingError, match="persistence"):
            capture.execute_manual_nfl_capture(
                connection,
                target_date=TARGET_DATE,
                provider_call=lambda request: calls.append(request) or _response(body),
            )
        assert len(calls) == 1

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, response_received_at IS NOT NULL, error_message
                FROM odds_ingestion_runs
                WHERE sport = 'americanfootball_nfl'
                """
            )
            status, observed, error_message = cursor.fetchone()
            assert status == "failed"
            assert observed is True
            assert "persistence" in error_message
            for table, predicate in (
                (
                    "nfl_odds_provider_event_mappings",
                    "provider_sport_key = 'americanfootball_nfl'",
                ),
                ("odds_provider_event_observations", "odds_ingestion_run_id = (SELECT odds_ingestion_run_id FROM odds_ingestion_runs WHERE sport = 'americanfootball_nfl')"),
                ("odds_market_snapshots", "odds_ingestion_run_id = (SELECT odds_ingestion_run_id FROM odds_ingestion_runs WHERE sport = 'americanfootball_nfl')"),
                ("nfl_official_pregame_evidence", "odds_ingestion_run_id = (SELECT odds_ingestion_run_id FROM odds_ingestion_runs WHERE sport = 'americanfootball_nfl')"),
            ):
                cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {predicate}")
                assert cursor.fetchone()[0] == 0
    finally:
        connection.close()


def test_conflicting_book_identity_rolls_back_raw_graph_without_retry(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    calls = []
    try:
        with connection.cursor() as cursor:
            _insert_fixture_schedule(cursor)
            resolve_provider_sportsbook(
                cursor,
                provider_name="odds_api",
                provider_bookmaker_key="conflicting_betmgm_key",
                bookmaker_title="BetMGM",
            )
        connection.commit()

        with pytest.raises(capture.NflCaptureProcessingError, match="persistence"):
            capture.execute_manual_nfl_capture(
                connection,
                target_date=TARGET_DATE,
                provider_call=lambda request: calls.append(request) or _response(),
            )
        assert len(calls) == 1

        with connection.cursor() as cursor:
            for table, predicate in (
                (
                    "nfl_odds_provider_event_mappings",
                    "provider_sport_key = 'americanfootball_nfl'",
                ),
                ("odds_provider_event_observations", "odds_ingestion_run_id = (SELECT odds_ingestion_run_id FROM odds_ingestion_runs WHERE sport = 'americanfootball_nfl')"),
                ("odds_market_snapshots", "odds_ingestion_run_id = (SELECT odds_ingestion_run_id FROM odds_ingestion_runs WHERE sport = 'americanfootball_nfl')"),
                ("nfl_official_pregame_evidence", "odds_ingestion_run_id = (SELECT odds_ingestion_run_id FROM odds_ingestion_runs WHERE sport = 'americanfootball_nfl')"),
            ):
                cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {predicate}")
                assert cursor.fetchone()[0] == 0
    finally:
        connection.close()


def test_conflicting_reused_provider_event_id_fails_without_retry(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    calls = []
    try:
        with connection.cursor() as cursor:
            _insert_fixture_schedule(cursor)
            events = parse_odds_api_h2h_response(
                _fixture()["body"],
                expected_sport_key=capture.NFL_SPORT_KEY,
            )
            conflicting_event = replace(events[1], event_id=events[0].event_id)
            resolve_and_persist_nfl_odds_event(cursor, conflicting_event)
        connection.commit()

        with pytest.raises(capture.NflCaptureProcessingError, match="persistence"):
            capture.execute_manual_nfl_capture(
                connection,
                target_date=TARGET_DATE,
                provider_call=lambda request: calls.append(request) or _response(),
            )
        assert len(calls) == 1

        with connection.cursor() as cursor:
            for table in (
                "odds_provider_event_observations",
                "odds_market_snapshots",
                "nfl_official_pregame_evidence",
            ):
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table}
                    WHERE odds_ingestion_run_id = (
                        SELECT odds_ingestion_run_id
                        FROM odds_ingestion_runs
                        WHERE sport = 'americanfootball_nfl'
                    )
                    """
                )
                assert cursor.fetchone()[0] == 0
    finally:
        connection.close()


def test_response_received_then_local_persistence_failure_is_terminal_and_auditable(
    initialized_nfl_test_database,
    monkeypatch,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    calls = []
    try:
        with connection.cursor() as cursor:
            _insert_fixture_schedule(cursor)
        connection.commit()
        monkeypatch.setattr(
            capture,
            "_persist_capture_payload",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("local persistence")),
        )

        with pytest.raises(capture.NflCaptureProcessingError, match="persistence"):
            capture.execute_manual_nfl_capture(
                connection,
                target_date=TARGET_DATE,
                provider_call=lambda request: calls.append(request) or _response(),
            )
        assert len(calls) == 1
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, response_received_at IS NOT NULL, error_message
                FROM odds_ingestion_runs
                WHERE sport = 'americanfootball_nfl'
                """
            )
            assert cursor.fetchone() == (
                "failed",
                True,
                "persistence: RuntimeError: local persistence",
            )
    finally:
        connection.close()


@pytest.mark.parametrize("offset_seconds", [0, 1])
def test_at_or_after_kickoff_raw_quotes_never_become_official(
    initialized_nfl_test_database,
    monkeypatch,
    offset_seconds,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    calls = []
    observed_at = datetime(2026, 9, 13, 17, tzinfo=timezone.utc) + timedelta(
        seconds=offset_seconds
    )
    def record_at_boundary(connection, **kwargs):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE odds_ingestion_runs
                SET response_received_at = %s,
                    status_code = %s,
                    remaining_requests = %s,
                    used_requests = %s
                WHERE odds_ingestion_run_id = %s
                RETURNING response_received_at
                """,
                (
                    observed_at,
                    kwargs["status_code"],
                    kwargs["remaining_requests"],
                    kwargs["used_requests"],
                    kwargs["ingestion_run_id"],
                ),
            )
            row = cursor.fetchone()
        connection.commit()
        return row[0]

    try:
        with connection.cursor() as cursor:
            _insert_fixture_schedule(cursor)
        connection.commit()
        monkeypatch.setattr(capture, "_record_response_once", record_at_boundary)

        audit = capture.execute_manual_nfl_capture(
            connection,
            target_date=TARGET_DATE,
            provider_call=lambda request: calls.append(request) or _response(),
        )
        assert len(calls) == 1
        assert audit.official_pregame_skipped == 4
        assert len(audit.official_pregame_evidence_ids) == 4
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM nfl_official_pregame_evidence AS evidence
                JOIN nfl_games AS nfl ON nfl.game_id = evidence.game_id
                WHERE evidence.trusted_observed_at >= nfl.scheduled_start_time
                """
            )
            assert cursor.fetchone()[0] == 0
    finally:
        connection.close()
