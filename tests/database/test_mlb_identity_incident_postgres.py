import os
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

from sportsmodel.database.boxscore_repository import save_parsed_boxscore
from sportsmodel.database.moneyline_daily_workflow_repository import (
    load_moneyline_daily_official_evidence_counts,
)
from sportsmodel.ingest.game_matching import (
    CanonicalGameIdentityConflictError,
    get_or_create_canonical_game,
)
from sportsmodel.ingest.mlb_stats import fetch_historical_results
from sportsmodel.models.parsed_boxscore import ParsedBoxScore
from sportsmodel.models.player_game_pitching_statistics import (
    PlayerGamePitchingStatistics,
)
from sportsmodel.models.team_game_statistics import TeamGameStatistics


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_mlb_cross_source_identity_is_schedule_drift_and_doubleheader_safe(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        home_team_id, away_team_id = _create_teams(connection, "Single")
        scheduled_time = datetime(
            2026, 9, 14, 23, 30, tzinfo=timezone.utc
        )
        canonical_game_id = _create_game_with_source(
            connection,
            game_datetime=scheduled_time,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            source_name="mlb_stats",
            external_game_id="900001",
        )

        with connection.cursor() as cursor:
            matched_game_id = get_or_create_canonical_game(
                cursor,
                source_name="odds_api",
                external_game_id="single-event",
                game_datetime=scheduled_time + timedelta(hours=2),
                home_team_id=home_team_id,
                away_team_id=away_team_id,
            )
        connection.commit()

        assert matched_game_id == canonical_game_id

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT game_id FROM game_sources "
                "WHERE source_name = 'odds_api' "
                "AND external_game_id = 'single-event';"
            )
            assert cursor.fetchone() == (canonical_game_id,)

        double_home_id, double_away_id = _create_teams(
            connection, "Double"
        )
        _create_game_with_source(
            connection,
            game_datetime=scheduled_time,
            home_team_id=double_home_id,
            away_team_id=double_away_id,
            source_name="mlb_stats",
            external_game_id="900002",
        )
        _create_game_with_source(
            connection,
            game_datetime=scheduled_time + timedelta(hours=4),
            home_team_id=double_home_id,
            away_team_id=double_away_id,
            source_name="mlb_stats",
            external_game_id="900003",
        )

        with connection.cursor() as cursor:
            with pytest.raises(
                CanonicalGameIdentityConflictError,
                match="doubleheader or schedule identity is ambiguous",
            ):
                get_or_create_canonical_game(
                    cursor,
                    source_name="odds_api",
                    external_game_id="ambiguous-event",
                    game_datetime=scheduled_time + timedelta(hours=6),
                    home_team_id=double_home_id,
                    away_team_id=double_away_id,
                )
        connection.rollback()

        stale_home_id, stale_away_id = _create_teams(connection, "Stale")
        authoritative_game_id = _create_game_with_source(
            connection,
            game_datetime=scheduled_time,
            home_team_id=stale_home_id,
            away_team_id=stale_away_id,
            source_name="mlb_stats",
            external_game_id="900004",
        )
        stale_game_id = _create_game_with_source(
            connection,
            game_datetime=scheduled_time + timedelta(minutes=1),
            home_team_id=stale_home_id,
            away_team_id=stale_away_id,
            source_name="odds_api",
            external_game_id="stale-event",
        )

        with connection.cursor() as cursor:
            with pytest.raises(
                CanonicalGameIdentityConflictError,
                match=(
                    f"maps to {stale_game_id}, "
                    f"candidate={authoritative_game_id}"
                ),
            ):
                get_or_create_canonical_game(
                    cursor,
                    source_name="odds_api",
                    external_game_id="stale-event",
                    game_datetime=scheduled_time + timedelta(minutes=1),
                    home_team_id=stale_home_id,
                    away_team_id=stale_away_id,
                )
        connection.rollback()
    finally:
        connection.close()


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_authoritative_mlb_result_ingestion_preserves_retained_odds_split(
    initialized_nfl_test_database,
) -> None:
    database_url = initialized_nfl_test_database
    connection = psycopg2.connect(database_url)
    try:
        home_team_id, away_team_id = _create_teams(connection, "Result")
        game_datetime = datetime(
            2026, 7, 12, 17, 0, tzinfo=timezone.utc
        )
        mlb_game_id = 900101
        authoritative_game_id = _create_game_with_source(
            connection,
            game_datetime=game_datetime,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            source_name="mlb_stats",
            external_game_id=str(mlb_game_id),
        )
        retained_odds_game_id = _create_game_with_source(
            connection,
            game_datetime=game_datetime + timedelta(minutes=1),
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            source_name="odds_api",
            external_game_id="retained-odds-event",
        )
        player_ids = _create_players(connection)
        evidence_ids = _create_failed_card_evidence(
            connection,
            target_date=date(2026, 7, 12),
        )
        before_evidence = _load_failed_card_evidence(
            connection,
            **evidence_ids,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT game_date, home_team_id, away_team_id, "
                "scheduled_innings, doubleheader_status, game_number "
                "FROM games WHERE game_id = %s;",
                (retained_odds_game_id,),
            )
            retained_odds_game_before = cursor.fetchone()

        schedule = {
            "dates": [
                {
                    "games": [
                        {
                            "gamePk": mlb_game_id,
                            "gameType": "R",
                            "gameDate": game_datetime.isoformat(),
                            "status": {
                                "detailedState": "Final",
                                "abstractGameState": "Final",
                            },
                            "teams": {
                                "home": {
                                    "team": {"name": "Result Home"},
                                    "score": 5,
                                },
                                "away": {
                                    "team": {"name": "Result Away"},
                                    "score": 3,
                                },
                            },
                        }
                    ]
                }
            ]
        }

        def resolve_team(cursor, team_name):
            return (
                home_team_id
                if team_name == "Result Home"
                else away_team_id
            )

        def persist_boxscore(*, game_id, game_pk):
            save_parsed_boxscore(
                _build_parsed_boxscore(
                    game_id=game_id,
                    game_pk=game_pk,
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                    player_ids=player_ids,
                ),
                connection_factory=lambda: psycopg2.connect(database_url),
            )

        summaries = []
        for _ in range(2):
            summaries.append(
                fetch_historical_results(
                    start_date=date(2026, 7, 12),
                    end_date=date(2026, 7, 12),
                    progress_callback=None,
                    schedule_fetcher=lambda _: schedule,
                    connection_factory=lambda: psycopg2.connect(database_url),
                    team_id_resolver=resolve_team,
                    complete_game_ids_getter=lambda _: frozenset(),
                    boxscore_ingestor=persist_boxscore,
                )
            )

        assert all(summary.dates_failed == 0 for summary in summaries)
        assert all(summary.games_processed == 1 for summary in summaries)
        assert all(summary.boxscores_processed == 1 for summary in summaries)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT game_id FROM historical_games WHERE mlb_game_id = %s;",
                (mlb_game_id,),
            )
            assert cursor.fetchone() == (authoritative_game_id,)
            cursor.execute(
                "SELECT COUNT(*) FROM team_game_statistics "
                "WHERE game_id = %s;",
                (authoritative_game_id,),
            )
            assert cursor.fetchone() == (2,)
            cursor.execute(
                "SELECT COUNT(*) FROM player_game_pitching_statistics "
                "WHERE game_id = %s;",
                (authoritative_game_id,),
            )
            assert cursor.fetchone() == (2,)
            cursor.execute(
                "SELECT source_name, external_game_id FROM game_sources "
                "WHERE game_id = %s;",
                (retained_odds_game_id,),
            )
            assert cursor.fetchall() == [
                ("odds_api", "retained-odds-event")
            ]
            cursor.execute(
                "SELECT COUNT(*) FROM historical_games "
                "WHERE game_id = %s;",
                (retained_odds_game_id,),
            )
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "SELECT game_date, home_team_id, away_team_id, "
                "scheduled_innings, doubleheader_status, game_number "
                "FROM games WHERE game_id = %s;",
                (retained_odds_game_id,),
            )
            assert cursor.fetchone() == retained_odds_game_before

        after_evidence = _load_failed_card_evidence(
            connection,
            **evidence_ids,
        )
        assert after_evidence == before_evidence
    finally:
        connection.close()


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_failed_evaluation_evidence_counts_require_exact_linkage(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO moneyline_prediction_runs (
                    target_date, model_version, feature_schema_version,
                    model_artifact_sha256, started_at, completed_at,
                    status, games_received, predictions_created,
                    games_skipped, run_type
                ) VALUES (
                    %s, 'model', 'schema', %s,
                    clock_timestamp(), clock_timestamp(),
                    'completed', 15, 15, 0, 'official'
                ) RETURNING moneyline_prediction_run_id;
                """,
                (date(2026, 9, 13), "a" * 64),
            )
            prediction_run_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO odds_ingestion_runs (
                    sport, source_name, started_at, completed_at, status,
                    games_returned, games_processed, selections_inserted,
                    selections_skipped, target_date, snapshot_role,
                    status_code, remaining_requests, used_requests
                ) VALUES (
                    'baseball_mlb', 'odds_api', clock_timestamp(),
                    clock_timestamp(), 'completed', 15, 15, 270, 0,
                    %s, 'entry', 200, 425, 75
                ) RETURNING odds_ingestion_run_id;
                """,
                (date(2026, 9, 13),),
            )
            odds_run_id = cursor.fetchone()[0]
        connection.commit()

        with connection.cursor() as cursor:
            counts = load_moneyline_daily_official_evidence_counts(
                cursor,
                target_date=date(2026, 9, 13),
                sport="baseball_mlb",
                prediction_run_id=prediction_run_id,
                odds_ingestion_run_id=odds_run_id,
            )

        assert counts.prediction_runs == 1
        assert counts.entry_odds_runs == 1
        assert counts.linked_prediction_runs == 1
        assert counts.linked_entry_odds_runs == 1
        assert counts.prediction_rows == 0
        assert counts.failed_unlinked_empty_prediction_runs == 0
        assert counts.market_evaluations == 0
        assert counts.paper_candidates == 0
        assert counts.settlements == 0
    finally:
        connection.close()


@pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)
def test_failed_empty_official_run_is_counted_without_preview_run(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    target_date = date(2026, 9, 22)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO moneyline_prediction_runs (
                    target_date, model_version, feature_schema_version,
                    model_artifact_sha256, completed_at, status,
                    games_received, predictions_created, games_skipped,
                    run_type
                ) VALUES
                    (
                        %s, 'model', 'schema', %s, clock_timestamp(),
                        'failed', 16, 0, 0, 'official'
                    ),
                    (
                        %s, 'model', 'schema', %s, clock_timestamp(),
                        'completed', 16, 16, 0, 'preview'
                    );
                """,
                (target_date, "c" * 64, target_date, "d" * 64),
            )
        connection.commit()

        with connection.cursor() as cursor:
            counts = load_moneyline_daily_official_evidence_counts(
                cursor,
                target_date=target_date,
                sport="baseball_mlb",
                prediction_run_id=None,
                odds_ingestion_run_id=None,
            )

        assert counts.prediction_runs == 1
        assert counts.prediction_rows == 0
        assert counts.failed_unlinked_empty_prediction_runs == 1
        assert counts.entry_odds_runs == 0
        assert counts.linked_prediction_runs == 0
        assert counts.linked_entry_odds_runs == 0
        assert counts.market_evaluations == 0
        assert counts.paper_candidates == 0
        assert counts.settlements == 0
    finally:
        connection.close()


def _create_teams(connection, label: str) -> tuple[int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO teams (team_name) VALUES (%s) RETURNING team_id;",
            (f"{label} Home",),
        )
        home_team_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO teams (team_name) VALUES (%s) RETURNING team_id;",
            (f"{label} Away",),
        )
        away_team_id = cursor.fetchone()[0]
    connection.commit()
    return home_team_id, away_team_id


def _create_game_with_source(
    connection,
    *,
    game_datetime: datetime,
    home_team_id: int,
    away_team_id: int,
    source_name: str,
    external_game_id: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO games (game_date, home_team_id, away_team_id)
            VALUES (%s, %s, %s) RETURNING game_id;
            """,
            (game_datetime, home_team_id, away_team_id),
        )
        game_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO game_sources (
                game_id, source_name, external_game_id
            ) VALUES (%s, %s, %s);
            """,
            (game_id, source_name, external_game_id),
        )
    connection.commit()
    return game_id


def _create_players(connection) -> tuple[int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO baseball_players (full_name) "
            "VALUES ('Result Home Starter') RETURNING baseball_player_id;"
        )
        home_player_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO baseball_players (full_name) "
            "VALUES ('Result Away Starter') RETURNING baseball_player_id;"
        )
        away_player_id = cursor.fetchone()[0]
    connection.commit()
    return home_player_id, away_player_id


def _create_failed_card_evidence(
    connection,
    *,
    target_date: date,
) -> dict[str, int | date]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO moneyline_prediction_runs (
                target_date, model_version, feature_schema_version,
                model_artifact_sha256, completed_at, status,
                games_received, predictions_created, games_skipped, run_type
            ) VALUES (
                %s, 'model', 'schema', %s, clock_timestamp(), 'completed',
                1, 1, 0, 'official'
            ) RETURNING moneyline_prediction_run_id;
            """,
            (target_date, "b" * 64),
        )
        prediction_run_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO odds_ingestion_runs (
                sport, source_name, started_at, completed_at, status,
                games_returned, games_processed, selections_inserted,
                selections_skipped, target_date, snapshot_role,
                status_code, remaining_requests, used_requests
            ) VALUES (
                'baseball_mlb', 'odds_api', clock_timestamp(),
                clock_timestamp(), 'completed', 1, 1, 2, 0,
                %s, 'entry', 200, 10, 1
            ) RETURNING odds_ingestion_run_id;
            """,
            (target_date,),
        )
        odds_run_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO moneyline_daily_workflow_runs (
                target_date, status, current_stage,
                moneyline_prediction_run_id, odds_ingestion_run_id,
                error_message
            ) VALUES (
                %s, 'failed', 'evaluation', %s, %s,
                'No complete consensus market.'
            );
            """,
            (target_date, prediction_run_id, odds_run_id),
        )
    connection.commit()
    return {
        "target_date": target_date,
        "prediction_run_id": prediction_run_id,
        "odds_run_id": odds_run_id,
    }


def _load_failed_card_evidence(
    connection,
    *,
    target_date: date,
    prediction_run_id: int,
    odds_run_id: int,
):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT status, current_stage, moneyline_prediction_run_id,
                   odds_ingestion_run_id, error_message
            FROM moneyline_daily_workflow_runs
            WHERE target_date = %s;
            """,
            (target_date,),
        )
        workflow = cursor.fetchone()
        counts = load_moneyline_daily_official_evidence_counts(
            cursor,
            target_date=target_date,
            sport="baseball_mlb",
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=odds_run_id,
        )
    return workflow, counts


def _build_parsed_boxscore(
    *,
    game_id: int,
    game_pk: int,
    home_team_id: int,
    away_team_id: int,
    player_ids: tuple[int, int],
) -> ParsedBoxScore:
    return ParsedBoxScore(
        game_id=game_id,
        game_pk=game_pk,
        game_number=1,
        double_header=False,
        team_statistics=(
            _build_team_statistics(
                game_id=game_id,
                team_id=home_team_id,
                is_home=True,
                runs=5,
                runs_allowed=3,
            ),
            _build_team_statistics(
                game_id=game_id,
                team_id=away_team_id,
                is_home=False,
                runs=3,
                runs_allowed=5,
            ),
        ),
        pitcher_statistics=(
            _build_pitcher_statistics(
                game_id=game_id,
                team_id=home_team_id,
                player_id=player_ids[0],
            ),
            _build_pitcher_statistics(
                game_id=game_id,
                team_id=away_team_id,
                player_id=player_ids[1],
            ),
        ),
    )


def _build_team_statistics(
    *,
    game_id: int,
    team_id: int,
    is_home: bool,
    runs: int,
    runs_allowed: int,
) -> TeamGameStatistics:
    return TeamGameStatistics(
        game_id=game_id,
        team_id=team_id,
        is_home=is_home,
        runs=runs,
        hits=8,
        errors=0,
        at_bats=34,
        plate_appearances=38,
        doubles=2,
        triples=0,
        home_runs=1,
        walks=3,
        intentional_walks=0,
        strikeouts=9,
        hit_by_pitch=1,
        sacrifice_flies=0,
        stolen_bases=1,
        caught_stealing=0,
        pitching_outs=27,
        runs_allowed=runs_allowed,
        earned_runs_allowed=runs_allowed,
        hits_allowed=7,
        home_runs_allowed=1,
        walks_allowed=2,
        strikeouts_recorded=8,
        left_on_base=7,
        double_plays=1,
        source_name="mlb_stats",
    )


def _build_pitcher_statistics(
    *,
    game_id: int,
    team_id: int,
    player_id: int,
) -> PlayerGamePitchingStatistics:
    return PlayerGamePitchingStatistics(
        game_id=game_id,
        team_id=team_id,
        baseball_player_id=player_id,
        appearance_order=1,
        is_starter=True,
        pitching_outs=27,
        batters_faced=34,
        hits_allowed=7,
        runs_allowed=3,
        earned_runs_allowed=3,
        home_runs_allowed=1,
        walks_allowed=2,
        intentional_walks_allowed=0,
        strikeouts=8,
        hit_batters=0,
        pitches_thrown=105,
        strikes_thrown=70,
        decision=None,
        save_recorded=False,
        hold_recorded=False,
        blown_save_recorded=False,
        source_name="mlb_stats",
    )
