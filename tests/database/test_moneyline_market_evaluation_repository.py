from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sportsmodel.database.moneyline_market_evaluation_repository import (
    upsert_moneyline_market_evaluation,
)
from sportsmodel.models.moneyline_market_evaluation import (
    MoneylineModelMarketEvaluation,
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
        returned_row=(71,),
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


def test_upserts_evaluation_and_returns_identifier() -> None:
    cursor = FakeCursor()

    evaluation_id = (
        upsert_moneyline_market_evaluation(
            cursor,
            moneyline_game_prediction_id=11,
            odds_ingestion_run_id=181,
            evaluation=_evaluation(),
        )
    )

    assert evaluation_id == 71

    assert (
        "ON CONFLICT"
        in cursor.executed_query
    )

    assert (
        "RETURNING"
        in cursor.executed_query
    )

    parameters = (
        cursor.executed_parameters
    )

    assert parameters[0] == 11
    assert parameters[1] == 181
    assert parameters[2] == 901
    assert parameters[3] == 5
    assert parameters[4] == SNAPSHOT_TIME
    assert parameters[5] == "Kansas City Royals"
    assert parameters[6] == 119
    assert parameters[7] == Decimal("0.5111")
    assert parameters[8] == Decimal("0.4440")
    assert parameters[9] == 5
    assert parameters[13] == Decimal("0.119309")
    assert parameters[17] == "1.0.0"
    assert parameters[18] is True
    assert parameters[19] == []


def test_persists_disqualification_reasons_as_array() -> None:
    cursor = FakeCursor()

    upsert_moneyline_market_evaluation(
        cursor,
        moneyline_game_prediction_id=11,
        odds_ingestion_run_id=181,
        evaluation=_evaluation(
            qualifies=False,
            reasons=(
                "incomplete_starter_coverage",
                "incomplete_starter_features",
            ),
        ),
    )

    assert cursor.executed_parameters[18] is False

    assert cursor.executed_parameters[19] == [
        "incomplete_starter_coverage",
        "incomplete_starter_features",
    ]


def test_rejects_nonpositive_identifiers() -> None:
    cursor = FakeCursor()

    with pytest.raises(
        ValueError,
        match="prediction ID",
    ):
        upsert_moneyline_market_evaluation(
            cursor,
            moneyline_game_prediction_id=0,
            odds_ingestion_run_id=181,
            evaluation=_evaluation(),
        )

    with pytest.raises(
        ValueError,
        match="Odds ingestion run ID",
    ):
        upsert_moneyline_market_evaluation(
            cursor,
            moneyline_game_prediction_id=11,
            odds_ingestion_run_id=-1,
            evaluation=_evaluation(),
        )


def test_raises_when_upsert_returns_no_row() -> None:
    cursor = FakeCursor(
        returned_row=None
    )

    with pytest.raises(
        RuntimeError,
        match="returned no row",
    ):
        upsert_moneyline_market_evaluation(
            cursor,
            moneyline_game_prediction_id=11,
            odds_ingestion_run_id=181,
            evaluation=_evaluation(),
        )


def _evaluation(
    *,
    qualifies: bool = True,
    reasons: tuple[str, ...] = (),
) -> MoneylineModelMarketEvaluation:
    return MoneylineModelMarketEvaluation(
        odds_market_snapshot_id=901,
        game_id=8066,
        sportsbook_id=5,
        snapshot_time=SNAPSHOT_TIME,
        selection_name="Kansas City Royals",
        price=119,
        model_probability=Decimal("0.5111"),
        market_no_vig_probability=(
            Decimal("0.4440")
        ),
        sportsbook_count=5,
        implied_probability=(
            Decimal("0.4566210046")
        ),
        model_market_edge=(
            Decimal("0.0671")
        ),
        model_price_edge=(
            Decimal("0.0544789954")
        ),
        model_expected_value=(
            Decimal("0.119309")
        ),
        starter_coverage="both",
        home_starter_features_available=True,
        away_starter_features_available=True,
        policy_version="1.0.0",
        qualifies_as_paper_candidate=(
            qualifies
        ),
        disqualification_reasons=reasons,
    )
