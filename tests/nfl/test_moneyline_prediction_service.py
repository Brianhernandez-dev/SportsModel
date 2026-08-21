from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect
from uuid import UUID

import pytest
from psycopg2.errors import SerializationFailure

import sportsmodel.nfl.moneyline_prediction_service as service
from sportsmodel.nfl.models import NflGame, NflGameStatus, NflSeasonType
from sportsmodel.nfl.moneyline_frozen import (
    fingerprint_payload,
    load_frozen_nfl_early_artifact,
    load_frozen_nfl_mature_artifact,
)
from sportsmodel.nfl.moneyline_inference import (
    NFLMoneylineInferenceResult,
    NFLPredictedSide,
    NFLSourceTraceChannel,
)
from sportsmodel.nfl.moneyline_prediction import (
    NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION,
    NFLMoneylinePredictionRun,
    NFLMoneylinePredictionRunStatus,
    NFLMoneylinePredictionRunType,
    canonical_nfl_moneyline_probability_text,
    canonicalize_nfl_moneyline_probability,
)
from sportsmodel.nfl.moneyline_routing import (
    NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
    NFLMoneylineRoute,
)


START = datetime(2026, 9, 10, tzinfo=timezone.utc)
END = START + timedelta(days=1)
RUN_KEY = UUID("b8eebca7-44f1-4e64-a821-01876b4db323")
EARLY_ARTIFACT = load_frozen_nfl_early_artifact()
MATURE_ARTIFACT = load_frozen_nfl_mature_artifact()


class FakeCursor:
    def __init__(self):
        self.row = None
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, parameters=None):
        self.queries.append((query, parameters))
        if "transaction_timestamp" in query:
            self.row = (START - timedelta(hours=1),)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.sessions = []
        self.cursors = []

    def cursor(self):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor

    def set_session(self, **values):
        self.sessions.append(values)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_dry_run_infers_and_performs_zero_writes(monkeypatch) -> None:
    connections = []
    monkeypatch.setattr(service, "list_nfl_prediction_targets", lambda *a, **k: (_game(1),))
    monkeypatch.setattr(service, "database_clock", lambda cursor: START - timedelta(days=1))
    monkeypatch.setattr(service, "list_existing_official_nfl_game_ids", lambda *a, **k: ())
    monkeypatch.setattr(service, "list_nfl_team_abbreviations", lambda *a, **k: ())
    monkeypatch.setattr(
        service, "create_nfl_prediction_run",
        lambda *a, **k: pytest.fail("dry-run created a run"),
    )
    monkeypatch.setattr(
        service, "insert_nfl_game_prediction",
        lambda *a, **k: pytest.fail("dry-run inserted a prediction"),
    )

    result = service._execute_nfl_moneyline_prediction_run(
        season=2026,
        target_date=date(2026, 9, 10),
        slate_start_time=START,
        slate_end_time=END,
        run_type=NFLMoneylinePredictionRunType.OFFICIAL,
        run_key=None,
        dry_run=True,
        connection_factory=lambda: _connection(connections),
        inference_runner=_inference,
    )

    assert result.dry_run
    assert len(result.inference_results) == 1
    assert result.inference_results[0].feature_vector_fingerprint == (
        result.inference_results[0].feature_vector_fingerprint
    )
    assert connections[0].commits == 0
    assert connections[0].rollbacks == 1
    assert connections[0].sessions == [{
        "isolation_level": "REPEATABLE READ", "readonly": True
    }]


@pytest.mark.parametrize(
    "run_type",
    [NFLMoneylinePredictionRunType.OFFICIAL, NFLMoneylinePredictionRunType.PREVIEW],
)
def test_write_run_uses_repeatable_read_and_persists_atomically(
    monkeypatch, run_type,
) -> None:
    connections = []
    inserted = []
    running = _run(run_type=run_type)
    completed = _run(
        run_type=run_type,
        status=NFLMoneylinePredictionRunStatus.COMPLETED,
        prediction_count=1,
        source_snapshot_sha256="a" * 64,
        prediction_set_sha256="b" * 64,
    )
    monkeypatch.setattr(service, "list_nfl_prediction_targets", lambda *a, **k: (_game(1),))
    monkeypatch.setattr(service, "load_nfl_prediction_run_by_key", lambda *a, **k: None)
    monkeypatch.setattr(service, "create_nfl_prediction_run", lambda *a, **k: running)
    monkeypatch.setattr(service, "lock_nfl_prediction_run", lambda *a, **k: running)
    monkeypatch.setattr(service, "database_clock", lambda cursor: START - timedelta(days=1))
    monkeypatch.setattr(service, "list_existing_official_nfl_game_ids", lambda *a, **k: ())
    monkeypatch.setattr(
        service, "insert_nfl_game_prediction",
        lambda *a, **values: inserted.append(values) or (91, START - timedelta(hours=1)),
    )
    monkeypatch.setattr(service, "complete_nfl_prediction_run", lambda *a, **k: completed)

    result = service._execute_nfl_moneyline_prediction_run(
        season=2026,
        target_date=date(2026, 9, 10),
        slate_start_time=START,
        slate_end_time=END,
        run_type=run_type,
        run_key=RUN_KEY,
        dry_run=False,
        connection_factory=lambda: _connection(connections),
        inference_runner=_inference,
    )

    assert result.run is completed
    assert len(inserted) == 1
    assert inserted[0]["run_type"] is run_type
    assert inserted[0]["feature_payload"]["ordered_feature_names"] == ["x"]
    assert inserted[0]["source_trace_payload"] == {
        "channels": [{"side": "home", "channel": "current_season_routing", "games": []}]
    }
    assert inserted[0]["model_home_win_probability"] == Decimal(
        "0.6000000000000000"
    )
    assert inserted[0]["classification_threshold"] == Decimal(
        "0.5000000000000000"
    )
    assert inserted[0]["predicted_side"] is NFLPredictedSide.HOME
    assert connections[0].commits == 1  # durable running audit row
    assert connections[1].commits == 1  # atomic children + completion
    assert connections[1].sessions == [{"isolation_level": "REPEATABLE READ"}]


def test_target_routing_and_feature_pit_reads_share_repeatable_read_snapshot(
    monkeypatch,
) -> None:
    connections = []
    target_cursors = []
    inference_cursors = []
    running = _run()
    completed = _run(
        status=NFLMoneylinePredictionRunStatus.COMPLETED,
        prediction_count=1,
        source_snapshot_sha256="a" * 64,
        prediction_set_sha256="b" * 64,
    )

    def targets(cursor, **kwargs):
        target_cursors.append(cursor)
        return (_game(1),)

    def infer_with_production_provider(game, *, provider, **kwargs):
        inference_cursors.append(provider._repository._cursor)
        return service.infer_nfl_moneyline(
            game,
            provider=provider,
            early_artifact_loader=kwargs["early_artifact_loader"],
            mature_artifact_loader=kwargs["mature_artifact_loader"],
        )

    monkeypatch.setattr(service, "list_nfl_prediction_targets", targets)
    monkeypatch.setattr(service, "load_nfl_prediction_run_by_key", lambda *a, **k: None)
    monkeypatch.setattr(service, "create_nfl_prediction_run", lambda *a, **k: running)
    monkeypatch.setattr(service, "lock_nfl_prediction_run", lambda *a, **k: running)
    monkeypatch.setattr(service, "database_clock", lambda cursor: START - timedelta(days=1))
    monkeypatch.setattr(service, "list_existing_official_nfl_game_ids", lambda *a, **k: ())
    monkeypatch.setattr(
        service,
        "insert_nfl_game_prediction",
        lambda *a, **k: (91, START - timedelta(hours=1)),
    )
    monkeypatch.setattr(service, "complete_nfl_prediction_run", lambda *a, **k: completed)

    service._execute_nfl_moneyline_prediction_run(
        season=2026,
        target_date=date(2026, 9, 10),
        slate_start_time=START,
        slate_end_time=END,
        run_type=NFLMoneylinePredictionRunType.OFFICIAL,
        run_key=RUN_KEY,
        dry_run=False,
        connection_factory=lambda: _connection(connections),
        inference_runner=infer_with_production_provider,
    )

    write_cursor = connections[1].cursors[0]
    assert connections[1].sessions == [{"isolation_level": "REPEATABLE READ"}]
    assert target_cursors == [connections[0].cursors[0], write_cursor]
    assert inference_cursors == [write_cursor]
    history_queries = [
        query for query, _ in write_cursor.queries
        if "FROM nfl_team_game_statistics stats" in query
    ]
    assert len(history_queries) == 4


def test_partial_slate_failure_rolls_back_children_and_retains_failed_run(
    monkeypatch,
) -> None:
    connections = []
    running = _run()
    inference_calls = []
    failure_updates = []
    monkeypatch.setattr(
        service, "list_nfl_prediction_targets",
        lambda *a, **k: (_game(1), _game(2)),
    )
    monkeypatch.setattr(service, "load_nfl_prediction_run_by_key", lambda *a, **k: None)
    monkeypatch.setattr(service, "create_nfl_prediction_run", lambda *a, **k: running)
    monkeypatch.setattr(service, "lock_nfl_prediction_run", lambda *a, **k: running)
    monkeypatch.setattr(service, "database_clock", lambda cursor: START - timedelta(days=1))
    monkeypatch.setattr(service, "list_existing_official_nfl_game_ids", lambda *a, **k: ())
    monkeypatch.setattr(
        service, "insert_nfl_game_prediction",
        lambda *a, **k: pytest.fail("no child inserts before all inference succeeds"),
    )
    monkeypatch.setattr(
        service, "fail_nfl_prediction_run",
        lambda *a, **values: failure_updates.append(values),
    )

    def failing_inference(game, **kwargs):
        inference_calls.append(game.game_id)
        if game.game_id == 2:
            raise ValueError("ineligible target")
        return _inference(game, **kwargs)

    with pytest.raises(ValueError, match="ineligible target"):
        service._execute_nfl_moneyline_prediction_run(
            season=2026,
            target_date=date(2026, 9, 10),
            slate_start_time=START,
            slate_end_time=END,
            run_type=NFLMoneylinePredictionRunType.OFFICIAL,
            run_key=RUN_KEY,
            dry_run=False,
            connection_factory=lambda: _connection(connections),
            inference_runner=failing_inference,
        )

    assert inference_calls == [1, 2]
    assert connections[1].rollbacks == 1
    assert connections[2].commits == 1
    assert failure_updates[0]["prediction_run_id"] == 7


def test_completed_run_key_returns_existing_and_mismatch_is_rejected(monkeypatch) -> None:
    targets = (_game(1),)
    early = EARLY_ARTIFACT
    mature = MATURE_ARTIFACT
    slate_sha = service._slate_fingerprint(targets)
    request_sha = service._request_fingerprint(
        season=2026, target_date=date(2026, 9, 10),
        slate_start_time=START, slate_end_time=END,
        run_type=NFLMoneylinePredictionRunType.OFFICIAL,
        slate_fingerprint=slate_sha,
        early_artifact=early, mature_artifact=mature,
    )
    existing = _run(
        status=NFLMoneylinePredictionRunStatus.COMPLETED,
        prediction_count=1,
        slate_fingerprint=slate_sha,
        request_sha256=request_sha,
        source_snapshot_sha256="a" * 64,
        prediction_set_sha256="b" * 64,
    )
    monkeypatch.setattr(
        service, "list_nfl_prediction_targets",
        lambda *a, **k: pytest.fail(
            "completed run retry must use its stored immutable slate"
        ),
    )
    monkeypatch.setattr(service, "load_nfl_prediction_run_by_key", lambda *a, **k: existing)
    result = service._execute_nfl_moneyline_prediction_run(
        season=2026, target_date=date(2026, 9, 10),
        slate_start_time=START, slate_end_time=END,
        run_type=NFLMoneylinePredictionRunType.OFFICIAL,
        run_key=RUN_KEY, dry_run=False,
        connection_factory=FakeConnection,
    )
    assert result.run is existing

    mismatched = _run(
        status=NFLMoneylinePredictionRunStatus.COMPLETED,
        prediction_count=1,
        slate_fingerprint=slate_sha,
        request_sha256="f" * 64,
        source_snapshot_sha256="a" * 64,
        prediction_set_sha256="b" * 64,
    )
    monkeypatch.setattr(service, "load_nfl_prediction_run_by_key", lambda *a, **k: mismatched)
    with pytest.raises(ValueError, match="different request identity"):
        service._execute_nfl_moneyline_prediction_run(
            season=2026, target_date=date(2026, 9, 10),
            slate_start_time=START, slate_end_time=END,
            run_type=NFLMoneylinePredictionRunType.OFFICIAL,
            run_key=RUN_KEY, dry_run=False,
            connection_factory=FakeConnection,
        )


def test_failed_run_key_cannot_be_reused(monkeypatch) -> None:
    targets = (_game(1),)
    early = EARLY_ARTIFACT
    mature = MATURE_ARTIFACT
    slate_sha = service._slate_fingerprint(targets)
    request_sha = service._request_fingerprint(
        season=2026, target_date=date(2026, 9, 10),
        slate_start_time=START, slate_end_time=END,
        run_type=NFLMoneylinePredictionRunType.OFFICIAL,
        slate_fingerprint=slate_sha, early_artifact=early, mature_artifact=mature,
    )
    failed = _run(
        status=NFLMoneylinePredictionRunStatus.FAILED,
        slate_fingerprint=slate_sha,
        request_sha256=request_sha,
    )
    monkeypatch.setattr(
        service, "list_nfl_prediction_targets",
        lambda *a, **k: pytest.fail(
            "failed run retry must use its stored immutable slate"
        ),
    )
    monkeypatch.setattr(service, "load_nfl_prediction_run_by_key", lambda *a, **k: failed)
    with pytest.raises(ValueError, match="new run_key"):
        service._execute_nfl_moneyline_prediction_run(
            season=2026, target_date=date(2026, 9, 10),
            slate_start_time=START, slate_end_time=END,
            run_type=NFLMoneylinePredictionRunType.OFFICIAL,
            run_key=RUN_KEY, dry_run=False,
            connection_factory=FakeConnection,
        )


def test_running_identical_run_key_recovers_only_with_no_children(monkeypatch) -> None:
    targets = (_game(1),)
    slate_sha = service._slate_fingerprint(targets)
    request_sha = service._request_fingerprint(
        season=2026, target_date=date(2026, 9, 10),
        slate_start_time=START, slate_end_time=END,
        run_type=NFLMoneylinePredictionRunType.OFFICIAL,
        slate_fingerprint=slate_sha,
        early_artifact=EARLY_ARTIFACT, mature_artifact=MATURE_ARTIFACT,
    )
    running = _run(
        slate_fingerprint=slate_sha,
        request_sha256=request_sha,
    )
    completed = _run(
        status=NFLMoneylinePredictionRunStatus.COMPLETED,
        prediction_count=1,
        slate_fingerprint=slate_sha,
        request_sha256=request_sha,
        source_snapshot_sha256="a" * 64,
        prediction_set_sha256="b" * 64,
    )
    connections = []
    target_reads = []
    monkeypatch.setattr(service, "load_nfl_prediction_run_by_key", lambda *a, **k: running)
    monkeypatch.setattr(service, "count_nfl_predictions_for_run", lambda *a, **k: 0)
    monkeypatch.setattr(service, "lock_nfl_prediction_run", lambda *a, **k: running)
    monkeypatch.setattr(
        service, "list_nfl_prediction_targets",
        lambda *a, **k: target_reads.append(True) or targets,
    )
    monkeypatch.setattr(service, "database_clock", lambda cursor: START - timedelta(days=1))
    monkeypatch.setattr(service, "list_existing_official_nfl_game_ids", lambda *a, **k: ())
    monkeypatch.setattr(
        service, "insert_nfl_game_prediction",
        lambda *a, **k: (91, START - timedelta(hours=1)),
    )
    monkeypatch.setattr(service, "complete_nfl_prediction_run", lambda *a, **k: completed)

    result = service._execute_nfl_moneyline_prediction_run(
        season=2026, target_date=date(2026, 9, 10),
        slate_start_time=START, slate_end_time=END,
        run_type=NFLMoneylinePredictionRunType.OFFICIAL,
        run_key=RUN_KEY, dry_run=False,
        connection_factory=lambda: _connection(connections),
        inference_runner=_inference,
    )
    assert result.run is completed
    assert target_reads == [True]
    assert connections[1].sessions == [{"isolation_level": "REPEATABLE READ"}]


def test_serialization_failure_restarts_and_returns_winning_completed_run(
    monkeypatch,
) -> None:
    targets = (_game(1),)
    slate_sha = service._slate_fingerprint(targets)
    request_sha = service._request_fingerprint(
        season=2026, target_date=date(2026, 9, 10),
        slate_start_time=START, slate_end_time=END,
        run_type=NFLMoneylinePredictionRunType.OFFICIAL,
        slate_fingerprint=slate_sha,
        early_artifact=EARLY_ARTIFACT, mature_artifact=MATURE_ARTIFACT,
    )
    running = _run(
        slate_fingerprint=slate_sha,
        request_sha256=request_sha,
    )
    completed = _run(
        status=NFLMoneylinePredictionRunStatus.COMPLETED,
        prediction_count=1,
        slate_fingerprint=slate_sha,
        request_sha256=request_sha,
        source_snapshot_sha256="a" * 64,
        prediction_set_sha256="b" * 64,
    )
    load_calls = []
    connections = []
    monkeypatch.setattr(service, "list_nfl_prediction_targets", lambda *a, **k: targets)
    monkeypatch.setattr(
        service,
        "load_nfl_prediction_run_by_key",
        lambda *a, **k: load_calls.append(True) or (
            None if len(load_calls) == 1 else completed
        ),
    )
    monkeypatch.setattr(service, "create_nfl_prediction_run", lambda *a, **k: running)
    monkeypatch.setattr(
        service, "lock_nfl_prediction_run",
        lambda *a, **k: (_ for _ in ()).throw(SerializationFailure()),
    )
    monkeypatch.setattr(
        service, "fail_nfl_prediction_run",
        lambda *a, **k: pytest.fail(
            "a serialization loser must not mark the winning run failed"
        ),
    )

    result = service._execute_nfl_moneyline_prediction_run(
        season=2026, target_date=date(2026, 9, 10),
        slate_start_time=START, slate_end_time=END,
        run_type=NFLMoneylinePredictionRunType.OFFICIAL,
        run_key=RUN_KEY, dry_run=False,
        connection_factory=lambda: _connection(connections),
        inference_runner=_inference,
    )

    assert result.run is completed
    assert len(load_calls) == 2
    assert connections[1].rollbacks == 1


def test_retry_is_bounded_and_only_for_recognized_concurrency(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        service,
        "_execute_nfl_moneyline_prediction_run_once",
        lambda **values: calls.append(values) or (
            (_ for _ in ()).throw(SerializationFailure())
        ),
    )
    with pytest.raises(SerializationFailure):
        service._execute_nfl_moneyline_prediction_run(
            season=2026, target_date=date(2026, 9, 10),
            slate_start_time=START, slate_end_time=END,
            run_type=NFLMoneylinePredictionRunType.OFFICIAL,
            run_key=RUN_KEY, dry_run=False,
        )
    assert len(calls) == service._MAX_CONCURRENCY_ATTEMPTS

    calls.clear()
    monkeypatch.setattr(
        service,
        "_execute_nfl_moneyline_prediction_run_once",
        lambda **values: calls.append(values) or (
            (_ for _ in ()).throw(ValueError("ordinary failure"))
        ),
    )
    with pytest.raises(ValueError, match="ordinary failure"):
        service._execute_nfl_moneyline_prediction_run(
            season=2026, target_date=date(2026, 9, 10),
            slate_start_time=START, slate_end_time=END,
            run_type=NFLMoneylinePredictionRunType.OFFICIAL,
            run_key=RUN_KEY, dry_run=False,
        )
    assert len(calls) == 1


def test_empty_official_write_is_rejected_before_run_creation(monkeypatch) -> None:
    monkeypatch.setattr(service, "list_nfl_prediction_targets", lambda *a, **k: ())
    monkeypatch.setattr(service, "load_nfl_prediction_run_by_key", lambda *a, **k: None)
    monkeypatch.setattr(
        service, "create_nfl_prediction_run",
        lambda *a, **k: pytest.fail("empty official run must not be created"),
    )
    with pytest.raises(ValueError, match="at least one target"):
        service._execute_nfl_moneyline_prediction_run(
            season=2026, target_date=date(2026, 9, 10),
            slate_start_time=START, slate_end_time=END,
            run_type=NFLMoneylinePredictionRunType.OFFICIAL,
            run_key=RUN_KEY, dry_run=False,
            connection_factory=FakeConnection,
            inference_runner=_inference,
        )


def test_public_execution_path_exposes_no_model_substitution_hooks() -> None:
    parameters = inspect.signature(
        service.execute_nfl_moneyline_prediction_run
    ).parameters
    assert "connection_factory" not in parameters
    assert "early_artifact_loader" not in parameters
    assert "mature_artifact_loader" not in parameters
    assert "inference_runner" not in parameters


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.052331638350280645, Decimal("0.0523316383502806")),
        (Decimal("0.49999999999999994"), Decimal("0.4999999999999999")),
        (Decimal("0.49999999999999995"), Decimal("0.5000000000000000")),
        (1.0, Decimal("1.0000000000000000")),
    ],
)
def test_probability_canonicalization_is_fixed_scale_half_even(value, expected) -> None:
    assert canonicalize_nfl_moneyline_probability(value) == expected
    assert canonical_nfl_moneyline_probability_text(value) == format(
        expected, ".16f"
    )


def test_prediction_hash_round_trips_from_persisted_canonical_values() -> None:
    inference = replace(
        _inference(_game(1)),
        model_home_win_probability=0.052331638350280645,
        classification_threshold=0.05233163835028065,
        predicted_side=NFLPredictedSide.AWAY,
    )
    prepared = service._prediction_payloads(inference)
    original_hash = service._prediction_set_fingerprint(
        (inference,), (prepared,)
    )
    persisted_record = {
        "game_id": inference.game_id,
        "selected_route": inference.selected_route.value,
        "model_specification_version": inference.model_specification_version,
        "feature_vector_sha256": inference.feature_vector_fingerprint,
        "source_trace_sha256": prepared.source_trace_sha256,
        "model_home_win_probability": format(
            prepared.model_home_win_probability, ".16f"
        ),
        "classification_threshold": format(
            prepared.classification_threshold, ".16f"
        ),
        "predicted_side": prepared.predicted_side.value,
    }
    assert prepared.model_home_win_probability == Decimal(
        "0.0523316383502806"
    )
    assert prepared.predicted_side is NFLPredictedSide.HOME
    assert original_hash == service._prediction_set_fingerprint_from_records(
        (persisted_record,)
    )


def _connection(connections):
    connection = FakeConnection()
    connections.append(connection)
    return connection


def _game(game_id):
    return NflGame(
        game_id=game_id, season=2026, season_type=NflSeasonType.REGULAR,
        week=1, week_label="Week 1",
        scheduled_start_time=START + timedelta(hours=game_id),
        home_team_id=game_id * 2 + 10, away_team_id=game_id * 2 + 11,
        status=NflGameStatus.UNPLAYED, home_score=None, away_score=None,
        overtime=None, neutral_site=False,
    )


def _inference(game, **kwargs):
    payload = {
        "feature_schema_version": "test-schema",
        "ordered_feature_names": ["x"],
        "ordered_feature_values": [1.0],
    }
    return NFLMoneylineInferenceResult(
        game_id=game.game_id, target_kickoff=game.scheduled_start_time,
        season=game.season, home_team_id=game.home_team_id,
        away_team_id=game.away_team_id, home_current_prior_games=0,
        away_current_prior_games=0, selected_route=NFLMoneylineRoute.EARLY,
        routing_contract_version=NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
        model_specification_version="test-model",
        feature_schema_version="test-schema",
        specification_fingerprint="c" * 64, model_fingerprint="d" * 64,
        ordered_feature_names=("x",), ordered_feature_values=(1.0,),
        feature_vector_fingerprint=fingerprint_payload(payload),
        feature_cutoff=game.scheduled_start_time, latest_source_kickoff=None,
        model_home_win_probability=0.6, classification_threshold=0.5,
        predicted_side=NFLPredictedSide.HOME,
        frozen_empirical_home_baseline=0.55,
        source_trace=(NFLSourceTraceChannel(
            side="home", channel="current_season_routing", games=(),
        ),),
    )


def _run(
    *, run_type=NFLMoneylinePredictionRunType.OFFICIAL,
    status=NFLMoneylinePredictionRunStatus.RUNNING,
    prediction_count=0,
    slate_fingerprint="e" * 64,
    request_sha256="f" * 64,
    source_snapshot_sha256=None,
    prediction_set_sha256=None,
):
    return NFLMoneylinePredictionRun(
        prediction_run_id=7, run_key=RUN_KEY,
        request_sha256=request_sha256, run_type=run_type,
        evaluation_protocol_version=NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION,
        routing_contract_version=NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
        season=2026, target_date=date(2026, 9, 10),
        slate_start_time=START, slate_end_time=END,
        slate_fingerprint=slate_fingerprint, target_count=1,
        early_model_specification_version=EARLY_ARTIFACT.specification_version,
        early_feature_schema_version=EARLY_ARTIFACT.feature_schema_version,
        early_specification_fingerprint=(
            EARLY_ARTIFACT.specification_fingerprint
        ),
        early_model_fingerprint=EARLY_ARTIFACT.model_fingerprint,
        mature_model_specification_version=(
            MATURE_ARTIFACT.specification_version
        ),
        mature_feature_schema_version=MATURE_ARTIFACT.feature_schema_version,
        mature_specification_fingerprint=(
            MATURE_ARTIFACT.specification_fingerprint
        ),
        mature_model_fingerprint=MATURE_ARTIFACT.model_fingerprint,
        prediction_count=prediction_count, status=status,
        source_data_as_of=None,
        source_snapshot_sha256=source_snapshot_sha256,
        prediction_set_sha256=prediction_set_sha256,
        failure_message="failed" if status is NFLMoneylinePredictionRunStatus.FAILED else None,
    )
