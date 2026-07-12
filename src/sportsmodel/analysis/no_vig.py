from sportsmodel.analysis.probability import (
    american_to_implied_probability,
    remove_vig,
)
from sportsmodel.models import (
    CompleteMarket,
    NoVigMarket,
    NoVigSelection,
)


def calculate_no_vig_market(
    market: CompleteMarket,
) -> NoVigMarket:
    """
    Remove sportsbook vig from one complete market.

    Each selection's implied probability is calculated from its
    American odds, then normalized so the resulting no-vig
    probabilities sum to 1.0.
    """

    implied_probabilities = [
        american_to_implied_probability(selection.price)
        for selection in market.selections
    ]

    no_vig_probabilities = remove_vig(
        implied_probabilities
    )

    selections = tuple(
        NoVigSelection(
            odds_market_snapshot_id=selection.odds_market_snapshot_id,
            selection_name=selection.selection_name,
            line_value=selection.line_value,
            price=selection.price,
            implied_probability=implied_probability,
            no_vig_probability=no_vig_probability,
        )
        for (
            selection,
            implied_probability,
            no_vig_probability,
        ) in zip(
            market.selections,
            implied_probabilities,
            no_vig_probabilities,
            strict=True,
        )
    )

    return NoVigMarket(
        game_id=market.game_id,
        sportsbook_id=market.sportsbook_id,
        market_type=market.market_type,
        line_value=market.line_value,
        snapshot_time=market.snapshot_time,
        selections=selections,
    )


def calculate_no_vig_markets(
    markets: list[CompleteMarket],
) -> list[NoVigMarket]:
    """
    Remove vig from multiple complete markets.
    """

    return [
        calculate_no_vig_market(market)
        for market in markets
    ]