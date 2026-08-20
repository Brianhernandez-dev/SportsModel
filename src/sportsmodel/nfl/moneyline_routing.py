from enum import StrEnum


NFL_MONEYLINE_ROUTING_CONTRACT_VERSION = "nfl_moneyline_routing_0.1.0"
NFL_MONEYLINE_MATURE_PRIOR_GAME_THRESHOLD = 3


class NFLMoneylineRoute(StrEnum):
    EARLY = "early"
    MATURE = "mature"


def select_nfl_moneyline_route(
    home_current_prior_games: int,
    away_current_prior_games: int,
) -> NFLMoneylineRoute:
    """Select a frozen route using PIT-safe current-season game counts."""

    if (
        isinstance(home_current_prior_games, bool)
        or isinstance(away_current_prior_games, bool)
        or not isinstance(home_current_prior_games, int)
        or not isinstance(away_current_prior_games, int)
    ):
        raise TypeError("current-season prior-game counts must be integers")
    if home_current_prior_games < 0 or away_current_prior_games < 0:
        raise ValueError("current-season prior-game counts cannot be negative")
    if (
        home_current_prior_games
        >= NFL_MONEYLINE_MATURE_PRIOR_GAME_THRESHOLD
        and away_current_prior_games
        >= NFL_MONEYLINE_MATURE_PRIOR_GAME_THRESHOLD
    ):
        return NFLMoneylineRoute.MATURE
    return NFLMoneylineRoute.EARLY
