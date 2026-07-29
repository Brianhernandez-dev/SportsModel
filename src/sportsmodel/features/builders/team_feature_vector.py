from sportsmodel.features.builders.base import (
    FeatureBuilder,
)
from sportsmodel.features.builders.bullpen import (
    BullpenFeatureBuilder,
)
from sportsmodel.features.builders.team_batting import (
    TeamBattingFeatureBuilder,
)
from sportsmodel.features.builders.team_pitching import (
    TeamPitchingFeatureBuilder,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.provider import (
    FeatureDataProvider,
)
from sportsmodel.models.team_feature_vector import (
    TeamFeatureVector,
)
from sportsmodel.models.team_schedule_features import (
    TeamScheduleFeatures,
)


class TeamFeatureVectorBuilder(
    FeatureBuilder[TeamFeatureVector],
):
    """
    Assemble all team-level feature groups for one team.

    Batting, pitching, and bullpen features are generated from historical
    point-in-time data. Schedule features temporarily use an explicit
    unavailable feature object until their dedicated builder is implemented.
    """

    def __init__(
        self,
        *,
        team_id: int,
    ) -> None:
        if team_id <= 0:
            raise ValueError(
                "Team feature vector builder team ID must be "
                "greater than zero."
            )

        self._team_id = team_id

    @property
    def team_id(self) -> int:
        """
        Return the team whose feature vector will be generated.
        """

        return self._team_id

    def build(
        self,
        context: FeatureGenerationContext,
        provider: FeatureDataProvider,
    ) -> TeamFeatureVector:
        """
        Build the complete typed feature vector for the configured team.
        """

        self._validate_context_team(context)
        self._validate_provider_context(
            context=context,
            provider=provider,
        )

        batting = TeamBattingFeatureBuilder(
            team_id=self._team_id,
        ).build(
            context,
            provider,
        )

        pitching = TeamPitchingFeatureBuilder(
            team_id=self._team_id,
        ).build(
            context,
            provider,
        )

        return TeamFeatureVector(
            team_id=self._team_id,
            batting=batting,
            pitching=pitching,
            bullpen=BullpenFeatureBuilder(
                team_id=self._team_id,
            ).build(
                context,
                provider,
            ),
            schedule=_build_unavailable_schedule_features(),
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
                "Team feature vector builder team ID must match "
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


def _build_unavailable_schedule_features() -> TeamScheduleFeatures:
    """
    Return the temporary unavailable schedule feature group.

    Replace this helper with TeamScheduleFeatureBuilder output when that
    dedicated builder is implemented.
    """

    return TeamScheduleFeatures(
        days_since_previous_game=None,
        played_previous_day=False,
        games_in_previous_3_days=0,
        games_in_previous_7_days=0,
        doubleheader_game=False,
        current_home_stand_length=0,
        current_road_trip_length=0,
    )
