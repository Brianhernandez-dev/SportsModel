from sportsmodel.features.builders.base import (
    FeatureBuilder,
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
from sportsmodel.models.starting_pitcher_features import (
    StartingPitcherFeatures,
)


DEFAULT_FEATURE_SCHEMA_VERSION = "1.0.0"


class GameFeatureVectorBuilder(
    FeatureBuilder[GameFeatureVector],
):
    """
    Assemble the complete pregame feature vector for one MLB game.

    Team batting and pitching features are generated through the team
    feature-vector builders. Starting-pitcher statistics temporarily use
    explicit unavailable-statistic objects until the dedicated pitcher
    feature builder is implemented.
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
                _build_placeholder_starting_pitcher_features(
                    player_id=(
                        context.home_starting_pitcher_id
                    ),
                )
            ),
            away_starting_pitcher=(
                _build_placeholder_starting_pitcher_features(
                    player_id=(
                        context.away_starting_pitcher_id
                    ),
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


def _build_placeholder_starting_pitcher_features(
    *,
    player_id: int | None,
) -> StartingPitcherFeatures:
    """
    Build a valid temporary starting-pitcher feature group.

    A supplied player ID means the expected starter is known, although
    historical pitcher statistics are not yet generated. A missing player
    ID means no reliable starter was available at the feature cutoff.
    """

    return StartingPitcherFeatures(
        player_id=player_id,
        starter_available=player_id is not None,
        starts_season=0,
        starts_last_5=0,
        innings_per_start_season=None,
        earned_run_average_season=None,
        earned_run_average_last_5=None,
        whip_season=None,
        whip_last_5=None,
        strikeouts_per_nine_season=None,
        walks_per_nine_season=None,
        home_runs_per_nine_season=None,
        days_rest=None,
    )
