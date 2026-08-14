from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class MoneylinePreviewGame:
    """
    Read-only Tomorrow Preview value row.
    """

    game_id: int
    game_start_time: datetime
    away_team_name: str
    home_team_name: str
    predicted_team_name: str

    model_probability: Decimal
    market_no_vig_probability: Decimal
    model_market_edge: Decimal
    model_price_edge: Decimal

    price: int
    sportsbook_name: str
    model_expected_value: Decimal
    sportsbook_count: int

    starter_coverage: str
    home_starter_features_available: bool
    away_starter_features_available: bool
    missing_raw_value_count: int

    preview_value_signal: bool
    preview_policy_pass: bool
    disqualification_reasons: tuple[str, ...]

    opening_price: int | None = None
    opening_model_expected_value: Decimal | None = None
    opening_model_market_edge: Decimal | None = None
    opening_policy_pass: bool | None = None
    movement_status: str = "OPENING ONLY"


@dataclass(frozen=True)
class MoneylinePreviewUnavailableGame:
    """
    Preview game without sufficient opening-market consensus.
    """

    game_id: int
    game_start_time: datetime
    away_team_name: str
    home_team_name: str
    predicted_team_name: str
    model_probability: Decimal
    starter_coverage: str
    missing_raw_value_count: int
    reason: str


@dataclass(frozen=True)
class MoneylinePreviewDashboard:
    """
    Read-only Tomorrow Preview card.
    """

    target_date: date
    prediction_run_id: int
    odds_ingestion_run_id: int
    market_snapshot_time: datetime
    model_version: str
    policy_version: str

    predictions_loaded: int

    games: tuple[MoneylinePreviewGame, ...]

    unavailable_games: tuple[
        MoneylinePreviewUnavailableGame,
        ...,
    ]

    market_snapshot_role: str = "opening"
    opening_odds_ingestion_run_id: int | None = None
    opening_market_snapshot_time: datetime | None = None
