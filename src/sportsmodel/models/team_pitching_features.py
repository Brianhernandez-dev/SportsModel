from dataclasses import dataclass


@dataclass(frozen=True)
class TeamPitchingFeatures:
    """
    Historical team run-prevention features at a defined cutoff.

    Starting-pitcher and bullpen-specific information is represented by
    separate feature contracts.
    """

    games_played: int

    runs_allowed_per_game_season: float | None

    runs_allowed_per_game_last_5: float | None

    runs_allowed_per_game_last_10: float | None

    earned_runs_allowed_per_game_last_10: float | None

    hits_allowed_per_game_last_10: float | None

    walks_allowed_per_game_last_10: float | None

    strikeouts_per_game_last_10: float | None

    home_runs_allowed_per_game_last_10: float | None

    whip_last_10: float | None

    games_in_last_5_window: int

    games_in_last_10_window: int

    def __post_init__(self) -> None:
        _validate_non_negative_count(
            value=self.games_played,
            field_name="Games played",
        )

        _validate_non_negative_count(
            value=self.games_in_last_5_window,
            field_name="Games in last 5 window",
        )

        _validate_non_negative_count(
            value=self.games_in_last_10_window,
            field_name="Games in last 10 window",
        )

        if self.games_in_last_5_window > 5:
            raise ValueError(
                "Games in last 5 window cannot exceed 5."
            )

        if self.games_in_last_10_window > 10:
            raise ValueError(
                "Games in last 10 window cannot exceed 10."
            )


def _validate_non_negative_count(
    value: int,
    field_name: str,
) -> None:
    if value < 0:
        raise ValueError(
            f"{field_name} cannot be negative."
        )
