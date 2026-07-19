from __future__ import annotations

from dataclasses import dataclass

from sportsmodel.models.player_game_pitching_statistics import (
    PlayerGamePitchingStatistics,
)
from sportsmodel.models.team_game_statistics import (
    TeamGameStatistics,
)


@dataclass(frozen=True)
class ParsedBoxScore:
    """
    Parsed historical box score ready for persistence.
    """

    game_pk: int

    game_number: int

    double_header: bool

    team_statistics: tuple[TeamGameStatistics, ...]

    pitcher_statistics: tuple[PlayerGamePitchingStatistics, ...]