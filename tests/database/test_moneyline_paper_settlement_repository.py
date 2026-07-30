from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sportsmodel.database.moneyline_paper_settlement_repository import (
    upsert_moneyline_paper_settlement,
)
from sportsmodel.models.moneyline_paper_settlement import (
    MoneylinePaperSettlement,
)
from sportsmodel.models.settled_bet import (
    BetOutcome,
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
    def __init__(
        self,
        *,
        returned_row=(81,),
    ) -> None:
        self.returned_row = returned_row
        self.executed_query = None
        self.executed_parameters = None

    def execute(
        self,
        query,
        parameters,
    ) -> None:
        self.executed_query = query
        self.executed_parameters = parameters

    def fetchone(self):
        return self.returned_row


def test_upserts_settlement_and_returns_identifier() -> None:
    cursor = FakeCursor()

    settlement_id = (
        upsert_moneyline_paper_settlement(
            cursor,
            _settlement(),
        )
    )

    assert settlement_id == 81

    assert "ON CONFLICT" in cursor.executed_query
    assert "RETURNING" in cursor.executed_query

    parameters = cursor.executed_parameters

    assert parameters[0] == 71
    assert parameters[1] == 8066
    assert parameters[2] == 5
    assert parameters[3] == 3
    assert parameters[4] == "win"
    assert parameters[5] == Decimal("1.19")


def test_persists_loss_outcome() -> None:
    cursor = FakeCursor()

    upsert_moneyline_paper_settlement(
        cursor,
        _settlement(
            outcome=BetOutcome.LOSS,
            profit_units=Decimal("-1"),
        ),
    )

    assert cursor.executed_parameters[4] == "loss"
    assert (
        cursor.executed_parameters[5]
        == Decimal("-1")
    )


def test_rejects_invalid_identifiers_and_scores() -> None:
    cursor = FakeCursor()

    with pytest.raises(
        ValueError,
        match="evaluation ID",
    ):
        upsert_moneyline_paper_settlement(
            cursor,
            _settlement(
                evaluation_id=0,
            ),
        )

    with pytest.raises(
        ValueError,
        match="Game ID",
    ):
        upsert_moneyline_paper_settlement(
            cursor,
            _settlement(
                game_id=0,
            ),
        )

    with pytest.raises(
        ValueError,
        match="Home score",
    ):
        upsert_moneyline_paper_settlement(
            cursor,
            _settlement(
                home_score=-1,
            ),
        )

    with pytest.raises(
        ValueError,
        match="Away score",
    ):
        upsert_moneyline_paper_settlement(
            cursor,
            _settlement(
                away_score=-1,
            ),
        )


def test_raises_when_upsert_returns_no_row() -> None:
    cursor = FakeCursor(
        returned_row=None
    )

    with pytest.raises(
        RuntimeError,
        match="returned no row",
    ):
        upsert_moneyline_paper_settlement(
            cursor,
            _settlement(),
        )


def _settlement(
    *,
    evaluation_id: int = 71,
    game_id: int = 8066,
    home_score: int = 5,
    away_score: int = 3,
    outcome: BetOutcome = BetOutcome.WIN,
    profit_units: Decimal = Decimal("1.19"),
) -> MoneylinePaperSettlement:
    return MoneylinePaperSettlement(
        moneyline_prediction_market_evaluation_id=(
            evaluation_id
        ),
        game_id=game_id,
        selection_name="Kansas City Royals",
        snapshot_time=SNAPSHOT_TIME,
        price=119,
        model_probability=Decimal("0.5111"),
        model_expected_value=Decimal("0.1193"),
        home_team_name="Minnesota Twins",
        away_team_name="Kansas City Royals",
        home_score=home_score,
        away_score=away_score,
        outcome=outcome,
        profit_units=profit_units,
    )
