from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sportsmodel.models.settled_bet import (
    BetOutcome,
)


@dataclass(frozen=True)
class MoneylinePaperCandidate:
    """
    One qualified forward-looking Moneyline paper candidate.

    This record contains only information known at its stored odds
    snapshot and does not contain a final result.
    """

    moneyline_prediction_market_evaluation_id: int

    game_id: int

    selection_name: str

    snapshot_time: datetime

    price: int

    model_probability: Decimal

    model_expected_value: Decimal

    def __post_init__(self) -> None:
        if (
            self.moneyline_prediction_market_evaluation_id
            <= 0
        ):
            raise ValueError(
                "Moneyline market evaluation ID must "
                "be greater than zero."
            )

        if self.game_id <= 0:
            raise ValueError(
                "Game ID must be greater than zero."
            )

        if not self.selection_name.strip():
            raise ValueError(
                "Selection name cannot be blank."
            )

        if (
            self.snapshot_time.tzinfo is None
            or self.snapshot_time.utcoffset() is None
        ):
            raise ValueError(
                "Snapshot time must be timezone-aware."
            )

        if self.price == 0:
            raise ValueError(
                "American odds cannot be zero."
            )

        if not (
            Decimal("0")
            <= self.model_probability
            <= Decimal("1")
        ):
            raise ValueError(
                "Model probability must be between "
                "zero and one."
            )

        if self.model_expected_value < Decimal("-1"):
            raise ValueError(
                "Model expected value cannot be "
                "less than -1."
            )


@dataclass(frozen=True)
class MoneylinePaperSettlement:
    """
    Final result of one qualified Moneyline paper candidate.
    """

    moneyline_prediction_market_evaluation_id: int

    game_id: int

    selection_name: str

    snapshot_time: datetime

    price: int

    model_probability: Decimal

    model_expected_value: Decimal

    home_team_name: str

    away_team_name: str

    home_score: int

    away_score: int

    outcome: BetOutcome

    profit_units: Decimal
