from dataclasses import dataclass


@dataclass(frozen=True)
class GameResult:
    """
    Final score and team identity for one canonical game.
    """

    game_id: int
    home_team: str
    away_team: str
    home_score: int
    away_score: int
