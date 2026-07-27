from dataclasses import dataclass
from datetime import datetime

from sportsmodel.models.player_game_pitching_statistics import (
    PlayerGamePitchingStatistics,
)


@dataclass(frozen=True)
class HistoricalPitcherStart:
    """
    Historical game context and final statistics for one pitcher start.

    This model combines canonical game metadata with the pitcher's final
    appearance statistics so feature builders do not need separate
    queries for game context and pitching performance.
    """

    game_id: int

    game_start_time: datetime

    team_id: int

    opponent_team_id: int

    is_home: bool

    statistics: PlayerGamePitchingStatistics

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

        if (
            self.game_start_time.tzinfo is None
            or self.game_start_time.utcoffset() is None
        ):
            raise ValueError(
                "Game start time must be timezone-aware."
            )

        if self.statistics.game_id != self.game_id:
            raise ValueError(
                "Pitching statistics game ID must match historical "
                "start game ID."
            )

        if self.statistics.team_id != self.team_id:
            raise ValueError(
                "Pitching statistics team ID must match historical "
                "start team ID."
            )

        if not self.statistics.is_starter:
            raise ValueError(
                "Historical pitcher start statistics must represent "
                "a starting-pitcher appearance."
            )


def _validate_positive_identifier(
    *,
    value: int,
    field_name: str,
) -> None:
    if value <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero."
        )
