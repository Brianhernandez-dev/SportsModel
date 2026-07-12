from datetime import datetime, timezone
from decimal import Decimal

from sportsmodel.analysis.market_timeline import (
    build_market_timelines,
)
from sportsmodel.models import (
    CompleteMarket,
    MarketSnapshot,
)


def make_market(
    *,
    game_id: int = 1,
    sportsbook_id: int = 1,
    market_type: str = "h2h",
    line_value: Decimal | None = None,
    snapshot_hour: int = 10,
    first_price: int = -110,
    second_price: int = -110,
) -> CompleteMarket:
    snapshot_time = datetime(
        2026,
        7,
        12,
        snapshot_hour,
        0,
        tzinfo=timezone.utc,
    )

    if market_type == "totals":
        first_name = "Over"
        second_name = "Under"
        first_line = line_value
        second_line = line_value
    elif market_type == "spreads":
        first_name = "Team A"
        second_name = "Team B"
        first_line = line_value
        second_line = (
            -line_value
            if line_value is not None
            else None
        )
    else:
        first_name = "Team A"
        second_name = "Team B"
        first_line = None
        second_line = None

    first_snapshot = MarketSnapshot(
        odds_market_snapshot_id=(
            game_id * 10000
            + sportsbook_id * 100
            + snapshot_hour * 2
        ),
        game_id=game_id,
        sportsbook_id=sportsbook_id,
        market_type=market_type,
        selection_name=first_name,
        line_value=first_line,
        price=first_price,
        snapshot_time=snapshot_time,
    )

    second_snapshot = MarketSnapshot(
        odds_market_snapshot_id=(
            game_id * 10000
            + sportsbook_id * 100
            + snapshot_hour * 2
            + 1
        ),
        game_id=game_id,
        sportsbook_id=sportsbook_id,
        market_type=market_type,
        selection_name=second_name,
        line_value=second_line,
        price=second_price,
        snapshot_time=snapshot_time,
    )

    return CompleteMarket(
        game_id=game_id,
        sportsbook_id=sportsbook_id,
        market_type=market_type,
        line_value=line_value,
        snapshot_time=snapshot_time,
        selections=(
            first_snapshot,
            second_snapshot,
        ),
    )


def test_groups_markets_into_one_timeline():
    markets = [
        make_market(snapshot_hour=9),
        make_market(snapshot_hour=10),
        make_market(snapshot_hour=11),
    ]

    timelines = build_market_timelines(markets)

    assert len(timelines) == 1
    assert len(timelines[0].markets) == 3


def test_orders_markets_chronologically():
    markets = [
        make_market(snapshot_hour=11),
        make_market(snapshot_hour=9),
        make_market(snapshot_hour=10),
    ]

    timeline = build_market_timelines(markets)[0]

    assert [
        market.snapshot_time.hour
        for market in timeline.markets
    ] == [9, 10, 11]


def test_separates_sportsbooks():
    markets = [
        make_market(
            sportsbook_id=1,
            snapshot_hour=9,
        ),
        make_market(
            sportsbook_id=2,
            snapshot_hour=9,
        ),
    ]

    timelines = build_market_timelines(markets)

    assert len(timelines) == 2
    assert {
        timeline.sportsbook_id
        for timeline in timelines
    } == {1, 2}


def test_separates_games():
    markets = [
        make_market(
            game_id=1,
            snapshot_hour=9,
        ),
        make_market(
            game_id=2,
            snapshot_hour=9,
        ),
    ]

    timelines = build_market_timelines(markets)

    assert len(timelines) == 2
    assert {
        timeline.game_id
        for timeline in timelines
    } == {1, 2}


def test_separates_market_types():
    markets = [
        make_market(
            market_type="h2h",
            snapshot_hour=9,
        ),
        make_market(
            market_type="totals",
            line_value=Decimal("8.5"),
            snapshot_hour=9,
        ),
    ]

    timelines = build_market_timelines(markets)

    assert len(timelines) == 2
    assert {
        timeline.market_type
        for timeline in timelines
    } == {"h2h", "totals"}


def test_line_changes_remain_in_same_timeline():
    markets = [
        make_market(
            market_type="totals",
            line_value=Decimal("8.5"),
            snapshot_hour=9,
        ),
        make_market(
            market_type="totals",
            line_value=Decimal("9.0"),
            snapshot_hour=10,
        ),
    ]

    timelines = build_market_timelines(markets)

    assert len(timelines) == 1
    assert [
        market.line_value
        for market in timelines[0].markets
    ] == [
        Decimal("8.5"),
        Decimal("9.0"),
    ]


def test_empty_input_returns_empty_list():
    assert build_market_timelines([]) == []
