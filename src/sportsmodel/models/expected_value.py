from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class ExpectedValueSelection:
    """
    Expected value for one sportsbook selection.
    """

    odds_market_snapshot_id: int
    selection_name: str
    line_value: Decimal | None
    sportsbook_id: int
    price: int
    consensus_probability: Decimal
    expected_value: Decimal


@dataclass(frozen=True)
class ExpectedValueMarket:
    """
    Expected values for one sportsbook market.
    """

    game_id: int
    sportsbook_id: int
    market_type: str
    line_value: Decimal | None
    snapshot_time: datetime
    selections: tuple[ExpectedValueSelection, ...]