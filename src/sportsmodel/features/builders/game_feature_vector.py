from sportsmodel.features.builders.base import (
    FeatureBuilder,
)
from sportsmodel.features.builders.starting_pitcher import (
    StartingPitcherFeatureBuilder,
)
from sportsmodel.features.builders.team_feature_vector import (
    TeamFeatureVectorBuilder,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.provider import (
    FeatureDataProvider,
)
from sportsmodel.models.game_feature_vector import (
    GameFeatureVector,
)


DEFAULT_FEATURE_SCHEMA_VERSION = "1.2.0"


class GameFeatureVectorBuilder(
    FeatureBuilder[GameFeatureVector],
):
    """
    Assemble the complete pregame feature vector for one MLB game.

    Team batting, pitching, and bullpen features are generated through
    the team feature-vector builders. Starting-pitcher statistics are
    generated from completed historical starts available before the cutoff.
    """

    def __init__(
        self,
        *,
        feature_schema_version: str = DEFAULT_FEATURE_SCHEMA_VERSION,
    ) -> None:
        if not feature_schema_version.strip():
            raise ValueError(
                "Feature schema version cannot be empty."
            )

        self._feature_schema_version = (
            feature_schema_version.strip()
        )

    @property
    def feature_schema_version(self) -> str:
        """
        Return the feature schema version produced by this builder.
        """

        return self._feature_schema_version

    def build(
        self,
        context: FeatureGenerationContext,
        provider: FeatureDataProvider,
    ) -> GameFeatureVector:
        """
        Build a complete point-in-time feature vector for one game.
        """

        self._validate_context(context)
        self._validate_provider_context(
            context=context,
            provider=provider,
        )

        home_team = TeamFeatureVectorBuilder(
            team_id=context.home_team_id,
        ).build(
            context,
            provider,
        )

        away_team = TeamFeatureVectorBuilder(
            team_id=context.away_team_id,
        ).build(
            context,
            provider,
        )

        return GameFeatureVector(
            game_id=context.game_id,
            game_start_time=context.game_start_time,
            feature_time=context.cutoff_time,
            feature_schema_version=(
                self._feature_schema_version
            ),
            home_team=home_team,
            away_team=away_team,
            home_starting_pitcher=(
                StartingPitcherFeatureBuilder(
                    player_id=(
                        context.home_starting_pitcher_id
                    ),
                ).build(
                    context,
                    provider,
                )
            ),
            away_starting_pitcher=(
                StartingPitcherFeatureBuilder(
                    player_id=(
                        context.away_starting_pitcher_id
                    ),
                ).build(
                    context,
                    provider,
                )
            ),
        )

    @staticmethod
    def _validate_context(
        context: FeatureGenerationContext,
    ) -> None:
        if context.game_id <= 0:
            raise ValueError(
                "Feature context game ID must be greater than zero."
            )

        if context.home_team_id <= 0:
            raise ValueError(
                "Feature context home team ID must be greater than zero."
            )

        if context.away_team_id <= 0:
            raise ValueError(
                "Feature context away team ID must be greater than zero."
            )

        if context.home_team_id == context.away_team_id:
            raise ValueError(
                "Feature context home and away teams must be different."
            )

        if (
            context.game_start_time.tzinfo is None
            or context.game_start_time.utcoffset() is None
        ):
            raise ValueError(
                "Feature context game start time must be "
                "timezone-aware."
            )

        if (
            context.cutoff_time.tzinfo is None
            or context.cutoff_time.utcoffset() is None
        ):
            raise ValueError(
                "Feature context cutoff time must be timezone-aware."
            )

        if context.cutoff_time > context.game_start_time:
            raise ValueError(
                "Feature context cutoff time cannot occur after "
                "game start time."
            )

        for pitcher_id in (
            context.home_starting_pitcher_id,
            context.away_starting_pitcher_id,
        ):
            if pitcher_id is not None and pitcher_id <= 0:
                raise ValueError(
                    "Starting pitcher IDs must be greater than zero "
                    "when provided."
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
