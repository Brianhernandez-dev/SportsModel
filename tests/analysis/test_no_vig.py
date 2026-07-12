from datetime import datetime, timezone
from decimal import Decimal

from sportsmodel.analysis.no_vig import calculate_no_vig_market
from sportsmodel.models import CompleteMarket, MarketSnapshot


def make_snapshot(
    snapshot_id: int,
    selection_name: str,
    price: int,
    line_value: Decimal | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(
        odds_market_snapshot_id=snapshot_id,
        game_id=10,
        sportsbook_id=2,
        market_type="h2h",
        selection_name=selection_name,
        line_value=line_value,
        price=price,
        snapshot_time=datetime(
            2026,
            7,
            11,
            18,
            0,
            tzinfo=timezone.utc,
        ),
    )


def test_calculates_even_no_vig_market():
    market = CompleteMarket(
        game_id=10,
        sportsbook_id=2,
        market_type="h2h",
        line_value=None,
        snapshot_time=datetime(
            2026,
            7,
            11,
            18,
            0,
            tzinfo=timezone.utc,
        ),
        selections=(
            make_snapshot(1, "Team A", -110),
            make_snapshot(2, "Team B", -110),
        ),
    )

    result = calculate_no_vig_market(market)

    assert len(result.selections) == 2

    assert result.selections[0].no_vig_probability.quantize(
        Decimal("0.000001")
    ) == Decimal("0.500000")

    assert result.selections[1].no_vig_probability.quantize(
        Decimal("0.000001")
    ) == Decimal("0.500000")


def test_no_vig_probabilities_sum_to_one():
    market = CompleteMarket(
        game_id=10,
        sportsbook_id=2,
        market_type="h2h",
        line_value=None,
        snapshot_time=datetime(
            2026,
            7,
            11,
            18,
            0,
            tzinfo=timezone.utc,
        ),
        selections=(
            make_snapshot(1, "Team A", -135),
            make_snapshot(2, "Team B", 115),
        ),
    )

    result = calculate_no_vig_market(market)

    total = sum(
        selection.no_vig_probability
        for selection in result.selections
    )

    assert total.quantize(
        Decimal("0.000001")
    ) == Decimal("1.000000")


def test_preserves_market_identity():
    market = CompleteMarket(
        game_id=42,
        sportsbook_id=8,
        market_type="totals",
        line_value=Decimal("8.5"),
        snapshot_time=datetime(
            2026,
            7,
            11,
            18,
            0,
            tzinfo=timezone.utc,
        ),
        selections=(
            MarketSnapshot(
                odds_market_snapshot_id=1,
                game_id=42,
                sportsbook_id=8,
                market_type="totals",
                selection_name="Over",
                line_value=Decimal("8.5"),
                price=-115,
                snapshot_time=datetime(
                    2026,
                    7,
                    11,
                    18,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            MarketSnapshot(
                odds_market_snapshot_id=2,
                game_id=42,
                sportsbook_id=8,
                market_type="totals",
                selection_name="Under",
                line_value=Decimal("8.5"),
                price=-105,
                snapshot_time=datetime(
                    2026,
                    7,
                    11,
                    18,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
        ),
    )

    result = calculate_no_vig_market(market)

    assert result.game_id == 42
    assert result.sportsbook_id == 8
    assert result.market_type == "totals"
    assert result.line_value == Decimal("8.5")