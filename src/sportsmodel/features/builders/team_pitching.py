from collections.abc import Sequence

from sportsmodel.features.builders.base import (
    FeatureBuilder,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.provider import (
    FeatureDataProvider,
)
from sportsmodel.models.historical_team_game import (
    HistoricalTeamGame,
)
from sportsmodel.models.team_pitching_features import (
    TeamPitchingFeatures,
)


SEASON_GAME_LIMIT = 200
LAST_5_WINDOW_SIZE = 5
LAST_10_WINDOW_SIZE = 10


class TeamPitchingFeatureBuilder(
    FeatureBuilder[TeamPitchingFeatures],
):
    """
    Build point-in-time historical pitching features for one team.
    """

    def __init__(
        self,
        *,
        team_id: int,
    ) -> None:
        if team_id <= 0:
            raise ValueError(
                "Team pitching feature builder team ID must be "
                "greater than zero."
            )

        self._team_id = team_id

    @property
    def team_id(self) -> int:
        return self._team_id

    def build(
        self,
        context: FeatureGenerationContext,
        provider: FeatureDataProvider,
    ) -> TeamPitchingFeatures:

        self._validate_context_team(context)

        self._validate_provider_context(
            context=context,
            provider=provider,
        )

        historical_games = provider.get_completed_team_games(
            team_id=self._team_id,
            limit=SEASON_GAME_LIMIT,
        )

        last_5_games = historical_games[
            :LAST_5_WINDOW_SIZE
        ]

        last_10_games = historical_games[
            :LAST_10_WINDOW_SIZE
        ]

        return TeamPitchingFeatures(
            games_played=len(historical_games),
            runs_allowed_per_game_season=_average_statistic(
                games=historical_games,
                statistic_name="runs_allowed",
            ),
            runs_allowed_per_game_last_5=_average_statistic(
                games=last_5_games,
                statistic_name="runs_allowed",
            ),
            runs_allowed_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="runs_allowed",
            ),
            earned_runs_allowed_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="earned_runs_allowed",
            ),
            hits_allowed_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="hits_allowed",
            ),
            walks_allowed_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="walks_allowed",
            ),
            strikeouts_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="strikeouts_recorded",
            ),
            home_runs_allowed_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="home_runs_allowed",
            ),
            whip_last_10=_calculate_whip(
                games=last_10_games,
            ),
            games_in_last_5_window=len(last_5_games),
            games_in_last_10_window=len(last_10_games),
        )

    def _validate_context_team(
        self,
        context: FeatureGenerationContext,
    ) -> None:
        if self._team_id not in {
            context.home_team_id,
            context.away_team_id,
        }:
            raise ValueError(
                "Team pitching feature builder team ID must match "
                "the home or away team in the feature context."
            )

    @staticmethod
    def _validate_provider_context(
        *,
        context: FeatureGenerationContext,
        provider: FeatureDataProvider,
    ) -> None:
        if provider.context != context:
            raise ValueError(
                "Feature data provider context must match the "
                "builder context."
            )


def _average_statistic(
    *,
    games: Sequence[HistoricalTeamGame],
    statistic_name: str,
) -> float | None:
    if not games:
        return None

    total = sum(
        getattr(
            game.statistics,
            statistic_name,
        )
        for game in games
    )

    return total / len(games)


def _calculate_whip(
    *,
    games: Sequence[HistoricalTeamGame],
) -> float | None:
    """
    Calculate aggregate WHIP over the supplied rolling window.

    WHIP =
        (Hits Allowed + Walks Allowed)
        /
        Innings Pitched

    Innings pitched are computed from pitching outs.
    """

    if not games:
        return None

    hits_allowed = sum(
        game.statistics.hits_allowed
        for game in games
    )

    walks_allowed = sum(
        game.statistics.walks_allowed
        for game in games
    )

    pitching_outs = sum(
        game.statistics.pitching_outs
        for game in games
    )

    if pitching_outs == 0:
        return None

    innings_pitched = pitching_outs / 3

    return (
        hits_allowed
        + walks_allowed
    ) / innings_pitched