from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class MoneylineDailyWorkflowRun:
    moneyline_daily_workflow_run_id: int
    target_date: date
    status: str
    current_stage: str
    moneyline_prediction_run_id: int | None
    odds_ingestion_run_id: int | None
    odds_status_code: int | None
    odds_remaining_requests: int | None
    odds_used_requests: int | None
    attempt_count: int
    last_attempt_started_at: datetime | None
    last_attempt_completed_at: datetime | None
    pregame_completed_at: datetime | None
    settlement_completed_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
