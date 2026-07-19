from dataclasses import dataclass


@dataclass(frozen=True)
class TeamGameStatistics:
    """
    Final team-level batting and pitching statistics for one game.

    Pitching innings are represented as outs. Baseball notation such as
    5.2 innings means 17 outs, not 5.2 decimal innings.
    """

    game_id: int

    team_id: int

    is_home: bool

    runs: int

    hits: int

    errors: int

    at_bats: int

    plate_appearances: int | None

    doubles: int

    triples: int

    home_runs: int

    walks: int

    intentional_walks: int

    strikeouts: int

    hit_by_pitch: int

    sacrifice_flies: int

    stolen_bases: int

    caught_stealing: int

    pitching_outs: int

    runs_allowed: int

    earned_runs_allowed: int

    hits_allowed: int

    home_runs_allowed: int

    walks_allowed: int

    strikeouts_recorded: int

    left_on_base: int | None

    double_plays: int | None

    source_name: str

    def __post_init__(self) -> None:
        _validate_positive_identifier(
            value=self.game_id,
            field_name="Game ID",
        )

        _validate_positive_identifier(
            value=self.team_id,
            field_name="Team ID",
        )

        required_counts = {
            "Runs": self.runs,
            "Hits": self.hits,
            "Errors": self.errors,
            "At-bats": self.at_bats,
            "Doubles": self.doubles,
            "Triples": self.triples,
            "Home runs": self.home_runs,
            "Walks": self.walks,
            "Intentional walks": self.intentional_walks,
            "Strikeouts": self.strikeouts,
            "Hit by pitch": self.hit_by_pitch,
            "Sacrifice flies": self.sacrifice_flies,
            "Stolen bases": self.stolen_bases,
            "Caught stealing": self.caught_stealing,
            "Pitching outs": self.pitching_outs,
            "Runs allowed": self.runs_allowed,
            "Earned runs allowed": self.earned_runs_allowed,
            "Hits allowed": self.hits_allowed,
            "Home runs allowed": self.home_runs_allowed,
            "Walks allowed": self.walks_allowed,
            "Strikeouts recorded": self.strikeouts_recorded,
        }

        for field_name, value in required_counts.items():
            _validate_non_negative_count(
                value=value,
                field_name=field_name,
            )

        optional_counts = {
            "Plate appearances": self.plate_appearances,
            "Left on base": self.left_on_base,
            "Double plays": self.double_plays,
        }

        for field_name, value in optional_counts.items():
            _validate_optional_non_negative_count(
                value=value,
                field_name=field_name,
            )

        if self.earned_runs_allowed > self.runs_allowed:
            raise ValueError(
                "Earned runs allowed cannot exceed runs allowed."
            )

        if not self.source_name.strip():
            raise ValueError(
                "Source name cannot be empty."
            )


def _validate_positive_identifier(
    value: int,
    field_name: str,
) -> None:
    if value <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero."
        )


def _validate_non_negative_count(
    value: int,
    field_name: str,
) -> None:
    if value < 0:
        raise ValueError(
            f"{field_name} cannot be negative."
        )


def _validate_optional_non_negative_count(
    value: int | None,
    field_name: str,
) -> None:
    if value is not None and value < 0:
        raise ValueError(
            f"{field_name} cannot be negative."
        )
