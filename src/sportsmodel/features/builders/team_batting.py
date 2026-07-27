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
from sportsmodel.models.team_batting_features import (
    TeamBattingFeatures,
)


SEASON_GAME_LIMIT = 200
LAST_5_WINDOW_SIZE = 5
LAST_10_WINDOW_SIZE = 10


class TeamBattingFeatureBuilder(
    FeatureBuilder[TeamBattingFeatures],
):
    """
    Build point-in-time historical batting features for one team.

    The provider returns games newest first and guarantees that every
    returned game occurred strictly before the feature-generation
    cutoff.
    """

    def __init__(
        self,
        *,
        team_id: int,
    ) -> None:
        if team_id <= 0:
            raise ValueError(
                "Team batting feature builder team ID must be "
                "greater than zero."
            )

        self._team_id = team_id

    @property
    def team_id(self) -> int:
        """
        Return the team whose batting features will be generated.
        """

        return self._team_id

    def build(
        self,
        context: FeatureGenerationContext,
        provider: FeatureDataProvider,
    ) -> TeamBattingFeatures:
        """
        Generate rolling batting features for the configured team.
        """

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

        return TeamBattingFeatures(
            games_played=len(historical_games),
            runs_per_game_season=_average_statistic(
                games=historical_games,
                statistic_name="runs",
            ),
            runs_per_game_last_5=_average_statistic(
                games=last_5_games,
                statistic_name="runs",
            ),
            runs_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="runs",
            ),
            hits_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="hits",
            ),
            home_runs_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="home_runs",
            ),
            walks_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="walks",
            ),
            strikeouts_per_game_last_10=_average_statistic(
                games=last_10_games,
                statistic_name="strikeouts",
            ),
            on_base_percentage_last_10=(
                _calculate_on_base_percentage(
                    games=last_10_games,
                )
            ),
            slugging_percentage_last_10=(
                _calculate_slugging_percentage(
                    games=last_10_games,
                )
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
                "Team batting feature builder team ID must match "
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


def _calculate_on_base_percentage(
    *,
    games: Sequence[HistoricalTeamGame],
) -> float | None:
    """
    Calculate aggregate OBP over the supplied rolling window.

    Formula:

        (H + BB + HBP) / (AB + BB + HBP + SF)
    """

    if not games:
        return None

    hits = sum(
        game.statistics.hits
        for game in games
    )

    walks = sum(
        game.statistics.walks
        for game in games
    )

    hit_by_pitch = sum(
        game.statistics.hit_by_pitch
        for game in games
    )

    at_bats = sum(
        game.statistics.at_bats
        for game in games
    )

    sacrifice_flies = sum(
        game.statistics.sacrifice_flies
        for game in games
    )

    denominator = (
        at_bats
        + walks
        + hit_by_pitch
        + sacrifice_flies
    )

    if denominator == 0:
        return None

    return (
        hits
        + walks
        + hit_by_pitch
    ) / denominator


def _calculate_slugging_percentage(
    *,
    games: Sequence[HistoricalTeamGame],
) -> float | None:
    """
    Calculate aggregate slugging percentage over the supplied window.

    Formula:

        Total bases / At-bats
    """

    if not games:
        return None

    at_bats = sum(
        game.statistics.at_bats
        for game in games
    )

    if at_bats == 0:
        return None

    hits = sum(
        game.statistics.hits
        for game in games
    )

    doubles = sum(
        game.statistics.doubles
        for game in games
    )

    triples = sum(
        game.statistics.triples
        for game in games
    )

    home_runs = sum(
        game.statistics.home_runs
        for game in games
    )

    singles = (
        hits
        - doubles
        - triples
        - home_runs
    )

    total_bases = (
        singles
        + (2 * doubles)
        + (3 * triples)
        + (4 * home_runs)
    )

    return total_bases / at_bats