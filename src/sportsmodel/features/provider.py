from collections.abc import Callable, Hashable
from typing import TypeVar, cast

from sportsmodel.database.team_statistics_repository import (
    PostgresTeamStatisticsRepository,
    TeamStatisticsRepository,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.validation import (
    validate_feature_generation_context,
)
from sportsmodel.models.historical_team_game import (
    HistoricalTeamGame,
)


CachedValueT = TypeVar("CachedValueT")


class FeatureDataProvider:
    """
    Shared point-in-time data provider for one feature-generation context.

    Feature builders use this provider rather than querying repositories
    directly. Values loaded through the provider are cached for reuse by
    multiple builders generating features for the same game.
    """

    def __init__(
        self,
        context: FeatureGenerationContext,
        *,
        team_statistics_repository: (
            TeamStatisticsRepository | None
        ) = None,
    ) -> None:
        validate_feature_generation_context(context)

        self._context = context
        self._team_statistics_repository = (
            team_statistics_repository
            if team_statistics_repository is not None
            else PostgresTeamStatisticsRepository()
        )
        self._cache: dict[
            tuple[str, Hashable],
            object,
        ] = {}

    @property
    def context(self) -> FeatureGenerationContext:
        """
        Return the immutable feature-generation context.
        """

        return self._context

    @property
    def cache_size(self) -> int:
        """
        Return the number of values currently stored in the cache.
        """

        return len(self._cache)

    def get_completed_team_games(
        self,
        *,
        team_id: int,
        limit: int,
    ) -> tuple[HistoricalTeamGame, ...]:
        """
        Return a team's completed games before the context cutoff.

        Results are returned newest first and cached by team, cutoff,
        and requested limit.
        """

        cache_key = (
            team_id,
            self._context.cutoff_time,
            limit,
        )

        return self.get_or_create(
            namespace="completed_team_games",
            key=cache_key,
            loader=lambda: (
                self._team_statistics_repository
                .get_completed_games_before(
                    team_id=team_id,
                    cutoff_time=self._context.cutoff_time,
                    limit=limit,
                )
            ),
        )

    def get_or_create(
        self,
        namespace: str,
        key: Hashable,
        loader: Callable[[], CachedValueT],
    ) -> CachedValueT:
        """
        Return a cached value or create it with the supplied loader.

        Namespaces prevent unrelated data types from colliding when they
        happen to use the same lookup key.
        """

        normalized_namespace = namespace.strip()

        if not normalized_namespace:
            raise ValueError(
                "Feature data cache namespace cannot be empty."
            )

        if normalized_namespace != namespace:
            raise ValueError(
                "Feature data cache namespace cannot contain leading or "
                "trailing whitespace."
            )

        cache_key = (
            normalized_namespace,
            key,
        )

        if cache_key not in self._cache:
            self._cache[cache_key] = loader()

        return cast(
            CachedValueT,
            self._cache[cache_key],
        )

    def clear_cache(self) -> None:
        """
        Remove all cached values from the provider.
        """

        self._cache.clear()