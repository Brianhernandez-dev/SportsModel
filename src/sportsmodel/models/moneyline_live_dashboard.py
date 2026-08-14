from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class MoneylineLiveSlate:
    """
    One persisted prediction, odds, and policy combination.
    """

    prediction_run_id: int

    odds_ingestion_run_id: int

    policy_version: str

    target_date: date

    snapshot_role: str

    snapshot_started_at: datetime

    run_type: str = "official"


@dataclass(frozen=True)
class MoneylineLiveGame:
    """
    Read-only dashboard row for one Moneyline prediction.
    """

    game_id: int

    game_start_time: datetime

    away_team_name: str

    home_team_name: str

    predicted_team_name: str

    model_probability: Decimal

    starter_coverage: str

    missing_raw_value_count: int

    market_no_vig_probability: Decimal

    model_market_edge: Decimal

    price: int

    sportsbook_name: str

    model_expected_value: Decimal

    qualifies_as_paper_candidate: bool

    disqualification_reasons: tuple[str, ...]

    outcome: str | None

    profit_units: Decimal | None

    home_score: int | None

    away_score: int | None


@dataclass(frozen=True)
class MoneylineLivePerformance:
    """
    Flat one-unit performance from settled dashboard rows.
    """

    settlements: int

    wins: int

    losses: int

    pushes: int

    win_rate: Decimal

    units_staked: Decimal

    profit_units: Decimal

    roi: Decimal

    average_model_expected_value: Decimal

    maximum_drawdown_units: Decimal
