from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BaseballGame:
    """
    Canonical MLB game used by the feature-generation pipeline.
    """

    game_id: int

    game_start_time: datetime

    home_team_id: int

    away_team_id: int

    def __post_init__(self) -> None:
        if self.game_id <= 0:
            raise ValueError(
                "Game ID must be greater than zero."
            )

        if self.game_start_time.tzinfo is None:
            raise ValueError(
                "Game start time must be timezone-aware."
            )

        if self.home_team_id <= 0:
            raise ValueError(
                "Home team ID must be greater than zero."
            )

        if self.away_team_id <= 0:
            raise ValueError(
                "Away team ID must be greater than zero."
            )

        if self.home_team_id == self.away_team_id:
            raise ValueError(
                "Home and away teams must be different."
            )
