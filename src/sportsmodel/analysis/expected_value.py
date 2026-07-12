from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sportsmodel.analysis.probability import (
    american_to_decimal_odds,
)
from sportsmodel.models import (
    ExpectedValueMarket,
    ExpectedValueSelection,
    NoVigMarket,
)


MarketKey = tuple[
    int,
    str,
    Decimal | None,
    datetime,
]

SelectionKey = tuple[
    str,
    Decimal | None,
]


def calculate_expected_value_markets(
    markets: list[NoVigMarket],
) -> list[ExpectedValueMarket]:
    """
    Calculate book-specific expected value using leave-one-out consensus.

    For each sportsbook, fair probability is calculated from all other
    sportsbooks offering the same market at the same snapshot time.

    At least three sportsbooks must exist in the original market group,
    leaving at least two independent reference sportsbooks.
    """

    grouped_markets: dict[
        MarketKey,
        list[NoVigMarket],
    ] = defaultdict(list)

    for market in markets:
        canonical_line = _canonical_market_line(
            market.market_type,
            market.line_value,
        )

        key = (
            market.game_id,
            market.market_type,
            canonical_line,
            market.snapshot_time,
        )

        grouped_markets[key].append(market)

    expected_value_markets: list[ExpectedValueMarket] = []

    for key, market_group in grouped_markets.items():
        sportsbook_ids = {
            market.sportsbook_id
            for market in market_group
        }

        if len(sportsbook_ids) < 3:
            continue

        for target_market in market_group:
            reference_markets = [
                market
                for market in market_group
                if market.sportsbook_id
                != target_market.sportsbook_id
            ]

            consensus_by_selection = (
                _build_reference_consensus(
                    reference_markets
                )
            )

            if consensus_by_selection is None:
                continue

            selections: list[
                ExpectedValueSelection
            ] = []

            target_is_complete = True

            for selection in target_market.selections:
                selection_key = (
                    selection.selection_name,
                    selection.line_value,
                )

                consensus_probability = (
                    consensus_by_selection.get(
                        selection_key
                    )
                )

                if consensus_probability is None:
                    target_is_complete = False
                    break

                decimal_odds = american_to_decimal_odds(
                    selection.price
                )

                expected_value = (
                    consensus_probability * decimal_odds
                ) - Decimal(1)

                selections.append(
                    ExpectedValueSelection(
                        odds_market_snapshot_id=(
                            selection.odds_market_snapshot_id
                        ),
                        selection_name=(
                            selection.selection_name
                        ),
                        line_value=selection.line_value,
                        sportsbook_id=(
                            target_market.sportsbook_id
                        ),
                        price=selection.price,
                        consensus_probability=(
                            consensus_probability
                        ),
                        expected_value=expected_value,
                    )
                )

            if not target_is_complete:
                continue

            expected_value_markets.append(
                ExpectedValueMarket(
                    game_id=target_market.game_id,
                    sportsbook_id=(
                        target_market.sportsbook_id
                    ),
                    market_type=(
                        target_market.market_type
                    ),
                    line_value=key[2],
                    snapshot_time=(
                        target_market.snapshot_time
                    ),
                    selections=tuple(selections),
                )
            )

    expected_value_markets.sort(
        key=lambda market: (
            market.snapshot_time,
            market.game_id,
            market.market_type,
            (
                str(market.line_value)
                if market.line_value is not None
                else ""
            ),
            market.sportsbook_id,
        )
    )

    return expected_value_markets


def _build_reference_consensus(
    markets: list[NoVigMarket],
) -> dict[SelectionKey, Decimal] | None:
    """
    Average no-vig probabilities across reference sportsbooks.

    Every reference sportsbook must offer every selection.
    """

    sportsbook_ids = {
        market.sportsbook_id
        for market in markets
    }

    if len(sportsbook_ids) < 2:
        return None

    probabilities_by_selection: dict[
        SelectionKey,
        dict[int, Decimal],
    ] = defaultdict(dict)

    for market in markets:
        for selection in market.selections:
            selection_key = (
                selection.selection_name,
                selection.line_value,
            )

            probabilities_by_selection[
                selection_key
            ][market.sportsbook_id] = (
                selection.no_vig_probability
            )

    if not probabilities_by_selection:
        return None

    if any(
        set(probabilities_by_book)
        != sportsbook_ids
        for probabilities_by_book
        in probabilities_by_selection.values()
    ):
        return None

    return {
        selection_key: (
            sum(probabilities_by_book.values())
            / Decimal(len(probabilities_by_book))
        )
        for (
            selection_key,
            probabilities_by_book,
        ) in probabilities_by_selection.items()
    }


def _canonical_market_line(
    market_type: str,
    line_value: Decimal | None,
) -> Decimal | None:
    """
    Return the canonical market-level line.
    """

    if market_type == "spreads" and line_value is not None:
        return abs(line_value)

    return line_value