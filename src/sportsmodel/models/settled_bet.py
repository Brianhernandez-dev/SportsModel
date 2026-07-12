from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class BetOutcome(Enum):
    WIN = "win"
    LOSS = "loss"
    PUSH = "push"


@dataclass(frozen=True)
class SettledBet:
    """
    A strategy-selected wager joined to its final result.
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

    outcome: BetOutcome
    profit_units: Decimal
