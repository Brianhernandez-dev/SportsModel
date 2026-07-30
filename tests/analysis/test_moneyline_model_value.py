from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sportsmodel.analysis.moneyline_model_value import (
    evaluate_moneyline_model_value,
)
from sportsmodel.models.consensus_market import (
    ConsensusMarket,
    ConsensusSelection,
)
from sportsmodel.models.moneyline_market_evaluation import (
    MoneylinePredictionMarketContext,
)
from sportsmodel.models.snapshot import (
    MarketSnapshot,
)


SNAPSHOT_TIME = datetime(
    2026,
    7,
    30,
    3,
    2,
    tzinfo=timezone.utc,
)


def test_qualifies_positive_model_value() -> None:
    result = evaluate_moneyline_model_value(
        prediction=_prediction(
            model_probability="0.5111",
        ),
        consensus_market=_consensus_market(
            consensus_probability="0.4440",
            sportsbook_count=5,
        ),
        snapshots=[
            _snapshot(
                snapshot_id=1,
                sportsbook_id=1,
                price=115,
            ),
            _snapshot(
                snapshot_id=2,
                sportsbook_id=2,
                price=119,
            ),
        ],
    )

    assert result.odds_market_snapshot_id == 2
    assert result.sportsbook_id == 2
    assert result.price == 119

    assert (
        result.model_market_edge
        == Decimal("0.0671")
    )

    assert (
        result.model_expected_value
        == (
            Decimal("0.5111")
            * Decimal("2.19")
            - Decimal("1")
        )
    )

    assert (
        result.qualifies_as_paper_candidate
        is True
    )

    assert result.disqualification_reasons == ()


def test_selects_best_negative_price() -> None:
    result = evaluate_moneyline_model_value(
        prediction=_prediction(
            model_probability="0.58",
        ),
        consensus_market=_consensus_market(
            consensus_probability="0.53",
            sportsbook_count=6,
        ),
        snapshots=[
            _snapshot(
                snapshot_id=1,
                sportsbook_id=1,
                price=-125,
            ),
            _snapshot(
                snapshot_id=2,
                sportsbook_id=2,
                price=-118,
            ),
        ],
    )

    assert result.price == -118
    assert result.odds_market_snapshot_id == 2


def test_partial_starter_coverage_is_disqualified() -> None:
    result = evaluate_moneyline_model_value(
        prediction=_prediction(
            model_probability="0.58",
            starter_coverage="partial",
            away_features_available=False,
        ),
        consensus_market=_consensus_market(
            consensus_probability="0.53",
            sportsbook_count=6,
        ),
        snapshots=[
            _snapshot(
                snapshot_id=1,
                sportsbook_id=1,
                price=-118,
            ),
        ],
    )

    assert (
        result.qualifies_as_paper_candidate
        is False
    )

    assert (
        "incomplete_starter_coverage"
        in result.disqualification_reasons
    )

    assert (
        "incomplete_starter_features"
        in result.disqualification_reasons
    )


def test_low_value_and_low_book_count_are_disqualified() -> None:
    result = evaluate_moneyline_model_value(
        prediction=_prediction(
            model_probability="0.50",
        ),
        consensus_market=_consensus_market(
            consensus_probability="0.51",
            sportsbook_count=4,
        ),
        snapshots=[
            _snapshot(
                snapshot_id=1,
                sportsbook_id=1,
                price=-110,
            ),
        ],
    )

    assert (
        result.qualifies_as_paper_candidate
        is False
    )

    assert result.disqualification_reasons == (
        "model_expected_value_below_minimum",
        "model_market_edge_below_minimum",
        "insufficient_sportsbook_count",
    )


def test_rejects_mismatched_game() -> None:
    consensus_market = _consensus_market(
        consensus_probability="0.50",
        sportsbook_count=5,
    )

    consensus_market = ConsensusMarket(
        game_id=999,
        market_type=(
            consensus_market.market_type
        ),
        line_value=(
            consensus_market.line_value
        ),
        snapshot_time=(
            consensus_market.snapshot_time
        ),
        selections=(
            consensus_market.selections
        ),
    )

    with pytest.raises(
        ValueError,
        match="game IDs",
    ):
        evaluate_moneyline_model_value(
            prediction=_prediction(
                model_probability="0.55",
            ),
            consensus_market=(
                consensus_market
            ),
            snapshots=[],
        )


def test_requires_stored_price_for_selection() -> None:
    with pytest.raises(
        LookupError,
        match="No matching stored",
    ):
        evaluate_moneyline_model_value(
            prediction=_prediction(
                model_probability="0.55",
            ),
            consensus_market=(
                _consensus_market(
                    consensus_probability="0.50",
                    sportsbook_count=5,
                )
            ),
            snapshots=[],
        )


def _prediction(
    *,
    model_probability: str,
    starter_coverage: str = "both",
    home_features_available: bool = True,
    away_features_available: bool = True,
) -> MoneylinePredictionMarketContext:
    return MoneylinePredictionMarketContext(
        game_id=101,
        selection_name="Kansas City Royals",
        model_probability=Decimal(
            model_probability
        ),
        starter_coverage=starter_coverage,
        home_starter_features_available=(
            home_features_available
        ),
        away_starter_features_available=(
            away_features_available
        ),
    )


def _consensus_market(
    *,
    consensus_probability: str,
    sportsbook_count: int,
) -> ConsensusMarket:
    return ConsensusMarket(
        game_id=101,
        market_type="h2h",
        line_value=None,
        snapshot_time=SNAPSHOT_TIME,
        selections=(
            ConsensusSelection(
                selection_name=(
                    "Kansas City Royals"
                ),
                line_value=None,
                consensus_probability=Decimal(
                    consensus_probability
                ),
                sportsbook_count=(
                    sportsbook_count
                ),
            ),
            ConsensusSelection(
                selection_name=(
                    "Minnesota Twins"
                ),
                line_value=None,
                consensus_probability=(
                    Decimal("1")
                    - Decimal(
                        consensus_probability
                    )
                ),
                sportsbook_count=(
                    sportsbook_count
                ),
            ),
        ),
    )


def _snapshot(
    *,
    snapshot_id: int,
    sportsbook_id: int,
    price: int,
) -> MarketSnapshot:
    return MarketSnapshot(
        odds_market_snapshot_id=(
            snapshot_id
        ),
        game_id=101,
        sportsbook_id=sportsbook_id,
        market_type="h2h",
        selection_name="Kansas City Royals",
        line_value=None,
        price=price,
        snapshot_time=SNAPSHOT_TIME,
    )
