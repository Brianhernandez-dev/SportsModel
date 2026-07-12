from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class ClosingLineValueSelection:
    """
    Closing line value for one selection at one historical bet time.

    Price-based CLV is only populated when the bet and closing line
    represent the same contract.
    """

    odds_market_snapshot_id: int
    selection_name: str
    sportsbook_id: int

    bet_line: Decimal | None
    closing_line: Decimal | None
    line_change: Decimal | None

    bet_price: int
    closing_price: int

    bet_implied_probability: Decimal
    closing_implied_probability: Decimal

    probability_clv: Decimal | None
    decimal_odds_clv: Decimal | None
    is_price_comparable: bool


@dataclass(frozen=True)
class ClosingLineValueMarket:
    """
    CLV results for one sportsbook market at one historical bet time.
    """

    game_id: int
    sportsbook_id: int
    market_type: str

    bet_snapshot_time: datetime
    closing_snapshot_time: datetime

    selections: tuple[ClosingLineValueSelection, ...]
