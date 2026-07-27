from dataclasses import dataclass

from sportsmodel.models.player_game_pitching_statistics import (
    PlayerGamePitchingStatistics,
)
from sportsmodel.models.team_game_statistics import TeamGameStatistics


@dataclass(frozen=True)
class ParsedBoxScore:
    """
    Fully parsed final MLB box score.

    The model retains both the canonical database game ID and the
    external MLB game identifier used to retrieve the source data.
    """

    game_id: int

    game_pk: int

    game_number: int

    double_header: bool

    team_statistics: tuple[TeamGameStatistics, ...]

    pitcher_statistics: tuple[PlayerGamePitchingStatistics, ...]

    def __post_init__(self) -> None:
        if self.game_id <= 0:
            raise ValueError(
                "Game ID must be greater than zero."
            )

        if self.game_pk <= 0:
            raise ValueError(
                "MLB game PK must be greater than zero."
            )

        if self.game_number <= 0:
            raise ValueError(
                "Game number must be greater than zero."
            )

        statistics_game_ids = {
            statistics.game_id
            for statistics in self.team_statistics
        }

        statistics_game_ids.update(
            statistics.game_id
            for statistics in self.pitcher_statistics
        )

        if (
            statistics_game_ids
            and statistics_game_ids != {self.game_id}
        ):
            raise ValueError(
                "All parsed statistics must use the ParsedBoxScore "
                "game ID."
            )