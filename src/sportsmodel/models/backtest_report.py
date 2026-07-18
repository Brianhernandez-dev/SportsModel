from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BacktestReport:
    """
    Aggregate performance for a sequence of flat-stake settled bets.
    """

    total_bets: int
    wins: int
    losses: int
    pushes: int

    settled_decisions: int
    win_rate: Decimal

    total_staked_units: Decimal
    profit_units: Decimal
    roi: Decimal

    average_expected_value: Decimal
    maximum_drawdown_units: Decimal
