from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from sportsmodel.models import CompleteMarket, MarketSnapshot


MarketKey = tuple[
    int,
    int,
    str,
    Decimal | None,
    object,
]


def build_complete_markets(
    snapshots: Iterable[MarketSnapshot],
) -> list[CompleteMarket]:
    """
    Group snapshots into complete sportsbook markets.

    Incomplete markets are ignored.
    """

    grouped: dict[
        MarketKey,
        list[MarketSnapshot],
    ] = defaultdict(list)

    for snapshot in snapshots:

        if snapshot.market_type == "h2h":
            line_key = None

        elif snapshot.market_type == "totals":
            line_key = snapshot.line_value

        elif snapshot.market_type == "spreads":
            line_key = abs(snapshot.line_value)

        else:
            continue

        key = (
            snapshot.game_id,
            snapshot.sportsbook_id,
            snapshot.market_type,
            line_key,
            snapshot.snapshot_time,
        )

        grouped[key].append(snapshot)

    markets: list[CompleteMarket] = []

    for group in grouped.values():

        if len(group) != 2:
            continue

        ordered = sorted(
            group,
            key=lambda s: s.selection_name,
        )

        markets.append(
            CompleteMarket(
                game_id=ordered[0].game_id,
                sportsbook_id=ordered[0].sportsbook_id,
                market_type=ordered[0].market_type,
                line_value=ordered[0].line_value,
                snapshot_time=ordered[0].snapshot_time,
                selections=tuple(ordered),
            )
        )

    markets.sort(
        key=lambda market: (
            market.snapshot_time,
            market.game_id,
            market.sportsbook_id,
            market.market_type,
        )
    )

    return markets