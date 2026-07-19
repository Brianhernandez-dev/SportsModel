from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FeatureGenerationContext:
    """
    Immutable context used to generate features for one historical game.

    The cutoff time represents the latest point in time from which source
    information may be used. Data occurring at or after the cutoff must not
    influence the generated feature vector.
    """

    game_id: int

    game_start_time: datetime

    cutoff_time: datetime

    home_team_id: int

    away_team_id: int

    home_starting_pitcher_id: int | None = None

    away_starting_pitcher_id: int | None = None