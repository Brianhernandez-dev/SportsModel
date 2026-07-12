from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sportsmodel.models.snapshot import MarketSnapshot


@dataclass(frozen=True)
class CompleteMarket:
    """
    Represents one complete sportsbook market at one instant.

    Examples:
        Moneyline:
            Home / Away

        Totals:
            Over / Under

        Spreads:
            Team A -1.5
            Team B +1.5
    """

    game_id: int

    sportsbook_id: int

    market_type: str

    line_value: Decimal | None

    snapshot_time: datetime

    selections: tuple[MarketSnapshot, ...]