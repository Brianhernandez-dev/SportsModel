import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import psycopg2
from psycopg2.errors import (
    CheckViolation,
    ForeignKeyViolation,
    LockNotAvailable,
    RaiseException,
    UniqueViolation,
)
from psycopg2.extras import Json
import pytest

import sportsmodel.nfl.market_evaluation as evaluation_module
from sportsmodel.ingest.odds_api_parser import parse_odds_api_h2h_response
from sportsmodel.ingest.odds_provenance import (
    create_provider_event_observation,
    resolve_provider_sportsbook,
)
from sportsmodel.nfl.market_evaluation import (
    MATURE_SPECIFICATION_FINGERPRINT,
    OfficialMarketEvaluationConflictError,
    OfficialMarketEvaluationError,
    evaluate_official_nfl_moneyline_market,
)
from sportsmodel.nfl.manual_market_evaluation import (
    ManualMarketEvaluationGuardError,
    execute_manual_market_evaluation,
)
from sportsmodel.nfl.market_math import american_to_decimal_odds
from sportsmodel.nfl.moneyline_frozen import (
    EARLY_FEATURE_SCHEMA_VERSION,
    EARLY_MODEL_FINGERPRINT,
    EARLY_SPECIFICATION_FINGERPRINT,
    EARLY_SPECIFICATION_VERSION,
    MATURE_FEATURE_SCHEMA_VERSION,
    MATURE_MODEL_FINGERPRINT,
    MATURE_SPECIFICATION_VERSION,
)
from sportsmodel.nfl.odds_identity import resolve_and_persist_nfl_odds_event
from sportsmodel.nfl.official_pregame_evidence import (
    create_official_nfl_pregame_evidence,
)


pytestmark = pytest.mark.skipif(
    not os.getenv("SPORTSMODEL_TEST_DATABASE_URL"),
    reason="requires disposable SPORTSMODEL_TEST_DATABASE_URL",
)

ROOT = Path(__file__).parents[2]
EVENT_FIXTURE = ROOT / "tests" / "fixtures" / "odds_api" / "nfl_h2h.json"
KICKOFF = datetime(2099, 9, 11, 0, 20, tzinfo=timezone.utc)


@dataclass(frozen=True)
class SeededPrediction:
    prediction_id: int
    prediction_run_id: int
    game_id: int
    home_team_id: int
    away_team_id: int


@dataclass(frozen=True)
class SeededOdds:
    odds_run_id: int
    evidence_ids: tuple[int, ...]


def _connect(database_url):
    return lambda: psycopg2.connect(database_url)


def _team_id(cursor, abbreviation: str) -> int:
    cursor.execute(
        "SELECT team_id FROM nfl_team_profiles WHERE current_abbreviation = %s",
        (abbreviation,),
    )
    return cursor.fetchone()[0]


def _seed_prediction(
    connection,
    *,
    run_type="official",
    run_status="completed",
    route="early",
    protocol="nfl_moneyline_forward_0.1.0",
    probability=Decimal("0.6000000000000000"),
) -> SeededPrediction:
    with connection.cursor() as cursor:
        home_team_id = _team_id(cursor, "KC")
        away_team_id = _team_id(cursor, "DEN")
        cursor.execute(
            """
            INSERT INTO games (game_date, home_team_id, away_team_id)
            VALUES (%s, %s, %s) RETURNING game_id
            """,
            (KICKOFF, home_team_id, away_team_id),
        )
        game_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO nfl_games (
                game_id, season, season_type, week, week_label,
                scheduled_start_time, neutral_site, status
            ) VALUES (%s, 2099, 'regular', 1, 'Week 1', %s, FALSE, 'unplayed')
            """,
            (game_id, KICKOFF),
        )
        cursor.execute(
            """
            INSERT INTO nfl_moneyline_prediction_runs (
                run_key, request_sha256, run_type,
                evaluation_protocol_version, routing_contract_version,
                season, target_date, slate_start_time, slate_end_time,
                slate_fingerprint, early_model_specification_version,
                early_feature_schema_version, early_specification_fingerprint,
                early_model_fingerprint, mature_model_specification_version,
                mature_feature_schema_version, mature_specification_fingerprint,
                mature_model_fingerprint, target_count
            ) VALUES (
                %s, %s, %s, %s, 'nfl_moneyline_routing_0.1.0', 2099,
                '2099-09-11', '2099-09-11T00:00:00Z',
                '2099-09-12T00:00:00Z', %s, %s, %s, %s, %s,
                %s, %s, %s, %s, 1
            ) RETURNING nfl_moneyline_prediction_run_id
            """,
            (
                uuid4(),
                "0" * 64,
                run_type,
                protocol,
                "1" * 64,
                EARLY_SPECIFICATION_VERSION,
                EARLY_FEATURE_SCHEMA_VERSION,
                EARLY_SPECIFICATION_FINGERPRINT,
                EARLY_MODEL_FINGERPRINT,
                MATURE_SPECIFICATION_VERSION,
                MATURE_FEATURE_SCHEMA_VERSION,
                MATURE_SPECIFICATION_FINGERPRINT,
                MATURE_MODEL_FINGERPRINT,
            ),
        )
        prediction_run_id = cursor.fetchone()[0]
        if route == "early":
            model_version = EARLY_SPECIFICATION_VERSION
            schema_version = EARLY_FEATURE_SCHEMA_VERSION
            specification_fingerprint = EARLY_SPECIFICATION_FINGERPRINT
            model_fingerprint = EARLY_MODEL_FINGERPRINT
            prior_games = 0
        else:
            model_version = MATURE_SPECIFICATION_VERSION
            schema_version = MATURE_FEATURE_SCHEMA_VERSION
            specification_fingerprint = MATURE_SPECIFICATION_FINGERPRINT
            model_fingerprint = MATURE_MODEL_FINGERPRINT
            prior_games = 3
        cursor.execute("SELECT transaction_timestamp()")
        source_time = cursor.fetchone()[0]
        predicted_side = "home" if probability >= Decimal("0.5") else "away"
        cursor.execute(
            """
            INSERT INTO nfl_moneyline_game_predictions (
                nfl_moneyline_prediction_run_id, run_type,
                evaluation_protocol_version, game_id, season, target_kickoff,
                home_team_id, away_team_id, neutral_site, feature_cutoff,
                source_data_as_of, home_current_prior_games,
                away_current_prior_games, selected_route,
                routing_contract_version, selected_model_specification_version,
                feature_schema_version, specification_fingerprint,
                model_fingerprint, feature_payload, feature_vector_sha256,
                source_trace_payload, source_trace_sha256,
                latest_source_kickoff, model_home_win_probability,
                frozen_route_home_baseline_probability,
                classification_threshold, predicted_side
            ) VALUES (
                %s, %s, %s, %s, 2099, %s, %s, %s, FALSE, %s, %s,
                %s, %s, %s, 'nfl_moneyline_routing_0.1.0', %s, %s, %s,
                %s, %s, %s, %s, %s, NULL, %s, 0.55, 0.5, %s
            ) RETURNING nfl_moneyline_game_prediction_id
            """,
            (
                prediction_run_id,
                run_type,
                protocol,
                game_id,
                KICKOFF,
                home_team_id,
                away_team_id,
                KICKOFF,
                source_time,
                prior_games,
                prior_games,
                route,
                model_version,
                schema_version,
                specification_fingerprint,
                model_fingerprint,
                Json({
                    "feature_schema_version": schema_version,
                    "ordered_feature_names": ["x"],
                    "ordered_feature_values": [1.0],
                }),
                "3" * 64,
                Json({"channels": []}),
                "5" * 64,
                probability,
                predicted_side,
            ),
        )
        prediction_id = cursor.fetchone()[0]
        if run_status == "completed":
            cursor.execute(
                """
                UPDATE nfl_moneyline_prediction_runs
                SET prediction_count = 1, source_data_as_of = %s,
                    source_snapshot_sha256 = %s,
                    prediction_set_sha256 = %s, status = 'completed'
                WHERE nfl_moneyline_prediction_run_id = %s
                """,
                (source_time, "6" * 64, "7" * 64, prediction_run_id),
            )
    connection.commit()
    return SeededPrediction(
        prediction_id,
        prediction_run_id,
        game_id,
        home_team_id,
        away_team_id,
    )


def _event(*, event_id: str):
    parsed = parse_odds_api_h2h_response(
        json.loads(EVENT_FIXTURE.read_text(encoding="utf-8")),
        expected_sport_key="americanfootball_nfl",
    )[0]
    return replace(parsed, event_id=event_id, commence_time=KICKOFF)


def _seed_odds(
    connection,
    prediction: SeededPrediction,
    *,
    books=5,
    incomplete_provider: int | None = None,
    stale_provider: int | None = None,
    duplicate_provider: int | None = None,
    observed_at: datetime | None = None,
) -> SeededOdds:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT completed_at FROM nfl_moneyline_prediction_runs "
            "WHERE nfl_moneyline_prediction_run_id = %s",
            (prediction.prediction_run_id,),
        )
        completed_at = cursor.fetchone()[0]
        baseline = datetime.now(timezone.utc)
        if observed_at is None:
            observed_at = max(
                baseline,
                (completed_at + timedelta(milliseconds=10))
                if completed_at is not None
                else baseline,
            )
        request_started_at = observed_at - timedelta(milliseconds=1)
        cursor.execute(
            "SELECT COUNT(*) FROM odds_ingestion_runs "
            "WHERE sport = 'americanfootball_nfl' AND snapshot_role = 'entry'"
        )
        target_date = KICKOFF.date() + timedelta(days=cursor.fetchone()[0])
        cursor.execute(
            """
            INSERT INTO odds_ingestion_runs (
                sport, source_name, snapshot_role, status, target_date,
                request_path,
                request_regions, request_markets, request_odds_format,
                request_started_at, response_received_at, status_code
            ) VALUES (
                'americanfootball_nfl', 'odds_api', 'entry', 'running', %s,
                '/v4/sports/americanfootball_nfl/odds', 'us', 'h2h',
                'american', %s, %s, 200
            ) RETURNING odds_ingestion_run_id
            """,
            (target_date, request_started_at, observed_at),
        )
        odds_run_id = cursor.fetchone()[0]
        event = _event(event_id=f"evaluation-{uuid4()}")
        mapping = resolve_and_persist_nfl_odds_event(cursor, event)
        event_observation_id = create_provider_event_observation(
            cursor,
            ingestion_run_id=odds_run_id,
            provider_name="odds_api",
            event=event,
            observed_at=observed_at,
            nfl_provider_event_mapping_id=mapping.provider_event_mapping_id,
        )
        snapshot_ids: list[tuple[int, int]] = []
        inserted = 0
        for index in range(books):
            provider = resolve_provider_sportsbook(
                cursor,
                provider_name="odds_api",
                provider_bookmaker_key=f"evaluation_book_{index}",
                bookmaker_title=f"Evaluation Book {index}",
            )
            market_time = observed_at - timedelta(seconds=20 + index)
            if stale_provider == index:
                market_time = observed_at - timedelta(seconds=301)
            selections = [
                ("Kansas City Chiefs", prediction.home_team_id, -110 + index),
                ("Denver Broncos", prediction.away_team_id, 100 + index),
            ]
            if incomplete_provider == index:
                selections.pop()
            if duplicate_provider == index:
                selections.append(selections[0])
            for selection_name, selection_team_id, price in selections:
                cursor.execute(
                    """
                    INSERT INTO odds_market_snapshots (
                        odds_ingestion_run_id,
                        odds_provider_event_observation_id,
                        game_id, sportsbook_provider_identity_id,
                        sportsbook_id, market_type, selection_name, price,
                        snapshot_time, source_name,
                        bookmaker_title_at_observation,
                        bookmaker_updated_at, market_updated_at, observed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'h2h', %s, %s, %s,
                        'odds_api', %s, %s, %s, %s
                    ) RETURNING odds_market_snapshot_id
                    """,
                    (
                        odds_run_id,
                        event_observation_id,
                        prediction.game_id,
                        provider.sportsbook_provider_identity_id,
                        provider.sportsbook_id,
                        selection_name,
                        price,
                        observed_at,
                        f"Evaluation Book {index}",
                        market_time,
                        market_time,
                        observed_at,
                    ),
                )
                snapshot_ids.append((cursor.fetchone()[0], selection_team_id))
                inserted += 1
        cursor.execute(
            """
            UPDATE odds_ingestion_runs
            SET status = 'completed', completed_at = clock_timestamp(),
                games_returned = 1, games_processed = 1,
                selections_inserted = %s, selections_skipped = 0
            WHERE odds_ingestion_run_id = %s
            """,
            (inserted, odds_run_id),
        )
        evidence_ids = []
        for snapshot_id, selection_team_id in snapshot_ids:
            evidence = create_official_nfl_pregame_evidence(
                cursor,
                odds_market_snapshot_id=snapshot_id,
                canonical_selection_team_id=selection_team_id,
            )
            evidence_ids.append(evidence.nfl_official_pregame_evidence_id)
    connection.commit()
    return SeededOdds(odds_run_id, tuple(evidence_ids))


def _counts(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM nfl_moneyline_market_evaluations),
                (SELECT COUNT(*) FROM nfl_moneyline_market_evaluation_contributors),
                (SELECT COUNT(*) FROM nfl_moneyline_market_evaluation_exclusions)
            """
        )
        return cursor.fetchone()


def _all_evaluation_counts(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM nfl_moneyline_market_evaluation_runs),
                (SELECT COUNT(*) FROM nfl_moneyline_market_evaluations),
                (SELECT COUNT(*)
                   FROM nfl_moneyline_market_evaluation_contributors),
                (SELECT COUNT(*) FROM nfl_moneyline_market_evaluation_exclusions)
            """
        )
        return cursor.fetchone()


def test_migration_031_schema_contract(initialized_nfl_test_database) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name LIKE 'nfl_moneyline_market_evaluation%'
            ORDER BY table_name
            """
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "nfl_moneyline_market_evaluation_contributors",
            "nfl_moneyline_market_evaluation_exclusions",
            "nfl_moneyline_market_evaluation_runs",
            "nfl_moneyline_market_evaluations",
        }
        cursor.execute(
            """
            SELECT conname, contype, confdeltype
            FROM pg_constraint
            WHERE conrelid IN (
                'nfl_moneyline_market_evaluation_runs'::regclass,
                'nfl_moneyline_market_evaluations'::regclass,
                'nfl_moneyline_market_evaluation_contributors'::regclass,
                'nfl_moneyline_market_evaluation_exclusions'::regclass
            )
            """
        )
        constraints = cursor.fetchall()
        names = {row[0] for row in constraints}
        assert {
            "uq_nfl_market_evaluation_identity",
            "uq_nfl_market_contributor_provider",
            "chk_nfl_market_exclusion_reason",
            "chk_nfl_market_evaluation_numbers",
            "chk_nfl_market_evaluation_time",
        } <= names
        assert all(
            delete_action == "r"
            for unused_name, constraint_type, delete_action in constraints
            if constraint_type == "f"
        )
        cursor.execute(
            """
            SELECT tgname
            FROM pg_trigger
            WHERE NOT tgisinternal
              AND tgrelid IN (
                'nfl_moneyline_market_evaluation_runs'::regclass,
                'nfl_moneyline_market_evaluations'::regclass,
                'nfl_moneyline_market_evaluation_contributors'::regclass,
                'nfl_moneyline_market_evaluation_exclusions'::regclass
              )
            """
        )
        trigger_names = {row[0] for row in cursor.fetchall()}
        assert {
            "trg_protect_nfl_market_evaluation_run",
            "trg_nfl_market_evaluation_parent_immutable",
            "trg_nfl_market_evaluation_contributor_immutable",
            "trg_nfl_market_evaluation_exclusion_immutable",
            "trg_validate_nfl_market_evaluation_graph_parent",
        } <= trigger_names
    connection.close()


@pytest.mark.parametrize(
    ("route", "probability", "selected_side"),
    [
        ("early", Decimal("0.6000000000000000"), "home"),
        ("mature", Decimal("0.4000000000000000"), "away"),
    ],
)
def test_official_evaluation_persists_exact_graph_and_math(
    initialized_nfl_test_database,
    route,
    probability,
    selected_side,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(
        connection,
        route=route,
        probability=probability,
    )
    odds = _seed_odds(connection, prediction, books=6)
    result = evaluate_official_nfl_moneyline_market(
        prediction_id=prediction.prediction_id,
        odds_ingestion_run_id=odds.odds_run_id,
        connection_factory=_connect(initialized_nfl_test_database),
    )
    assert result.idempotent is False
    assert result.evaluation.selected_side == selected_side
    assert result.evaluation.contributor_count == 6
    assert len(result.evaluation.contributors) == 6
    assert result.evaluation.best_price_evidence_id in odds.evidence_ids
    assert result.evaluation.best_price_provider_identity_id in {
        item.provider_identity_id for item in result.evaluation.contributors
    }
    assert result.evaluation.market_edge == (
        probability - result.evaluation.consensus_no_vig_selected_probability
        if selected_side == "home"
        else Decimal("1.0000000000000000")
        - probability
        - result.evaluation.consensus_no_vig_selected_probability
    )
    expected_model_probability = (
        probability
        if selected_side == "home"
        else Decimal("1.0000000000000000") - probability
    )
    assert result.evaluation.model_expected_value == (
        expected_model_probability
        * american_to_decimal_odds(result.evaluation.best_american_price)
        - Decimal("1.0000000000000000")
    ).quantize(Decimal("0.0000000000000001"))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT nfl_official_pregame_evidence_id, american_price
            FROM nfl_official_pregame_evidence
            WHERE nfl_official_pregame_evidence_id = ANY(%s)
            """,
            (list(odds.evidence_ids),),
        )
        prices_by_evidence = dict(cursor.fetchall())
    for contributor in result.evaluation.contributors:
        assert prices_by_evidence[contributor.home_evidence_id] == (
            contributor.home_american_price
        )
        assert prices_by_evidence[contributor.away_evidence_id] == (
            contributor.away_american_price
        )
    assert _counts(connection) == (1, 6, 0)
    connection.close()


def test_minimum_coverage_and_deterministic_exclusions(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    four_books = _seed_odds(connection, prediction, books=4)
    with pytest.raises(OfficialMarketEvaluationError) as insufficient:
        evaluate_official_nfl_moneyline_market(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=four_books.odds_run_id,
            connection_factory=_connect(initialized_nfl_test_database),
        )
    assert insufficient.value.code == "insufficient_coverage"
    assert _counts(connection) == (0, 0, 0)

    seven_books = _seed_odds(
        connection,
        prediction,
        books=7,
        incomplete_provider=5,
        stale_provider=6,
    )
    success = evaluate_official_nfl_moneyline_market(
        prediction_id=prediction.prediction_id,
        odds_ingestion_run_id=seven_books.odds_run_id,
        connection_factory=_connect(initialized_nfl_test_database),
    )
    assert success.evaluation.contributor_count == 5
    assert {item.reason_code for item in success.evaluation.exclusions} == {
        "incomplete_market",
        "stale_market",
    }
    assert _counts(connection) == (1, 5, 2)
    evaluation_id = success.evaluation.evaluation_id
    for statement in (
        "UPDATE nfl_moneyline_market_evaluation_exclusions SET reason_code = 'stale_market' WHERE nfl_moneyline_market_evaluation_id = %s",
        "DELETE FROM nfl_moneyline_market_evaluation_exclusions WHERE nfl_moneyline_market_evaluation_id = %s",
    ):
        with pytest.raises(RaiseException, match="immutable"):
            with connection.cursor() as cursor:
                cursor.execute(statement, (evaluation_id,))
        connection.rollback()
    connection.close()


def test_source_schema_prevents_duplicate_provider_selection_graph(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    with pytest.raises(UniqueViolation, match="uq_odds_snapshot_provider_selection"):
        _seed_odds(
            connection,
            prediction,
            books=5,
            duplicate_provider=0,
        )
    connection.rollback()
    assert _counts(connection) == (0, 0, 0)
    connection.close()


def test_same_graph_is_idempotent_and_different_graph_conflicts(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    first_odds = _seed_odds(connection, prediction)
    second_odds = _seed_odds(connection, prediction)
    first = evaluate_official_nfl_moneyline_market(
        prediction_id=prediction.prediction_id,
        odds_ingestion_run_id=first_odds.odds_run_id,
        connection_factory=_connect(initialized_nfl_test_database),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE nfl_games SET status = 'final', home_score = 24, "
            "away_score = 17, overtime = FALSE WHERE game_id = %s",
            (prediction.game_id,),
        )
    connection.commit()
    replay = evaluate_official_nfl_moneyline_market(
        prediction_id=prediction.prediction_id,
        odds_ingestion_run_id=first_odds.odds_run_id,
        connection_factory=_connect(initialized_nfl_test_database),
    )
    assert replay.idempotent is True
    assert replay.evaluation.evaluation_id == first.evaluation.evaluation_id
    with pytest.raises(OfficialMarketEvaluationConflictError) as conflict:
        evaluate_official_nfl_moneyline_market(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=second_odds.odds_run_id,
            connection_factory=_connect(initialized_nfl_test_database),
        )
    assert conflict.value.code == "source_graph_conflict"
    assert _counts(connection) == (1, 5, 0)
    connection.close()


def test_database_immutability_delete_restrictions_and_cross_graph_constraints(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    odds = _seed_odds(connection, prediction)
    result = evaluate_official_nfl_moneyline_market(
        prediction_id=prediction.prediction_id,
        odds_ingestion_run_id=odds.odds_run_id,
        connection_factory=_connect(initialized_nfl_test_database),
    )
    evaluation_id = result.evaluation.evaluation_id
    for statement in (
        "UPDATE nfl_moneyline_market_evaluations SET contributor_count = 6 WHERE nfl_moneyline_market_evaluation_id = %s",
        "DELETE FROM nfl_moneyline_market_evaluations WHERE nfl_moneyline_market_evaluation_id = %s",
        "UPDATE nfl_moneyline_market_evaluation_contributors SET contributor_ordinal = 9 WHERE nfl_moneyline_market_evaluation_id = %s",
        "DELETE FROM nfl_moneyline_market_evaluation_contributors WHERE nfl_moneyline_market_evaluation_id = %s",
    ):
        with pytest.raises(RaiseException, match="immutable"):
            with connection.cursor() as cursor:
                cursor.execute(statement, (evaluation_id,))
        connection.rollback()
    with pytest.raises(RaiseException, match="copied source identity mismatch"):
        with connection.cursor() as cursor:
            contributor = result.evaluation.contributors[0]
            cursor.execute(
                """
                INSERT INTO nfl_moneyline_market_evaluation_contributors (
                    nfl_moneyline_market_evaluation_id,
                    odds_ingestion_run_id, game_id, trusted_observed_at,
                    contributor_ordinal, sportsbook_provider_identity_id,
                    home_nfl_official_pregame_evidence_id,
                    away_nfl_official_pregame_evidence_id,
                    home_american_price, away_american_price,
                    home_raw_implied_probability,
                    away_raw_implied_probability,
                    home_no_vig_probability, away_no_vig_probability,
                    market_updated_at
                ) VALUES (%s, -1, %s, %s, 99, %s, %s, %s, -110, 100,
                          0.5, 0.5, 0.5, 0.5, %s)
                """,
                (
                    evaluation_id,
                    prediction.game_id,
                    contributor.trusted_observed_at,
                    contributor.provider_identity_id + 1000,
                    contributor.home_evidence_id,
                    contributor.away_evidence_id,
                    contributor.market_updated_at,
                ),
            )
    connection.rollback()
    connection.close()


def test_forced_child_failure_rolls_back_parent_and_children(
    initialized_nfl_test_database,
    monkeypatch,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    odds = _seed_odds(connection, prediction)

    def fail_child(cursor, *, evaluation_id, prepared):
        cursor.execute("SELECT 1 / 0")

    monkeypatch.setattr(evaluation_module, "_insert_contributors", fail_child)
    with pytest.raises(OfficialMarketEvaluationError) as captured:
        evaluate_official_nfl_moneyline_market(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=odds.odds_run_id,
            connection_factory=_connect(initialized_nfl_test_database),
        )
    assert captured.value.code == "persistence_error"
    assert _counts(connection) == (0, 0, 0)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, evaluation_count FROM "
            "nfl_moneyline_market_evaluation_runs"
        )
        assert cursor.fetchall() == [("failed", 0)]
    connection.close()


def test_same_and_conflicting_source_graph_concurrency(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    first_odds = _seed_odds(connection, prediction)
    second_odds = _seed_odds(connection, prediction)
    barrier = Barrier(2)

    def same_worker():
        barrier.wait()
        return evaluate_official_nfl_moneyline_market(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=first_odds.odds_run_id,
            connection_factory=_connect(initialized_nfl_test_database),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        same_results = list(executor.map(lambda _: same_worker(), range(2)))
    assert {item.idempotent for item in same_results} == {False, True}
    assert len({item.evaluation.evaluation_id for item in same_results}) == 1
    assert _counts(connection) == (1, 5, 0)

    connection.close()


def test_conflicting_graph_concurrency_one_wins(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    first_odds = _seed_odds(connection, prediction)
    second_odds = _seed_odds(connection, prediction)
    barrier = Barrier(2)

    def worker(odds_run_id):
        barrier.wait()
        try:
            return evaluate_official_nfl_moneyline_market(
                prediction_id=prediction.prediction_id,
                odds_ingestion_run_id=odds_run_id,
                connection_factory=_connect(initialized_nfl_test_database),
            )
        except OfficialMarketEvaluationConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(worker, (first_odds.odds_run_id, second_odds.odds_run_id))
        )
    assert sum(
        not isinstance(item, OfficialMarketEvaluationError) for item in outcomes
    ) == 1
    assert sum(
        isinstance(item, OfficialMarketEvaluationConflictError)
        for item in outcomes
    ) == 1
    assert _counts(connection) == (1, 5, 0)
    connection.close()


def test_kickoff_row_lock_prevents_overlapping_invalid_update(
    initialized_nfl_test_database,
    monkeypatch,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    odds = _seed_odds(connection, prediction)
    locked = Event()
    release = Event()
    original = evaluation_module._load_odds_run_source

    def pause_after_game_lock(cursor, odds_run_id):
        result = original(cursor, odds_run_id)
        locked.set()
        assert release.wait(timeout=5)
        return result

    monkeypatch.setattr(
        evaluation_module,
        "_load_odds_run_source",
        pause_after_game_lock,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            evaluate_official_nfl_moneyline_market,
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=odds.odds_run_id,
            connection_factory=_connect(initialized_nfl_test_database),
        )
        assert locked.wait(timeout=5)
        updater = psycopg2.connect(initialized_nfl_test_database)
        try:
            with updater.cursor() as cursor:
                cursor.execute("SET lock_timeout = '200ms'")
                with pytest.raises(LockNotAvailable):
                    cursor.execute(
                        "UPDATE nfl_games SET scheduled_start_time = %s "
                        "WHERE game_id = %s",
                        (KICKOFF - timedelta(hours=1), prediction.game_id),
                    )
            updater.rollback()
        finally:
            updater.close()
            release.set()
        result = future.result(timeout=5)
    assert result.evaluation.evaluation_id > 0
    assert _counts(connection) == (1, 5, 0)
    connection.close()


@pytest.mark.parametrize(
    ("route", "probability", "selected_side"),
    [
        ("early", Decimal("0.6000000000000000"), "home"),
        ("mature", Decimal("0.4000000000000000"), "away"),
    ],
)
def test_manual_preview_and_guarded_live_rehearsal(
    initialized_nfl_test_database,
    route,
    probability,
    selected_side,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(
        connection,
        route=route,
        probability=probability,
    )
    odds = _seed_odds(connection, prediction, books=5)
    factory = _connect(initialized_nfl_test_database)

    preview = execute_manual_market_evaluation(
        prediction_id=prediction.prediction_id,
        odds_ingestion_run_id=odds.odds_run_id,
        connection_factory=factory,
    )
    assert preview.dry_run is True
    assert preview.preview.selected_route == route
    assert preview.preview.selected_side == selected_side
    assert preview.preview.contributor_count == 5
    assert preview.preview.idempotent is False
    assert _all_evaluation_counts(connection) == (0, 0, 0, 0)

    with pytest.raises(ManualMarketEvaluationGuardError):
        execute_manual_market_evaluation(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=odds.odds_run_id,
            live=True,
            connection_factory=factory,
        )
    assert _all_evaluation_counts(connection) == (0, 0, 0, 0)

    live = execute_manual_market_evaluation(
        prediction_id=prediction.prediction_id,
        odds_ingestion_run_id=odds.odds_run_id,
        live=True,
        confirm_create_evaluation=True,
        connection_factory=factory,
    )
    assert live.execution is not None
    assert live.execution.idempotent is False
    evaluation_id = live.execution.evaluation.evaluation_id
    assert _all_evaluation_counts(connection) == (1, 1, 5, 0)

    replay = execute_manual_market_evaluation(
        prediction_id=prediction.prediction_id,
        odds_ingestion_run_id=odds.odds_run_id,
        live=True,
        confirm_create_evaluation=True,
        connection_factory=factory,
    )
    assert replay.execution is not None
    assert replay.execution.idempotent is True
    assert replay.execution.evaluation.evaluation_id == evaluation_id
    assert _all_evaluation_counts(connection) == (2, 1, 5, 0)
    connection.close()


def test_manual_different_graph_conflicts_before_write(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    first_odds = _seed_odds(connection, prediction)
    second_odds = _seed_odds(connection, prediction)
    factory = _connect(initialized_nfl_test_database)
    first = execute_manual_market_evaluation(
        prediction_id=prediction.prediction_id,
        odds_ingestion_run_id=first_odds.odds_run_id,
        live=True,
        confirm_create_evaluation=True,
        connection_factory=factory,
    )
    assert first.execution is not None
    with pytest.raises(OfficialMarketEvaluationConflictError) as conflict:
        execute_manual_market_evaluation(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=second_odds.odds_run_id,
            live=True,
            confirm_create_evaluation=True,
            connection_factory=factory,
        )
    assert conflict.value.code == "source_graph_conflict"
    assert _all_evaluation_counts(connection) == (1, 1, 5, 0)
    connection.close()


@pytest.mark.parametrize(
    ("run_type", "run_status"),
    [
        ("preview", "completed"),
        ("official", "running"),
    ],
)
def test_manual_preview_rejects_nonofficial_or_noncompleted_prediction_runs(
    initialized_nfl_test_database,
    run_type,
    run_status,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(
        connection,
        run_type=run_type,
        run_status=run_status,
    )
    odds = _seed_odds(connection, prediction)
    with pytest.raises(OfficialMarketEvaluationError) as captured:
        execute_manual_market_evaluation(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=odds.odds_run_id,
            connection_factory=_connect(initialized_nfl_test_database),
        )
    assert captured.value.code == "prediction_ineligible"
    assert _all_evaluation_counts(connection) == (0, 0, 0, 0)
    connection.close()


@pytest.mark.parametrize(
    ("sport", "source", "role", "status"),
    [
        ("baseball_mlb", "odds_api", "entry", "completed"),
        ("americanfootball_nfl", "manual", "entry", "completed"),
        ("americanfootball_nfl", "odds_api", "manual", "completed"),
        ("americanfootball_nfl", "odds_api", "entry", "running"),
    ],
)
def test_manual_preview_rejects_odds_run_identity_mismatch(
    initialized_nfl_test_database,
    sport,
    source,
    role,
    status,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO odds_ingestion_runs (
                sport, source_name, snapshot_role, status, target_date,
                request_path, request_regions, request_markets,
                request_odds_format, request_started_at,
                response_received_at, status_code
            ) VALUES (%s, %s, %s, %s, '2099-09-11',
                      '/test/persisted-evidence', 'us', 'h2h', 'american',
                      clock_timestamp(), clock_timestamp(), 200)
            RETURNING odds_ingestion_run_id
            """,
            (sport, source, role, status),
        )
        odds_run_id = cursor.fetchone()[0]
    connection.commit()
    with pytest.raises(OfficialMarketEvaluationError) as captured:
        execute_manual_market_evaluation(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=odds_run_id,
            connection_factory=_connect(initialized_nfl_test_database),
        )
    assert captured.value.code == "odds_run_ineligible"
    assert _all_evaluation_counts(connection) == (0, 0, 0, 0)
    connection.close()


def test_manual_preview_rejects_odds_captured_before_prediction(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT prediction_created_at FROM nfl_moneyline_game_predictions "
            "WHERE nfl_moneyline_game_prediction_id = %s",
            (prediction.prediction_id,),
        )
        prediction_created_at = cursor.fetchone()[0]
    odds = _seed_odds(
        connection,
        prediction,
        observed_at=prediction_created_at - timedelta(seconds=1),
    )
    with pytest.raises(OfficialMarketEvaluationError) as captured:
        execute_manual_market_evaluation(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=odds.odds_run_id,
            connection_factory=_connect(initialized_nfl_test_database),
        )
    assert captured.value.code == "prediction_market_timing_ineligible"
    assert _all_evaluation_counts(connection) == (0, 0, 0, 0)
    connection.close()


def test_manual_preview_excludes_stale_and_incomplete_then_enforces_minimum(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    eligible_odds = _seed_odds(
        connection,
        prediction,
        books=7,
        incomplete_provider=5,
        stale_provider=6,
    )
    preview = execute_manual_market_evaluation(
        prediction_id=prediction.prediction_id,
        odds_ingestion_run_id=eligible_odds.odds_run_id,
        connection_factory=_connect(initialized_nfl_test_database),
    )
    assert preview.preview.contributor_count == 5
    assert {item.reason_code for item in preview.preview.exclusions} == {
        "incomplete_market",
        "stale_market",
    }
    assert _all_evaluation_counts(connection) == (0, 0, 0, 0)

    insufficient_odds = _seed_odds(connection, prediction, books=4)
    with pytest.raises(OfficialMarketEvaluationError) as captured:
        execute_manual_market_evaluation(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=insufficient_odds.odds_run_id,
            connection_factory=_connect(initialized_nfl_test_database),
        )
    assert captured.value.code == "insufficient_coverage"
    assert _all_evaluation_counts(connection) == (0, 0, 0, 0)
    connection.close()


def test_manual_preview_rejects_game_that_is_no_longer_unplayed(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    odds = _seed_odds(connection, prediction)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE nfl_games SET status = 'final', home_score = 24, "
            "away_score = 17, overtime = FALSE WHERE game_id = %s",
            (prediction.game_id,),
        )
    connection.commit()
    with pytest.raises(OfficialMarketEvaluationError) as captured:
        execute_manual_market_evaluation(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=odds.odds_run_id,
            connection_factory=_connect(initialized_nfl_test_database),
        )
    assert captured.value.code == "game_already_played"
    assert _all_evaluation_counts(connection) == (0, 0, 0, 0)
    connection.close()


def test_manual_and_persistence_paths_require_schema_031_before_attempt(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    prediction = _seed_prediction(connection)
    odds = _seed_odds(connection, prediction)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM schema_migrations WHERE version = 31")
    connection.commit()
    factory = _connect(initialized_nfl_test_database)
    with pytest.raises(OfficialMarketEvaluationError) as preview_error:
        execute_manual_market_evaluation(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=odds.odds_run_id,
            connection_factory=factory,
        )
    assert preview_error.value.code == "schema_incompatible"
    with pytest.raises(OfficialMarketEvaluationError) as live_error:
        evaluate_official_nfl_moneyline_market(
            prediction_id=prediction.prediction_id,
            odds_ingestion_run_id=odds.odds_run_id,
            connection_factory=factory,
        )
    assert live_error.value.code == "schema_incompatible"
    assert _all_evaluation_counts(connection) == (0, 0, 0, 0)
    connection.close()
