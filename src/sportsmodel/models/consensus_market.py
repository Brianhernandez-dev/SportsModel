from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class ConsensusSelection:
    """
    Consensus probability for one market selection.
    """

    selection_name: str

    line_value: Decimal | None

    consensus_probability: Decimal

    sportsbook_count: int


@dataclass(frozen=True)
class ConsensusMarket:
    """
    Consensus probabilities across sportsbooks.
    """

    game_id: int

    market_type: str

    line_value: Decimal | None

    snapshot_time: datetime

    selections: tuple[ConsensusSelection, ...]