from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class BaseballPlayer:
    """
    Canonical baseball player identity.

    External provider identifiers are stored separately through
    baseball_player_sources.
    """

    baseball_player_id: int | None

    full_name: str

    bats: str | None = None
    throws: str | None = None

    primary_position: str | None = None

    active_from: date | None = None
    active_through: date | None = None

    is_active: bool = True

    last_synced_at: datetime | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None