from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class LineMovement:
    """
    Represents how one sportsbook's line changed over time.
    """

    game_id: int

    sportsbook_id: int

    market_type: str

    selection_name: str

    opening_line: Decimal | None

    latest_line: Decimal | None

    line_change: Decimal | None

    opening_price: int

    latest_price: int

    price_change: int

    first_snapshot: datetime

    latest_snapshot: datetime

    snapshot_count: int