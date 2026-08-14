from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MoneylineRunTiming:
    """
    Persisted timing metadata for one prediction/odds pair.
    """

    prediction_run_id: int
    odds_ingestion_run_id: int

    prediction_completed_at: datetime | None
    odds_completed_at: datetime | None
    market_snapshot_time: datetime | None

    snapshot_role: str
