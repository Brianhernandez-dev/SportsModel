from dataclasses import dataclass


@dataclass(frozen=True)
class TeamScheduleFeatures:
    """
    Rest and recent scheduling features for one team.
    """

    days_since_previous_game: int | None

    played_previous_day: bool

    games_in_previous_3_days: int

    games_in_previous_7_days: int

    doubleheader_game: bool

    current_home_stand_length: int

    current_road_trip_length: int

    def __post_init__(self) -> None:
        if (
            self.days_since_previous_game is not None
            and self.days_since_previous_game < 0
        ):
            raise ValueError(
                "Days since previous game cannot be negative."
            )

        if self.games_in_previous_3_days < 0:
            raise ValueError(
                "Games in previous 3 days cannot be negative."
            )

        if self.games_in_previous_7_days < 0:
            raise ValueError(
                "Games in previous 7 days cannot be negative."
            )

        if (
            self.games_in_previous_3_days
            > self.games_in_previous_7_days
        ):
            raise ValueError(
                "Games in previous 3 days cannot exceed games in "
                "previous 7 days."
            )

        if self.current_home_stand_length < 0:
            raise ValueError(
                "Current home stand length cannot be negative."
            )

        if self.current_road_trip_length < 0:
            raise ValueError(
                "Current road trip length cannot be negative."
            )

        if (
            self.current_home_stand_length > 0
            and self.current_road_trip_length > 0
        ):
            raise ValueError(
                "A team cannot be on a home stand and road trip "
                "simultaneously."
            )
