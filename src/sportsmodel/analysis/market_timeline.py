from collections import defaultdict
from collections.abc import Iterable

from sportsmodel.models.complete_market import CompleteMarket
from sportsmodel.models.market_timeline import MarketTimeline


TimelineKey = tuple[
    int,
    int,
    str,
]


def build_market_timelines(
    markets: Iterable[CompleteMarket],
) -> list[MarketTimeline]:
    """
    Group complete sportsbook markets into chronological timelines.

    Markets are grouped by:
    - game
    - sportsbook
    - market type

    Line values are intentionally not part of the grouping key because
    line changes must remain within the same timeline.
    """

    grouped_markets: dict[
        TimelineKey,
        list[CompleteMarket],
    ] = defaultdict(list)

    for market in markets:
        key = (
            market.game_id,
            market.sportsbook_id,
            market.market_type,
        )

        grouped_markets[key].append(market)

    timelines: list[MarketTimeline] = []

    for key, group in grouped_markets.items():
        ordered_markets = sorted(
            group,
            key=lambda market: (
                market.snapshot_time,
                str(market.line_value)
                if market.line_value is not None
                else "",
            ),
        )

        timelines.append(
            MarketTimeline(
                game_id=key[0],
                sportsbook_id=key[1],
                market_type=key[2],
                markets=tuple(ordered_markets),
            )
        )

    timelines.sort(
        key=lambda timeline: (
            timeline.game_id,
            timeline.sportsbook_id,
            timeline.market_type,
        )
    )

    return timelines
