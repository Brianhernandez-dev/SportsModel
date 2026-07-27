from dataclasses import dataclass

from sportsmodel.models.bullpen_features import (
    BullpenFeatures,
)
from sportsmodel.models.team_batting_features import (
    TeamBattingFeatures,
)
from sportsmodel.models.team_pitching_features import (
    TeamPitchingFeatures,
)
from sportsmodel.models.team_schedule_features import (
    TeamScheduleFeatures,
)


@dataclass(frozen=True)
class TeamFeatureVector:
    """
    Complete feature groups for one team in one game.
    """

    team_id: int

    batting: TeamBattingFeatures

    pitching: TeamPitchingFeatures

    bullpen: BullpenFeatures

    schedule: TeamScheduleFeatures

    def __post_init__(self) -> None:
        if self.team_id <= 0:
            raise ValueError(
                "Team feature vector team ID must be greater than zero."
            )
