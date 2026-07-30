from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sportsmodel.models.game_result import (
    GameResult,
)
from sportsmodel.models.moneyline_paper_settlement import (
    MoneylinePaperCandidate,
)
from sportsmodel.settlement import (
    moneyline_paper_service as service,
)


SNAPSHOT_TIME = datetime(
    2026,
    7,
    30,
    3,
    2,
    48,
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


def test_settles_completed_candidate(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    persisted = []

    monkeypatch.setattr(
        service,
        "_load_paper_candidates",
        lambda cursor, **kwargs: (
            _candidate(),
        ),
    )

    monkeypatch.setattr(
        service,
        "_load_completed_results",
        lambda cursor, **kwargs: (
            _result(),
        ),
    )

    monkeypatch.setattr(
        service,
        "upsert_moneyline_paper_settlement",
        lambda cursor, settlement: (
            persisted.append(settlement)
            or 81
        ),
    )

    result = (
        service.settle_moneyline_paper_candidate_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            connection_factory=lambda: connection,
        )
    )

    assert result.report.candidates_loaded == 1
    assert result.report.settlements_saved == 1
    assert result.report.pending_candidates == 0
    assert result.report.wins == 1
    assert result.report.profit_units == Decimal(
        "1.19"
    )
    assert result.report.roi == Decimal("1.19")

    assert len(result.settlements) == 1

    assert (
        result.settlements[0]
        .moneyline_paper_candidate_settlement_id
        == 81
    )

    assert len(persisted) == 1
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_unfinished_candidate_remains_pending(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    persisted = []

    monkeypatch.setattr(
        service,
        "_load_paper_candidates",
        lambda cursor, **kwargs: (
            _candidate(),
        ),
    )

    monkeypatch.setattr(
        service,
        "_load_completed_results",
        lambda cursor, **kwargs: (),
    )

    monkeypatch.setattr(
        service,
        "upsert_moneyline_paper_settlement",
        lambda cursor, settlement: (
            persisted.append(settlement)
            or 81
        ),
    )

    result = (
        service.settle_moneyline_paper_candidate_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            connection_factory=lambda: connection,
        )
    )

    assert result.report.candidates_loaded == 1
    assert result.report.settlements_saved == 0
    assert result.report.pending_candidates == 1
    assert result.report.profit_units == Decimal("0")
    assert result.report.roi == Decimal("0")
    assert persisted == []
    assert connection.commits == 1


def test_calculates_multi_candidate_performance(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    candidates = (
        _candidate(
            evaluation_id=71,
            game_id=1,
            selection_name="Away Team",
            price=119,
            model_expected_value="0.10",
        ),
        _candidate(
            evaluation_id=72,
            game_id=2,
            selection_name="Home Team",
            price=-110,
            model_expected_value="0.04",
        ),
    )

    results = (
        _result(
            game_id=1,
            home_score=2,
            away_score=5,
        ),
        _result(
            game_id=2,
            home_score=1,
            away_score=4,
        ),
    )

    monkeypatch.setattr(
        service,
        "_load_paper_candidates",
        lambda cursor, **kwargs: candidates,
    )

    monkeypatch.setattr(
        service,
        "_load_completed_results",
        lambda cursor, **kwargs: results,
    )

    monkeypatch.setattr(
        service,
        "upsert_moneyline_paper_settlement",
        lambda cursor, settlement: (
            settlement
            .moneyline_prediction_market_evaluation_id
        ),
    )

    result = (
        service.settle_moneyline_paper_candidate_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            connection_factory=lambda: connection,
        )
    )

    report = result.report

    assert report.wins == 1
    assert report.losses == 1
    assert report.pushes == 0
    assert report.win_rate == Decimal("0.5")
    assert report.total_staked_units == Decimal("2")
    assert report.profit_units == Decimal("0.19")
    assert report.roi == Decimal("0.095")

    assert (
        report.average_model_expected_value
        == Decimal("0.07")
    )

    assert (
        report.maximum_drawdown_units
        == Decimal("1")
    )


def test_rolls_back_on_invalid_team_match(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    monkeypatch.setattr(
        service,
        "_load_paper_candidates",
        lambda cursor, **kwargs: (
            _candidate(
                selection_name="Unknown Team",
            ),
        ),
    )

    monkeypatch.setattr(
        service,
        "_load_completed_results",
        lambda cursor, **kwargs: (
            _result(),
        ),
    )

    with pytest.raises(
        ValueError,
        match="does not match",
    ):
        service.settle_moneyline_paper_candidate_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            connection_factory=lambda: connection,
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed is True


def test_rejects_invalid_arguments() -> None:
    with pytest.raises(
        ValueError,
        match="Prediction run ID",
    ):
        service.settle_moneyline_paper_candidate_run(
            prediction_run_id=0,
            odds_ingestion_run_id=181,
        )

    with pytest.raises(
        ValueError,
        match="Policy version",
    ):
        service.settle_moneyline_paper_candidate_run(
            prediction_run_id=1,
            odds_ingestion_run_id=181,
            policy_version=" ",
        )


def _candidate(
    *,
    evaluation_id: int = 71,
    game_id: int = 1,
    selection_name: str = "Away Team",
    price: int = 119,
    model_expected_value: str = "0.10",
) -> MoneylinePaperCandidate:
    return MoneylinePaperCandidate(
        moneyline_prediction_market_evaluation_id=(
            evaluation_id
        ),
        game_id=game_id,
        selection_name=selection_name,
        snapshot_time=SNAPSHOT_TIME,
        price=price,
        model_probability=Decimal("0.55"),
        model_expected_value=Decimal(
            model_expected_value
        ),
    )


def _result(
    *,
    game_id: int = 1,
    home_score: int = 2,
    away_score: int = 5,
) -> GameResult:
    return GameResult(
        game_id=game_id,
        home_team="Home Team",
        away_team="Away Team",
        home_score=home_score,
        away_score=away_score,
    )
