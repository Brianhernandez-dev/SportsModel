from dataclasses import dataclass
from datetime import datetime

from sportsmodel.models.team_game_statistics import (
    TeamGameStatistics,
)


@dataclass(frozen=True)
class HistoricalTeamGame:
    """
    Historical game context and final statistics for one team.

    This model combines canonical game metadata with the team's final
    box score statistics so feature builders do not need separate
    database queries for game context and team performance.
    """

    game_id: int

    game_start_time: datetime

    team_id: int

    opponent_team_id: int

    is_home: bool

    statistics: TeamGameStatistics

    def __post_init__(self) -> None:
        _validate_positive_identifier(
            value=self.game_id,
            field_name="Game ID",
        )

        _validate_positive_identifier(
            value=self.team_id,
            field_name="Team ID",
        )

        _validate_positive_identifier(
            value=self.opponent_team_id,
            field_name="Opponent team ID",
        )

        if self.team_id == self.opponent_team_id:
            raise ValueError(
                "Team ID and opponent team ID cannot be the same."
            )

        if self.game_start_time.tzinfo is None:
            raise ValueError(
                "Game start time must be timezone-aware."
            )

        if self.statistics.game_id != self.game_id:
            raise ValueError(
                "Statistics game ID must match historical game ID."
            )

        if self.statistics.team_id != self.team_id:
            raise ValueError(
                "Statistics team ID must match historical team ID."
            )

        if self.statistics.is_home != self.is_home:
            raise ValueError(
                "Statistics home status must match historical game "
                "home status."
            )


def _validate_positive_identifier(
    value: int,
    field_name: str,
) -> None:
    if value <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero."
        )