from dataclasses import dataclass


@dataclass(frozen=True)
class StartingPitcherFeatures:
    """
    Historical features for an expected starting pitcher.

    The player ID may be absent when no reliable pregame starter was
    available at the feature cutoff.
    """

    player_id: int | None

    starter_available: bool

    starts_season: int

    starts_last_5: int

    innings_per_start_season: float | None

    earned_run_average_season: float | None

    earned_run_average_last_5: float | None

    whip_season: float | None

    whip_last_5: float | None

    strikeouts_per_nine_season: float | None

    walks_per_nine_season: float | None

    home_runs_per_nine_season: float | None

    days_rest: int | None

    def __post_init__(self) -> None:
        if self.player_id is not None and self.player_id <= 0:
            raise ValueError(
                "Starting pitcher player ID must be greater than zero."
            )

        if self.starts_season < 0:
            raise ValueError(
                "Season start count cannot be negative."
            )

        if self.starts_last_5 < 0:
            raise ValueError(
                "Last 5 start count cannot be negative."
            )

        if self.starts_last_5 > 5:
            raise ValueError(
                "Last 5 start count cannot exceed 5."
            )

        if self.days_rest is not None and self.days_rest < 0:
            raise ValueError(
                "Starting pitcher days rest cannot be negative."
            )

        if self.starter_available and self.player_id is None:
            raise ValueError(
                "An available starting pitcher must have a player ID."
            )

        if not self.starter_available and self.player_id is not None:
            raise ValueError(
                "An unavailable starting pitcher cannot have a "
                "player ID."
            )
