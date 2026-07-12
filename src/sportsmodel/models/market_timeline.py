from dataclasses import dataclass

from sportsmodel.models.complete_market import CompleteMarket


@dataclass(frozen=True)
class MarketTimeline:
    """
    Represents one sportsbook market evolving over time.

    Markets are ordered chronologically and may contain changing
    line values and prices.
    """

    game_id: int
    sportsbook_id: int
    market_type: str
    markets: tuple[CompleteMarket, ...]
