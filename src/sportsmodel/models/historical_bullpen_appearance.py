from dataclasses import dataclass
from datetime import datetime

from sportsmodel.models.player_game_pitching_statistics import (
    PlayerGamePitchingStatistics,
)


@dataclass(frozen=True)
class HistoricalBullpenAppearance:
    """
    One completed historical relief appearance with game context.
    """

    game_id: int

    game_start_time: datetime

    team_id: int

    opponent_team_id: int

    is_home: bool

    statistics: PlayerGamePitchingStatistics

    def __post_init__(self) -> None:
        identifiers = {
            "Game ID": self.game_id,
            "Team ID": self.team_id,
            "Opponent team ID": self.opponent_team_id,
        }

        for field_name, value in identifiers.items():
            if value <= 0:
                raise ValueError(
                    f"{field_name} must be greater than zero."
                )

        if self.team_id == self.opponent_team_id:
            raise ValueError(
                "Team ID and opponent team ID cannot be the same."
            )

        if (
            self.game_start_time.tzinfo is None
            or self.game_start_time.utcoffset() is None
        ):
            raise ValueError(
                "Game start time must be timezone-aware."
            )

        if self.statistics.game_id != self.game_id:
            raise ValueError(
                "Statistics game ID must match appearance game ID."
            )

        if self.statistics.team_id != self.team_id:
            raise ValueError(
                "Statistics team ID must match appearance team ID."
            )

        if self.statistics.is_starter:
            raise ValueError(
                "Historical bullpen appearance cannot be a starter."
            )
