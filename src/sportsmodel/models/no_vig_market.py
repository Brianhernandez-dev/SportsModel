from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class NoVigSelection:
    """
    Represents one selection after removing sportsbook vig.
    """

    odds_market_snapshot_id: int
    selection_name: str
    line_value: Decimal | None
    price: int
    implied_probability: Decimal
    no_vig_probability: Decimal


@dataclass(frozen=True)
class NoVigMarket:
    """
    Represents one sportsbook market after vig removal.
    """

    game_id: int
    sportsbook_id: int
    market_type: str
    line_value: Decimal | None
    snapshot_time: datetime
    selections: tuple[NoVigSelection, ...]