from collections.abc import Iterable
from decimal import Decimal

from sportsmodel.analysis.probability import (
    american_to_decimal_odds,
    american_to_implied_probability,
)
from sportsmodel.models import (
    ClosingLineValueMarket,
    ClosingLineValueSelection,
    CompleteMarket,
    MarketSnapshot,
    MarketTimeline,
)


def calculate_closing_line_value_markets(
    timelines: Iterable[MarketTimeline],
) -> list[ClosingLineValueMarket]:
    """
    Compare every historical market in a timeline against its close.

    The final complete market in each timeline is treated as the closing
    market. Every earlier complete market is treated as a possible
    historical bet point.

    Price CLV is calculated only when the selection's bet line and
    closing line are identical. Different lines represent different
    betting contracts and must not be directly compared by price.
    """

    clv_markets: list[ClosingLineValueMarket] = []

    for timeline in timelines:
        ordered_markets = sorted(
            timeline.markets,
            key=lambda market: market.snapshot_time,
        )

        if len(ordered_markets) < 2:
            continue

        closing_market = ordered_markets[-1]

        for bet_market in ordered_markets[:-1]:
            clv_market = _compare_markets(
                timeline=timeline,
                bet_market=bet_market,
                closing_market=closing_market,
            )

            if clv_market is not None:
                clv_markets.append(clv_market)

    clv_markets.sort(
        key=lambda market: (
            market.bet_snapshot_time,
            market.game_id,
            market.sportsbook_id,
            market.market_type,
        )
    )

    return clv_markets


def _compare_markets(
    timeline: MarketTimeline,
    bet_market: CompleteMarket,
    closing_market: CompleteMarket,
) -> ClosingLineValueMarket | None:
    """
    Compare one historical sportsbook market with its closing market.

    A comparison is returned only when the same selection names exist in
    both complete markets.
    """

    closing_by_selection = {
        selection.selection_name: selection
        for selection in closing_market.selections
    }

    bet_selection_names = {
        selection.selection_name
        for selection in bet_market.selections
    }

    if bet_selection_names != set(closing_by_selection):
        return None

    selections: list[ClosingLineValueSelection] = []

    for bet_selection in bet_market.selections:
        closing_selection = closing_by_selection[
            bet_selection.selection_name
        ]

        selections.append(
            _compare_selections(
                sportsbook_id=timeline.sportsbook_id,
                bet_selection=bet_selection,
                closing_selection=closing_selection,
            )
        )

    return ClosingLineValueMarket(
        game_id=timeline.game_id,
        sportsbook_id=timeline.sportsbook_id,
        market_type=timeline.market_type,
        bet_snapshot_time=bet_market.snapshot_time,
        closing_snapshot_time=closing_market.snapshot_time,
        selections=tuple(selections),
    )


def _compare_selections(
    sportsbook_id: int,
    bet_selection: MarketSnapshot,
    closing_selection: MarketSnapshot,
) -> ClosingLineValueSelection:
    """
    Compare one selection at bet time with the same selection at close.
    """

    bet_probability = american_to_implied_probability(
        bet_selection.price
    )
    closing_probability = american_to_implied_probability(
        closing_selection.price
    )

    line_change = _calculate_line_change(
        bet_selection.line_value,
        closing_selection.line_value,
    )

    is_price_comparable = (
        bet_selection.line_value
        == closing_selection.line_value
    )

    probability_clv: Decimal | None = None
    decimal_odds_clv: Decimal | None = None

    if is_price_comparable:
        probability_clv = (
            closing_probability - bet_probability
        )

        bet_decimal_odds = american_to_decimal_odds(
            bet_selection.price
        )
        closing_decimal_odds = american_to_decimal_odds(
            closing_selection.price
        )

        decimal_odds_clv = (
            bet_decimal_odds / closing_decimal_odds
        ) - Decimal(1)

    return ClosingLineValueSelection(
        odds_market_snapshot_id=(
            bet_selection.odds_market_snapshot_id
        ),
        selection_name=bet_selection.selection_name,
        sportsbook_id=sportsbook_id,
        bet_line=bet_selection.line_value,
        closing_line=closing_selection.line_value,
        line_change=line_change,
        bet_price=bet_selection.price,
        closing_price=closing_selection.price,
        bet_implied_probability=bet_probability,
        closing_implied_probability=closing_probability,
        probability_clv=probability_clv,
        decimal_odds_clv=decimal_odds_clv,
        is_price_comparable=is_price_comparable,
    )


def _calculate_line_change(
    bet_line: Decimal | None,
    closing_line: Decimal | None,
) -> Decimal | None:
    """
    Return raw closing-line movement.

    The result is closing line minus bet line. It is deliberately not
    labeled favorable or unfavorable because interpretation depends on
    the market type and selection.
    """

    if bet_line is None or closing_line is None:
        return None

    return closing_line - bet_line
