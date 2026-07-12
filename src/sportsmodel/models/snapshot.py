from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class MarketSnapshot:
    """
    Represents a single sportsbook price at one point in time.
    """

    odds_market_snapshot_id: int

    game_id: int

    sportsbook_id: int

    market_type: str

    selection_name: str

    line_value: Decimal | None

    price: int

    snapshot_time: datetime