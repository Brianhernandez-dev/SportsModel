from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BaseballPlayerSource:
    """
    External source identifier mapped to a canonical baseball player.
    """

    baseball_player_source_id: int | None

    baseball_player_id: int

    source_name: str

    external_player_id: str

    created_at: datetime | None = None