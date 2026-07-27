from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.provider import (
    FeatureDataProvider,
)


FeatureResultT = TypeVar("FeatureResultT")


class FeatureBuilder(
    ABC,
    Generic[FeatureResultT],
):
    """
    Abstract contract implemented by every feature builder.

    Each builder receives the immutable feature-generation context and
    the shared data provider for that game, then returns one strongly
    typed feature result.
    """

    @abstractmethod
    def build(
        self,
        context: FeatureGenerationContext,
        provider: FeatureDataProvider,
    ) -> FeatureResultT:
        """
        Generate one feature result for the supplied game context.
        """