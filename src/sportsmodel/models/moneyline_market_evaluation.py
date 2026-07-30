from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


VALID_STARTER_COVERAGE = {
    "both",
    "partial",
    "none",
}


@dataclass(frozen=True)
class MoneylineMarketEvaluationPolicy:
    """
    Qualification rules for one model-versus-market evaluation.
    """

    policy_version: str = "1.0.0"

    minimum_model_expected_value: Decimal = Decimal(
        "0.03"
    )

    minimum_model_market_edge: Decimal = Decimal(
        "0.02"
    )

    minimum_sportsbook_count: int = 5

    require_both_starters: bool = True

    require_both_starter_features: bool = True

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError(
                "Policy version cannot be blank."
            )

        if (
            self.minimum_model_expected_value
            < Decimal("-1")
        ):
            raise ValueError(
                "Minimum model expected value cannot "
                "be less than -1."
            )

        if not (
            Decimal("-1")
            <= self.minimum_model_market_edge
            <= Decimal("1")
        ):
            raise ValueError(
                "Minimum model-market edge must be "
                "between -1 and 1."
            )

        if self.minimum_sportsbook_count < 1:
            raise ValueError(
                "Minimum sportsbook count must be "
                "greater than zero."
            )


@dataclass(frozen=True)
class MoneylinePredictionMarketContext:
    """
    Prediction information required for market evaluation.
    """

    game_id: int

    selection_name: str

    model_probability: Decimal

    starter_coverage: str

    home_starter_features_available: bool

    away_starter_features_available: bool

    def __post_init__(self) -> None:
        if self.game_id <= 0:
            raise ValueError(
                "Game ID must be greater than zero."
            )

        if not self.selection_name.strip():
            raise ValueError(
                "Selection name cannot be blank."
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

        if (
            self.starter_coverage
            not in VALID_STARTER_COVERAGE
        ):
            raise ValueError(
                "Starter coverage must be both, "
                "partial, or none."
            )


@dataclass(frozen=True)
class MoneylineModelMarketEvaluation:
    """
    Model value at one stored sportsbook price snapshot.
    """

    odds_market_snapshot_id: int

    game_id: int

    sportsbook_id: int

    snapshot_time: datetime

    selection_name: str

    price: int

    model_probability: Decimal

    market_no_vig_probability: Decimal

    sportsbook_count: int

    implied_probability: Decimal

    model_market_edge: Decimal

    model_price_edge: Decimal

    model_expected_value: Decimal

    starter_coverage: str

    home_starter_features_available: bool

    away_starter_features_available: bool

    policy_version: str

    qualifies_as_paper_candidate: bool

    disqualification_reasons: tuple[str, ...]
