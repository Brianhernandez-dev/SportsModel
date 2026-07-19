from collections.abc import Iterable
from datetime import datetime

from sportsmodel.features.context import (
    FeatureGenerationContext,
)


class FeatureValidationError(ValueError):
    """
    Raised when a feature-generation contract is invalid.
    """


def validate_feature_generation_context(
    context: FeatureGenerationContext,
) -> None:
    """
    Validate the identifiers and timestamps in a feature context.

    Feature generation requires timezone-aware timestamps and a cutoff
    that does not occur after the scheduled game start.
    """

    if context.game_id <= 0:
        raise FeatureValidationError(
            "Game ID must be greater than zero."
        )

    if context.home_team_id <= 0:
        raise FeatureValidationError(
            "Home team ID must be greater than zero."
        )

    if context.away_team_id <= 0:
        raise FeatureValidationError(
            "Away team ID must be greater than zero."
        )

    if context.home_team_id == context.away_team_id:
        raise FeatureValidationError(
            "Home and away teams must be different."
        )

    _validate_optional_identifier(
        identifier=context.home_starting_pitcher_id,
        field_name="Home starting pitcher ID",
    )

    _validate_optional_identifier(
        identifier=context.away_starting_pitcher_id,
        field_name="Away starting pitcher ID",
    )

    _validate_timezone_aware(
        value=context.game_start_time,
        field_name="Game start time",
    )

    _validate_timezone_aware(
        value=context.cutoff_time,
        field_name="Cutoff time",
    )

    if context.cutoff_time > context.game_start_time:
        raise FeatureValidationError(
            "Feature cutoff time cannot occur after game start time."
        )


def validate_source_event_times(
    source_event_times: Iterable[datetime],
    cutoff_time: datetime,
) -> None:
    """
    Ensure every source event occurred strictly before the cutoff.

    Events at the cutoff are excluded because they may represent
    information that was not available when the prediction was made.
    """

    _validate_timezone_aware(
        value=cutoff_time,
        field_name="Cutoff time",
    )

    for source_event_time in source_event_times:
        _validate_timezone_aware(
            value=source_event_time,
            field_name="Source event time",
        )

        if source_event_time >= cutoff_time:
            raise FeatureValidationError(
                "Source event time must occur before the feature "
                "cutoff time."
            )


def _validate_optional_identifier(
    identifier: int | None,
    field_name: str,
) -> None:
    if identifier is not None and identifier <= 0:
        raise FeatureValidationError(
            f"{field_name} must be greater than zero when provided."
        )


def _validate_timezone_aware(
    value: datetime,
    field_name: str,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FeatureValidationError(
            f"{field_name} must be timezone-aware."
        )
