from collections.abc import Callable, Hashable
from typing import TypeVar, cast

from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.validation import (
    validate_feature_generation_context,
)


CachedValueT = TypeVar("CachedValueT")


class FeatureDataProvider:
    """
    Shared point-in-time data provider for one feature-generation context.

    Feature builders use this provider rather than querying repositories
    directly. Values loaded through the provider may be cached for reuse
    by multiple builders generating features for the same game.

    Repository-specific lookup methods will be added as feature builders
    are implemented.
    """

    def __init__(
        self,
        context: FeatureGenerationContext,
    ) -> None:
        validate_feature_generation_context(context)

        self._context = context
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