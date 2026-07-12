from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class BetCandidate:
    """
    A historical sportsbook selection that satisfied a strategy.

    This model contains only information known at the bet timestamp.
    It intentionally contains no closing data or game result.
    """

    odds_market_snapshot_id: int
    game_id: int
    sportsbook_id: int

    market_type: str
    selection_name: str
    line_value: Decimal | None

    bet_snapshot_time: datetime
    price: int

    consensus_probability: Decimal
    expected_value: Decimal
