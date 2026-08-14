from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sportsmodel.analysis import (
    moneyline_market_evaluation_service
    as service,
)
from sportsmodel.models.moneyline_market_evaluation import (
    MoneylineMarketEvaluationPolicy,
)
from sportsmodel.models.snapshot import (
    MarketSnapshot,
)


PREDICTION_TIME = datetime(
    2026,
    7,
    30,
    3,
    0,
    tzinfo=timezone.utc,
)

SNAPSHOT_TIME = datetime(
    2026,
    7,
    30,
    3,
    10,
    tzinfo=timezone.utc,
)

GAME_START_TIME = datetime(
    2026,
    7,
    30,
    17,
    40,
    tzinfo=timezone.utc,
)


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False


class FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_evaluates_and_persists_prediction(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    persisted = []

    _patch_loaded_records(
        monkeypatch,
        snapshot_time=SNAPSHOT_TIME,
    )

    monkeypatch.setattr(
        service,
        "upsert_moneyline_market_evaluation",
        lambda cursor, **kwargs: (
            persisted.append(kwargs)
            or 88
        ),
    )

    result = (
        service.evaluate_moneyline_prediction_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            policy=MoneylineMarketEvaluationPolicy(
                policy_version="test-1",
                minimum_sportsbook_count=2,
            ),
            connection_factory=lambda: connection,
        )
    )

    assert result.predictions_loaded == 1
    assert result.evaluations_saved == 1
    assert result.paper_candidates == 1

    evaluation = result.evaluations[0]

    assert (
        evaluation
        .moneyline_prediction_market_evaluation_id
        == 88
    )

    assert evaluation.price == 110
    assert evaluation.sportsbook_name == "Book Two"

    assert len(persisted) == 1

    assert persisted[0][
        "moneyline_game_prediction_id"
    ] == 501

    assert persisted[0][
        "odds_ingestion_run_id"
    ] == 181

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_rejects_snapshot_before_prediction(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    _patch_loaded_records(
        monkeypatch,
        snapshot_time=datetime(
            2026,
            7,
            30,
            2,
            59,
            tzinfo=timezone.utc,
        ),
    )

    with pytest.raises(
        ValueError,
        match="cannot precede",
    ):
        service.evaluate_moneyline_prediction_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            connection_factory=lambda: connection,
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed is True


def test_rejects_snapshot_at_game_start(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    _patch_loaded_records(
        monkeypatch,
        snapshot_time=GAME_START_TIME,
    )

    with pytest.raises(
        ValueError,
        match="before the game starts",
    ):
        service.evaluate_moneyline_prediction_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            connection_factory=lambda: connection,
        )

    assert connection.rollbacks == 1


def test_rejects_missing_matching_snapshots(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    monkeypatch.setattr(
        service,
        "_validate_completed_runs",
        lambda cursor, **kwargs: None,
    )

    monkeypatch.setattr(
        service,
        "_load_prediction_records",
        lambda cursor, **kwargs: (
            _prediction(),
        ),
    )

    monkeypatch.setattr(
        service,
        "_load_snapshot_records",
        lambda cursor, **kwargs: (
            (),
            {},
        ),
    )

    with pytest.raises(
        LookupError,
        match="no matching",
    ):
        service.evaluate_moneyline_prediction_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            connection_factory=lambda: connection,
        )

    assert connection.rollbacks == 1


def test_partial_coverage_skips_only_missing_consensus_markets(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    persisted = []
    predictions = tuple(
        _prediction(game_id=game_id)
        for game_id in range(8066, 8080)
    )
    available_game_ids = set(range(8066, 8077))
    snapshots = tuple(
        snapshot
        for game_id in available_game_ids
        for snapshot in _snapshots(
            snapshot_time=SNAPSHOT_TIME,
            game_id=game_id,
        )
    )

    monkeypatch.setattr(
        service,
        "_validate_completed_runs",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_load_prediction_records",
        lambda *args, **kwargs: predictions,
    )
    monkeypatch.setattr(
        service,
        "_load_snapshot_records",
        lambda *args, **kwargs: (
            snapshots,
            {1: "Book One", 2: "Book Two"},
        ),
    )
    monkeypatch.setattr(
        service,
        "upsert_moneyline_market_evaluation",
        lambda cursor, **kwargs: persisted.append(kwargs) or len(persisted),
    )

    result = service.evaluate_moneyline_prediction_run(
        prediction_run_id=1,
        odds_ingestion_run_id=181,
        connection_factory=lambda: connection,
        require_complete_market_coverage=False,
    )

    assert result.predictions_loaded == 14
    assert result.evaluations_saved == 11
    assert result.skipped_missing_market_game_ids == (8077, 8078, 8079)
    assert len(persisted) == 11


def test_default_coverage_remains_strict(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(
        service,
        "_validate_completed_runs",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_load_prediction_records",
        lambda *args, **kwargs: (
            _prediction(),
            _prediction(game_id=8067),
        ),
    )
    monkeypatch.setattr(
        service,
        "_load_snapshot_records",
        lambda *args, **kwargs: (
            _snapshots(snapshot_time=SNAPSHOT_TIME),
            {1: "Book One", 2: "Book Two"},
        ),
    )

    with pytest.raises(LookupError, match="8067"):
        service.evaluate_moneyline_prediction_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            connection_factory=lambda: connection,
        )


def test_partial_coverage_with_all_markets_has_no_skips(monkeypatch) -> None:
    connection = FakeConnection()
    _patch_loaded_records(monkeypatch, snapshot_time=SNAPSHOT_TIME)
    monkeypatch.setattr(
        service,
        "upsert_moneyline_market_evaluation",
        lambda cursor, **kwargs: 88,
    )

    result = service.evaluate_moneyline_prediction_run(
        prediction_run_id=1,
        odds_ingestion_run_id=181,
        connection_factory=lambda: connection,
        require_complete_market_coverage=False,
    )

    assert result.evaluations_saved == 1
    assert result.skipped_missing_market_game_ids == ()


def test_repeated_partial_evaluation_uses_same_upsert_key(
    monkeypatch,
) -> None:
    _patch_loaded_records(monkeypatch, snapshot_time=SNAPSHOT_TIME)
    persisted_keys = set()

    def fake_upsert(cursor, **arguments):
        persisted_keys.add(
            (
                arguments["moneyline_game_prediction_id"],
                arguments["odds_ingestion_run_id"],
                arguments["evaluation"].policy_version,
            )
        )
        return 88

    monkeypatch.setattr(
        service,
        "upsert_moneyline_market_evaluation",
        fake_upsert,
    )

    for _ in range(2):
        result = service.evaluate_moneyline_prediction_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            connection_factory=FakeConnection,
            require_complete_market_coverage=False,
        )
        assert result.evaluations_saved == 1

    assert persisted_keys == {(501, 181, "1.0.0")}


def test_rejects_nonpositive_run_identifier() -> None:
    with pytest.raises(
        ValueError,
        match="Prediction run ID",
    ):
        service.evaluate_moneyline_prediction_run(
            prediction_run_id=0,
            odds_ingestion_run_id=181,
        )


def _patch_loaded_records(
    monkeypatch,
    *,
    snapshot_time: datetime,
) -> None:
    monkeypatch.setattr(
        service,
        "_validate_completed_runs",
        lambda cursor, **kwargs: None,
    )

    monkeypatch.setattr(
        service,
        "_load_prediction_records",
        lambda cursor, **kwargs: (
            _prediction(),
        ),
    )

    snapshots = _snapshots(
        snapshot_time=snapshot_time,
    )

    monkeypatch.setattr(
        service,
        "_load_snapshot_records",
        lambda cursor, **kwargs: (
            snapshots,
            {
                1: "Book One",
                2: "Book Two",
            },
        ),
    )


def _prediction(
    *,
    game_id: int = 8066,
) -> service.StoredMoneylinePrediction:
    return service.StoredMoneylinePrediction(
        moneyline_game_prediction_id=501,
        game_id=game_id,
        prediction_time=PREDICTION_TIME,
        game_start_time=GAME_START_TIME,
        away_team_name="Kansas City Royals",
        home_team_name="Minnesota Twins",
        selection_name="Kansas City Royals",
        model_probability=Decimal("0.60"),
        starter_coverage="both",
        home_starter_features_available=True,
        away_starter_features_available=True,
    )


def _snapshots(
    *,
    snapshot_time: datetime,
    game_id: int = 8066,
) -> tuple[MarketSnapshot, ...]:
    return (
        MarketSnapshot(
            odds_market_snapshot_id=1,
            game_id=game_id,
            sportsbook_id=1,
            market_type="h2h",
            selection_name="Kansas City Royals",
            line_value=None,
            price=105,
            snapshot_time=snapshot_time,
        ),
        MarketSnapshot(
            odds_market_snapshot_id=2,
            game_id=game_id,
            sportsbook_id=1,
            market_type="h2h",
            selection_name="Minnesota Twins",
            line_value=None,
            price=-115,
            snapshot_time=snapshot_time,
        ),
        MarketSnapshot(
            odds_market_snapshot_id=3,
            game_id=game_id,
            sportsbook_id=2,
            market_type="h2h",
            selection_name="Kansas City Royals",
            line_value=None,
            price=110,
            snapshot_time=snapshot_time,
        ),
        MarketSnapshot(
            odds_market_snapshot_id=4,
            game_id=game_id,
            sportsbook_id=2,
            market_type="h2h",
            selection_name="Minnesota Twins",
            line_value=None,
            price=-120,
            snapshot_time=snapshot_time,
        ),
    )
