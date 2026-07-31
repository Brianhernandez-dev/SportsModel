from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class SystemHealthSummary:
    """
    Read-only operational summary for the Control Center.
    """

    canonical_games_count: int

    completed_games_count: int

    latest_completed_game_date: date | None

    games_with_complete_team_statistics_count: int

    games_with_pitching_statistics_count: int

    odds_snapshot_count: int

    latest_odds_snapshot_time: datetime | None

    latest_odds_run_status: str | None

    latest_odds_run_started_at: datetime | None

    latest_odds_run_completed_at: datetime | None

    latest_odds_run_error_message: str | None
