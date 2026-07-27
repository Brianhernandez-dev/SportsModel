from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.features import (
    FeatureDataProvider,
    FeatureGenerationContext,
)
from sportsmodel.features.builders import (
    FeatureBuilder,
)


class ExampleBuilder(FeatureBuilder[int]):
    def build(
        self,
        context: FeatureGenerationContext,
        provider: FeatureDataProvider,
    ) -> int:
        assert provider.context is context

        return context.game_id


def build_context() -> FeatureGenerationContext:
    game_start_time = datetime(
        2026,
        7,
        19,
        1,
        10,
        tzinfo=timezone.utc,
    )

    return FeatureGenerationContext(
        game_id=100,
        game_start_time=game_start_time,
        cutoff_time=game_start_time - timedelta(hours=1),
        home_team_id=10,
        away_team_id=20,
        home_starting_pitcher_id=30,
        away_starting_pitcher_id=40,
    )


def test_feature_builder_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        FeatureBuilder()


def test_concrete_feature_builder_returns_typed_result() -> None:
    context = build_context()
    provider = FeatureDataProvider(context)
    builder = ExampleBuilder()

    result = builder.build(
        context=context,
        provider=provider,
    )

    assert result == 100