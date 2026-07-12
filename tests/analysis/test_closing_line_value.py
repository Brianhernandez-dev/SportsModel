from datetime import datetime, timezone
from decimal import Decimal

from sportsmodel.analysis.closing_line_value import (
    calculate_closing_line_value_markets,
)
from sportsmodel.models import (
    CompleteMarket,
    MarketSnapshot,
    MarketTimeline,
)


def make_market(
    *,
    snapshot_hour: int,
    market_type: str = "h2h",
    first_line: Decimal | None = None,
    second_line: Decimal | None = None,
    first_price: int = 150,
    second_price: int = -170,
    first_name: str = "Team A",
    second_name: str = "Team B",
) -> CompleteMarket:
    snapshot_time = datetime(
        2026,
        7,
        12,
        snapshot_hour,
        0,
        tzinfo=timezone.utc,
    )

    first = MarketSnapshot(
        odds_market_snapshot_id=snapshot_hour * 2,
        game_id=1,
        sportsbook_id=1,
        market_type=market_type,
        selection_name=first_name,
        line_value=first_line,
        price=first_price,
        snapshot_time=snapshot_time,
    )

    second = MarketSnapshot(
        odds_market_snapshot_id=snapshot_hour * 2 + 1,
        game_id=1,
        sportsbook_id=1,
        market_type=market_type,
        selection_name=second_name,
        line_value=second_line,
        price=second_price,
        snapshot_time=snapshot_time,
    )

    return CompleteMarket(
        game_id=1,
        sportsbook_id=1,
        market_type=market_type,
        line_value=first_line,
        snapshot_time=snapshot_time,
        selections=(first, second),
    )


def make_timeline(
    markets: tuple[CompleteMarket, ...],
    market_type: str = "h2h",
) -> MarketTimeline:
    return MarketTimeline(
        game_id=1,
        sportsbook_id=1,
        market_type=market_type,
        markets=markets,
    )


def test_requires_at_least_two_markets():
    timeline = make_timeline(
        (
            make_market(snapshot_hour=10),
        )
    )

    result = calculate_closing_line_value_markets(
        [timeline]
    )

    assert result == []


def test_two_markets_produce_one_clv_market():
    timeline = make_timeline(
        (
            make_market(snapshot_hour=10),
            make_market(snapshot_hour=12),
        )
    )

    result = calculate_closing_line_value_markets(
        [timeline]
    )

    assert len(result) == 1
    assert result[0].bet_snapshot_time.hour == 10
    assert result[0].closing_snapshot_time.hour == 12


def test_every_preclosing_market_becomes_a_bet_point():
    timeline = make_timeline(
        (
            make_market(snapshot_hour=9),
            make_market(snapshot_hour=10),
            make_market(snapshot_hour=11),
            make_market(snapshot_hour=12),
        )
    )

    result = calculate_closing_line_value_markets(
        [timeline]
    )

    assert len(result) == 3
    assert [
        market.bet_snapshot_time.hour
        for market in result
    ] == [9, 10, 11]

    assert all(
        market.closing_snapshot_time.hour == 12
        for market in result
    )


def test_uses_latest_market_as_close_even_when_unsorted():
    timeline = make_timeline(
        (
            make_market(snapshot_hour=12),
            make_market(snapshot_hour=9),
            make_market(snapshot_hour=10),
        )
    )

    result = calculate_closing_line_value_markets(
        [timeline]
    )

    assert len(result) == 2
    assert all(
        market.closing_snapshot_time.hour == 12
        for market in result
    )


def test_moneyline_price_clv_is_calculated():
    bet_market = make_market(
        snapshot_hour=10,
        first_price=150,
    )
    closing_market = make_market(
        snapshot_hour=12,
        first_price=100,
    )

    timeline = make_timeline(
        (bet_market, closing_market)
    )

    result = calculate_closing_line_value_markets(
        [timeline]
    )

    selection = result[0].selections[0]

    assert selection.is_price_comparable is True
    assert selection.probability_clv == Decimal("0.1")
    assert selection.decimal_odds_clv == Decimal("0.25")


def test_same_line_total_has_price_clv():
    bet_market = make_market(
        snapshot_hour=10,
        market_type="totals",
        first_name="Over",
        second_name="Under",
        first_line=Decimal("8.5"),
        second_line=Decimal("8.5"),
        first_price=150,
    )
    closing_market = make_market(
        snapshot_hour=12,
        market_type="totals",
        first_name="Over",
        second_name="Under",
        first_line=Decimal("8.5"),
        second_line=Decimal("8.5"),
        first_price=100,
    )

    timeline = make_timeline(
        (bet_market, closing_market),
        market_type="totals",
    )

    result = calculate_closing_line_value_markets(
        [timeline]
    )

    selection = result[0].selections[0]

    assert selection.is_price_comparable is True
    assert selection.line_change == Decimal("0.0")
    assert selection.probability_clv == Decimal("0.1")
    assert selection.decimal_odds_clv == Decimal("0.25")


def test_changed_line_is_not_price_comparable():
    bet_market = make_market(
        snapshot_hour=10,
        market_type="totals",
        first_name="Over",
        second_name="Under",
        first_line=Decimal("7.0"),
        second_line=Decimal("7.0"),
        first_price=-103,
    )
    closing_market = make_market(
        snapshot_hour=12,
        market_type="totals",
        first_name="Over",
        second_name="Under",
        first_line=Decimal("7.5"),
        second_line=Decimal("7.5"),
        first_price=-111,
    )

    timeline = make_timeline(
        (bet_market, closing_market),
        market_type="totals",
    )

    result = calculate_closing_line_value_markets(
        [timeline]
    )

    selection = result[0].selections[0]

    assert selection.line_change == Decimal("0.5")
    assert selection.is_price_comparable is False
    assert selection.probability_clv is None
    assert selection.decimal_odds_clv is None


def test_selection_sets_must_match():
    bet_market = make_market(
        snapshot_hour=10,
        first_name="Team A",
        second_name="Team B",
    )
    closing_market = make_market(
        snapshot_hour=12,
        first_name="Team A",
        second_name="Team C",
    )

    timeline = make_timeline(
        (bet_market, closing_market)
    )

    result = calculate_closing_line_value_markets(
        [timeline]
    )

    assert result == []


def test_empty_input_returns_empty_list():
    assert calculate_closing_line_value_markets([]) == []


def test_favorite_flip_records_line_change_without_price_clv():
    bet_market = make_market(
        snapshot_hour=10,
        market_type="spreads",
        first_name="Team A",
        second_name="Team B",
        first_line=Decimal("1.5"),
        second_line=Decimal("-1.5"),
        first_price=-199,
        second_price=167,
    )
    closing_market = make_market(
        snapshot_hour=12,
        market_type="spreads",
        first_name="Team A",
        second_name="Team B",
        first_line=Decimal("-1.5"),
        second_line=Decimal("1.5"),
        first_price=159,
        second_price=-189,
    )

    timeline = make_timeline(
        (bet_market, closing_market),
        market_type="spreads",
    )

    result = calculate_closing_line_value_markets(
        [timeline]
    )

    selections = {
        selection.selection_name: selection
        for selection in result[0].selections
    }

    assert selections["Team A"].line_change == Decimal("-3.0")
    assert selections["Team B"].line_change == Decimal("3.0")

    assert selections["Team A"].is_price_comparable is False
    assert selections["Team B"].is_price_comparable is False

    assert selections["Team A"].probability_clv is None
    assert selections["Team A"].decimal_odds_clv is None
