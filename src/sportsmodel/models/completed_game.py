from dataclasses import dataclass

from sportsmodel.models.baseball_game import BaseballGame


@dataclass(frozen=True)
class CompletedGame:
    """
    Canonical MLB game paired with its final score and observed starters.

    Starting-pitcher IDs are derived from the final box score. They
    identify which pitchers started the game, but feature generation
    must still use only statistics recorded before the game cutoff.
    """

    game: BaseballGame

    home_score: int

    away_score: int

    home_starting_pitcher_id: int | None = None

    away_starting_pitcher_id: int | None = None

    def __post_init__(self) -> None:
        if self.home_score < 0:
            raise ValueError(
                "Home score cannot be negative."
            )

        if self.away_score < 0:
            raise ValueError(
                "Away score cannot be negative."
            )

        for field_name, player_id in (
            (
                "Home starting pitcher ID",
                self.home_starting_pitcher_id,
            ),
            (
                "Away starting pitcher ID",
                self.away_starting_pitcher_id,
            ),
        ):
            if player_id is not None and player_id <= 0:
                raise ValueError(
                    f"{field_name} must be greater than zero "
                    "when provided."
                )

        if (
            self.home_starting_pitcher_id is not None
            and self.home_starting_pitcher_id
            == self.away_starting_pitcher_id
        ):
            raise ValueError(
                "Home and away starting pitchers must be different."
            )

    @property
    def home_team_won(self) -> bool:
        """
        Return whether the canonical home team won the game.

        Tied games are rejected because they cannot produce a binary
        Moneyline training target.
        """

        if self.home_score == self.away_score:
            raise ValueError(
                "A tied game cannot produce a Moneyline target."
            )

        return self.home_score > self.away_score
