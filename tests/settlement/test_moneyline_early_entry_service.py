from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from sportsmodel.models.game_result import GameResult
from sportsmodel.models.moneyline_paper_settlement import (
    MoneylinePaperCandidate,
)
from sportsmodel.settlement import (
    moneyline_early_entry_service as early_entry_service,
)
from sportsmodel.settlement import (
    moneyline_paper_service,
)


TARGET_DATE = date(2026, 8, 12)
SNAPSHOT_TIME = datetime(
    2026,
    8,
    12,
    5,
    0,
    tzinfo=timezone.utc,
)


class FakeCursor:
    def __init__(self, row) -> None:
        self.row = row
        self.query = None
        self.parameters = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, parameters) -> None:
        self.query = query
        self.parameters = parameters

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.row


class FakeConnection:
    def __init__(self, row) -> None:
        self.cursor_instance = FakeCursor(row)
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


class ConnectionQueue:
    def __init__(self, *rows) -> None:
        self.connections = [
            FakeConnection(row)
            for row in rows
        ]

    def __call__(self):
        return self.connections.pop(0)


def test_settles_identified_early_entry_cohort() -> None:
    connection_factory = ConnectionQueue(
        ((44, 211),),
        (2, 2, 1, 1, 0, Decimal("0.19")),
    )
    calls = []
    settlement_result = SimpleNamespace()

    result = early_entry_service.settle_moneyline_early_entry(
        target_date=TARGET_DATE,
        connection_factory=connection_factory,
        settlement_runner=lambda **arguments: (
            calls.append(arguments)
            or settlement_result
        ),
    )

    assert calls == [
        {
            "prediction_run_id": 44,
            "odds_ingestion_run_id": 211,
            "connection_factory": connection_factory,
        }
    ]
    assert len(result.cohort_settlements) == 1
    assert (
        result.cohort_settlements[0].settlement_result
        is settlement_result
    )
    assert result.performance.wins == 1
    assert result.performance.losses == 1
    assert result.performance.pending == 0
    assert result.performance.profit_units == Decimal("0.19")
    assert result.performance.roi == Decimal("0.095")


def test_missing_early_entry_cohort_is_safe_noop() -> None:
    connection_factory = ConnectionQueue(
        (),
        (0, 0, 0, 0, 0, Decimal("0")),
    )
    calls = []

    result = early_entry_service.settle_moneyline_early_entry(
        target_date=TARGET_DATE,
        connection_factory=connection_factory,
        settlement_runner=lambda **arguments: calls.append(arguments),
    )

    assert calls == []
    assert result.cohort_settlements == ()
    assert result.performance.total_qualified_bets == 0


def test_qualified_early_entry_without_result_remains_pending() -> None:
    connection_factory = ConnectionQueue(
        ((44, 211),),
        (1, 0, 0, 0, 0, Decimal("0")),
    )

    result = early_entry_service.settle_moneyline_early_entry(
        target_date=TARGET_DATE,
        connection_factory=connection_factory,
        settlement_runner=lambda **arguments: SimpleNamespace(
            report=SimpleNamespace(pending_candidates=1),
        ),
    )

    assert result.performance.total_qualified_bets == 1
    assert result.performance.settled_bets == 0
    assert result.performance.pending == 1
    assert result.performance.profit_units == Decimal("0")
    assert result.performance.roi == Decimal("0")


def test_performance_isolated_to_preview_late_night() -> None:
    connection = FakeConnection(
        (3, 2, 1, 1, 0, Decimal("0.50"))
    )

    report = (
        early_entry_service
        .load_moneyline_early_entry_performance(
            target_date=TARGET_DATE,
            connection_factory=lambda: connection,
        )
    )

    query = connection.cursor_instance.query

    assert "prediction_run.run_type = 'preview'" in query
    assert "odds_run.snapshot_role = 'late_night'" in query
    assert "odds_run.sport = %s" in query
    assert connection.cursor_instance.parameters == (
        "baseball_mlb",
        TARGET_DATE,
        TARGET_DATE,
    )
    assert "candidate_run" not in query
    assert report.total_qualified_bets == 3
    assert report.settled_bets == 2
    assert report.pending == 1
    assert report.total_staked_units == Decimal("2")
    assert report.profit_units == Decimal("0.50")
    assert report.roi == Decimal("0.25")
    assert connection.closed is True


def test_early_entry_uses_stored_prices_for_win_and_loss(
    monkeypatch,
) -> None:
    candidates = (
        _candidate(71, 1, "Away Team", 150),
        _candidate(72, 2, "Home Team", -125),
    )
    results = (
        _result(1, 2, 5),
        _result(2, 1, 4),
    )
    persisted = []
    connection = _SettlementConnection()

    monkeypatch.setattr(
        moneyline_paper_service,
        "_load_paper_candidates",
        lambda cursor, **arguments: candidates,
    )
    monkeypatch.setattr(
        moneyline_paper_service,
        "_load_completed_results",
        lambda cursor, **arguments: results,
    )
    monkeypatch.setattr(
        moneyline_paper_service,
        "upsert_moneyline_paper_settlement",
        lambda cursor, settlement: (
            persisted.append(settlement)
            or settlement.moneyline_prediction_market_evaluation_id
        ),
    )

    result = moneyline_paper_service.settle_moneyline_paper_candidate_run(
        prediction_run_id=44,
        odds_ingestion_run_id=211,
        connection_factory=lambda: connection,
    )

    assert result.report.wins == 1
    assert result.report.losses == 1
    assert persisted[0].profit_units == Decimal("1.5")
    assert persisted[1].profit_units == Decimal("-1")


def test_official_and_early_entry_settle_independently(
    monkeypatch,
) -> None:
    official_candidate = _candidate(70, 1, "Away Team", -110)
    early_candidate = _candidate(71, 1, "Away Team", 150)
    persisted = {}

    def load_candidates(cursor, *, odds_ingestion_run_id, **arguments):
        if odds_ingestion_run_id == 182:
            return (official_candidate,)
        return (early_candidate,)

    monkeypatch.setattr(
        moneyline_paper_service,
        "_load_paper_candidates",
        load_candidates,
    )
    monkeypatch.setattr(
        moneyline_paper_service,
        "_load_completed_results",
        lambda cursor, **arguments: (_result(1, 2, 5),),
    )
    monkeypatch.setattr(
        moneyline_paper_service,
        "upsert_moneyline_paper_settlement",
        lambda cursor, settlement: (
            persisted.__setitem__(
                settlement.moneyline_prediction_market_evaluation_id,
                settlement,
            )
            or settlement.moneyline_prediction_market_evaluation_id
        ),
    )

    official = moneyline_paper_service.settle_moneyline_paper_candidate_run(
        prediction_run_id=25,
        odds_ingestion_run_id=182,
        connection_factory=_SettlementConnection,
    )
    early = moneyline_paper_service.settle_moneyline_paper_candidate_run(
        prediction_run_id=44,
        odds_ingestion_run_id=211,
        connection_factory=_SettlementConnection,
    )

    assert set(persisted) == {70, 71}
    assert official.report.profit_units == Decimal(
        "0.909090909090909090909090909"
    )
    assert early.report.profit_units == Decimal("1.5")
    assert official.report.candidates_loaded == 1


def test_early_entry_rerun_uses_stable_cohort_identity() -> None:
    calls = []

    for _ in range(2):
        early_entry_service.settle_moneyline_early_entry(
            target_date=TARGET_DATE,
            connection_factory=ConnectionQueue(
                (
                    (43, 210),
                    (44, 211),
                ),
                (2, 2, 2, 0, 0, Decimal("2.5")),
            ),
            settlement_runner=lambda **arguments: (
                calls.append(arguments)
                or SimpleNamespace()
            ),
        )

    assert len(calls) == 4
    assert [
        (
            call["prediction_run_id"],
            call["odds_ingestion_run_id"],
        )
        for call in calls
    ] == [
        (43, 210),
        (44, 211),
        (43, 210),
        (44, 211),
    ]


def test_newer_preview_does_not_replace_persisted_cohort() -> None:
    completed_preview_run_ids = (44, 45)
    connection_factory = ConnectionQueue(
        ((44, 211),),
        (1, 1, 1, 0, 0, Decimal("1.5")),
    )
    discovery_connection = connection_factory.connections[0]
    calls = []

    early_entry_service.settle_moneyline_early_entry(
        target_date=TARGET_DATE,
        connection_factory=connection_factory,
        settlement_runner=lambda **arguments: (
            calls.append(arguments)
            or SimpleNamespace()
        ),
    )

    assert max(completed_preview_run_ids) == 45
    assert (
        calls[0]["prediction_run_id"],
        calls[0]["odds_ingestion_run_id"],
    ) == (44, 211)

    query = discovery_connection.cursor_instance.query

    assert "moneyline_prediction_market_evaluations" in query
    assert "evaluation.qualifies_as_paper_candidate" in query
    assert "odds_run.sport = %s" in query
    assert discovery_connection.cursor_instance.parameters == (
        TARGET_DATE,
        TARGET_DATE,
        "baseball_mlb",
    )
    assert "completed_at" not in query
    assert "LIMIT 1" not in query


class _SettlementConnection:
    def cursor(self):
        return FakeCursor(None)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def _candidate(
    evaluation_id: int,
    game_id: int,
    selection_name: str,
    price: int,
) -> MoneylinePaperCandidate:
    return MoneylinePaperCandidate(
        moneyline_prediction_market_evaluation_id=evaluation_id,
        game_id=game_id,
        selection_name=selection_name,
        snapshot_time=SNAPSHOT_TIME,
        price=price,
        model_probability=Decimal("0.55"),
        model_expected_value=Decimal("0.10"),
    )


def _result(
    game_id: int,
    home_score: int,
    away_score: int,
) -> GameResult:
    return GameResult(
        game_id=game_id,
        home_team="Home Team",
        away_team="Away Team",
        home_score=home_score,
        away_score=away_score,
    )
