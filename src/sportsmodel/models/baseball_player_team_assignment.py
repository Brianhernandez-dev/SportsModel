from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class BaseballPlayerTeamAssignment:
    baseball_player_team_assignment_id: int | None
    baseball_player_id: int
    team_id: int

    roster_status_code: str | None = None
    roster_status_description: str | None = None

    jersey_number: str | None = None

    position_code: str | None = None
    position_name: str | None = None

    valid_from: date | None = None
    valid_through: date | None = None

    is_current: bool = True

    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None