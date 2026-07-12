from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sportsmodel.models import (
    ConsensusMarket,
    ConsensusSelection,
    NoVigMarket,
)


ConsensusKey = tuple[
    int,
    str,
    Decimal | None,
    datetime,
]

SelectionKey = tuple[
    str,
    Decimal | None,
]


def build_consensus_markets(
    markets: list[NoVigMarket],
) -> list[ConsensusMarket]:
    """
    Build consensus probabilities across sportsbooks.

    Markets are grouped by:
    - game
    - market type
    - canonical line
    - snapshot time

    A consensus market requires at least two sportsbooks.
    Every contributing sportsbook must offer every selection in the
    market. Incomplete or inconsistent groups are excluded.
    """

    grouped_markets: dict[
        ConsensusKey,
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

    consensus_markets: list[ConsensusMarket] = []

    for key, market_group in grouped_markets.items():
        (
            game_id,
            market_type,
            canonical_line,
            snapshot_time,
        ) = key

        sportsbook_ids = {
            market.sportsbook_id
            for market in market_group
        }

        if len(sportsbook_ids) < 2:
            continue

        probabilities_by_selection: dict[
            SelectionKey,
            dict[int, Decimal],
        ] = defaultdict(dict)

        for market in market_group:
            for selection in market.selections:
                selection_key = (
                    selection.selection_name,
                    selection.line_value,
                )

                probabilities_by_selection[selection_key][
                    market.sportsbook_id
                ] = selection.no_vig_probability

        if not probabilities_by_selection:
            continue

        # Every selection must be represented by every contributing book.
        if any(
            set(probabilities_by_book) != sportsbook_ids
            for probabilities_by_book
            in probabilities_by_selection.values()
        ):
            continue

        selections: list[ConsensusSelection] = []

        for (
            selection_name,
            selection_line,
        ), probabilities_by_book in probabilities_by_selection.items():
            probabilities = list(
                probabilities_by_book.values()
            )

            consensus_probability = (
                sum(probabilities)
                / Decimal(len(probabilities))
            )

            selections.append(
                ConsensusSelection(
                    selection_name=selection_name,
                    line_value=selection_line,
                    consensus_probability=consensus_probability,
                    sportsbook_count=len(probabilities_by_book),
                )
            )

        selections.sort(
            key=lambda selection: (
                selection.selection_name,
                (
                    str(selection.line_value)
                    if selection.line_value is not None
                    else ""
                ),
            )
        )

        consensus_markets.append(
            ConsensusMarket(
                game_id=game_id,
                market_type=market_type,
                line_value=canonical_line,
                snapshot_time=snapshot_time,
                selections=tuple(selections),
            )
        )

    consensus_markets.sort(
        key=lambda market: (
            market.snapshot_time,
            market.game_id,
            market.market_type,
            (
                str(market.line_value)
                if market.line_value is not None
                else ""
            ),
        )
    )

    return consensus_markets


def _canonical_market_line(
    market_type: str,
    line_value: Decimal | None,
) -> Decimal | None:
    """
    Return a consistent market-level line.

    Spread selections contain opposite signed values, such as -1.5
    and +1.5. The absolute value identifies the shared spread market.
    """

    if market_type == "spreads" and line_value is not None:
        return abs(line_value)

    return line_value