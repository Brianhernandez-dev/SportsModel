from dataclasses import dataclass


@dataclass(frozen=True)
class BullpenFeatures:
    """
    Historical relief-pitching performance and workload features.
    """

    relief_appearances_season: int

    bullpen_earned_run_average_season: float | None

    bullpen_earned_run_average_last_10: float | None

    bullpen_whip_season: float | None

    bullpen_whip_last_10: float | None

    relief_innings_last_1_day: float | None

    relief_innings_last_3_days: float | None

    relief_innings_last_7_days: float | None

    relievers_used_previous_game: int | None

    back_to_back_usage_count: int | None

    games_in_last_10_window: int

    def __post_init__(self) -> None:
        if self.relief_appearances_season < 0:
            raise ValueError(
                "Relief appearance count cannot be negative."
            )

        if self.games_in_last_10_window < 0:
            raise ValueError(
                "Games in last 10 window cannot be negative."
            )

        if self.games_in_last_10_window > 10:
            raise ValueError(
                "Games in last 10 window cannot exceed 10."
            )

        if (
            self.relievers_used_previous_game is not None
            and self.relievers_used_previous_game < 0
        ):
            raise ValueError(
                "Relievers used in the previous game cannot be "
                "negative."
            )

        if (
            self.back_to_back_usage_count is not None
            and self.back_to_back_usage_count < 0
        ):
            raise ValueError(
                "Back-to-back usage count cannot be negative."
            )
