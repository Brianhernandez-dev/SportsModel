from datetime import datetime, timezone
from decimal import Decimal

from sportsmodel.analysis.line_movement import calculate_line_movements
from sportsmodel.models import MarketSnapshot


def test_calculates_opening_to_latest_movement():
    snapshots = [
        MarketSnapshot(
            odds_market_snapshot_id=1,
            game_id=10,
            sportsbook_id=2,
            market_type="totals",
            selection_name="Over",
            line_value=Decimal("8.0"),
            price=-110,
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
            game_id=10,
            sportsbook_id=2,
            market_type="totals",
            selection_name="Over",
            line_value=Decimal("8.5"),
            price=-120,
            snapshot_time=datetime(
                2026,
                7,
                11,
                19,
                0,
                tzinfo=timezone.utc,
            ),
        ),
    ]

    movements = calculate_line_movements(snapshots)

    assert len(movements) == 1

    movement = movements[0]

    assert movement.opening_line == Decimal("8.0")
    assert movement.latest_line == Decimal("8.5")
    assert movement.line_change == Decimal("0.5")
    assert movement.opening_price == -110
    assert movement.latest_price == -120
    assert movement.price_change == -10
    assert movement.snapshot_count == 2


def test_moneyline_has_no_line_change():
    snapshots = [
        MarketSnapshot(
            odds_market_snapshot_id=1,
            game_id=10,
            sportsbook_id=2,
            market_type="h2h",
            selection_name="Home Team",
            line_value=None,
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
            game_id=10,
            sportsbook_id=2,
            market_type="h2h",
            selection_name="Home Team",
            line_value=None,
            price=-125,
            snapshot_time=datetime(
                2026,
                7,
                11,
                19,
                0,
                tzinfo=timezone.utc,
            ),
        ),
    ]

    movement = calculate_line_movements(snapshots)[0]

    assert movement.opening_line is None
    assert movement.latest_line is None
    assert movement.line_change is None
    assert movement.price_change == -10