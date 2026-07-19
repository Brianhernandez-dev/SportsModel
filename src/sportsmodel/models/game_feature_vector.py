from dataclasses import dataclass
from datetime import datetime

from sportsmodel.models.starting_pitcher_features import (
    StartingPitcherFeatures,
)
from sportsmodel.models.team_feature_vector import (
    TeamFeatureVector,
)


@dataclass(frozen=True)
class GameFeatureVector:
    """
    Complete pregame feature vector for one canonical MLB game.
    """

    game_id: int

    game_start_time: datetime

    feature_time: datetime

    feature_schema_version: str

    home_team: TeamFeatureVector

    away_team: TeamFeatureVector

    home_starting_pitcher: StartingPitcherFeatures

    away_starting_pitcher: StartingPitcherFeatures

    def __post_init__(self) -> None:
        if self.game_id <= 0:
            raise ValueError(
                "Game feature vector game ID must be greater than zero."
            )

        if self.home_team.team_id == self.away_team.team_id:
            raise ValueError(
                "Home and away feature vectors must represent "
                "different teams."
            )

        if (
            self.game_start_time.tzinfo is None
            or self.game_start_time.utcoffset() is None
        ):
            raise ValueError(
                "Game start time must be timezone-aware."
            )

        if (
            self.feature_time.tzinfo is None
            or self.feature_time.utcoffset() is None
        ):
            raise ValueError(
                "Feature time must be timezone-aware."
            )

        if self.feature_time > self.game_start_time:
            raise ValueError(
                "Feature time cannot occur after game start time."
            )

        if not self.feature_schema_version.strip():
            raise ValueError(
                "Feature schema version cannot be empty."
            )
