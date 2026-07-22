from dataclasses import dataclass

from sportsmodel.models.baseball_game import BaseballGame


@dataclass(frozen=True)
class CompletedGame:
    """
    Canonical MLB game paired with its final score.
    """

    game: BaseballGame

    home_score: int

    away_score: int

    def __post_init__(self) -> None:
        if self.home_score < 0:
            raise ValueError(
                "Home score cannot be negative."
            )

        if self.away_score < 0:
            raise ValueError(
                "Away score cannot be negative."
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
