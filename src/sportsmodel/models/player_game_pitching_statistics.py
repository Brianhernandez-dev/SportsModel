from dataclasses import dataclass
from enum import StrEnum


class PitchingDecision(StrEnum):
    """
    Supported official pitching decisions.
    """

    WIN = "W"

    LOSS = "L"

    SAVE = "S"

    HOLD = "H"

    BLOWN_SAVE = "BS"


@dataclass(frozen=True)
class PlayerGamePitchingStatistics:
    """
    Final statistics for one pitcher appearance in one game.

    The appearance order and starter flag allow starting-pitcher and
    bullpen features to be generated from the same historical table.
    """

    game_id: int

    team_id: int

    baseball_player_id: int

    appearance_order: int

    is_starter: bool

    pitching_outs: int

    batters_faced: int | None

    hits_allowed: int

    runs_allowed: int

    earned_runs_allowed: int

    home_runs_allowed: int

    walks_allowed: int

    intentional_walks_allowed: int

    strikeouts: int

    hit_batters: int

    pitches_thrown: int | None

    strikes_thrown: int | None

    decision: PitchingDecision | None

    save_recorded: bool

    hold_recorded: bool

    blown_save_recorded: bool

    source_name: str

    def __post_init__(self) -> None:
        identifiers = {
            "Game ID": self.game_id,
            "Team ID": self.team_id,
            "Baseball player ID": self.baseball_player_id,
        }

        for field_name, value in identifiers.items():
            if value <= 0:
                raise ValueError(
                    f"{field_name} must be greater than zero."
                )

        if self.appearance_order <= 0:
            raise ValueError(
                "Appearance order must be greater than zero."
            )

        required_counts = {
            "Pitching outs": self.pitching_outs,
            "Hits allowed": self.hits_allowed,
            "Runs allowed": self.runs_allowed,
            "Earned runs allowed": self.earned_runs_allowed,
            "Home runs allowed": self.home_runs_allowed,
            "Walks allowed": self.walks_allowed,
            "Intentional walks allowed": (
                self.intentional_walks_allowed
            ),
            "Strikeouts": self.strikeouts,
            "Hit batters": self.hit_batters,
        }

        for field_name, value in required_counts.items():
            if value < 0:
                raise ValueError(
                    f"{field_name} cannot be negative."
                )

        optional_counts = {
            "Batters faced": self.batters_faced,
            "Pitches thrown": self.pitches_thrown,
            "Strikes thrown": self.strikes_thrown,
        }

        for field_name, value in optional_counts.items():
            if value is not None and value < 0:
                raise ValueError(
                    f"{field_name} cannot be negative."
                )

        if self.earned_runs_allowed > self.runs_allowed:
            raise ValueError(
                "Earned runs allowed cannot exceed runs allowed."
            )

        if (
            self.pitches_thrown is not None
            and self.strikes_thrown is not None
            and self.strikes_thrown > self.pitches_thrown
        ):
            raise ValueError(
                "Strikes thrown cannot exceed pitches thrown."
            )

        if not self.source_name.strip():
            raise ValueError(
                "Source name cannot be empty."
            )
