from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BaseballTeamSource:
    baseball_team_source_id: int | None
    team_id: int
    source_name: str
    external_team_id: str
    created_at: datetime | None = None