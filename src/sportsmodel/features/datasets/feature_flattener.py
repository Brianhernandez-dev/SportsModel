from dataclasses import fields, is_dataclass
from typing import TypeAlias

from sportsmodel.models.game_feature_vector import (
    GameFeatureVector,
)


FlatFeatureValue: TypeAlias = bool | int | float | None
FlatFeatureMapping: TypeAlias = dict[str, FlatFeatureValue]


_EXCLUDED_FIELDS = frozenset(
    {
        "game_id",
        "game_start_time",
        "feature_time",
        "feature_schema_version",
        "team_id",
        "player_id",
    }
)


def flatten_game_feature_vector(
    vector: GameFeatureVector,
) -> FlatFeatureMapping:
    """
    Convert a nested game feature vector into a flat ML feature map.

    Metadata and database identifiers are intentionally excluded. The
    returned keys form the tabular input contract used by training,
    evaluation, and live prediction workflows.
    """

    if not isinstance(vector, GameFeatureVector):
        raise TypeError(
            "Vector must be a GameFeatureVector."
        )

    flattened: FlatFeatureMapping = {}

    _flatten_dataclass(
        value=vector.home_team,
        prefix="home",
        destination=flattened,
    )
    _flatten_dataclass(
        value=vector.away_team,
        prefix="away",
        destination=flattened,
    )
    _flatten_dataclass(
        value=vector.home_starting_pitcher,
        prefix="home_starting_pitcher",
        destination=flattened,
    )
    _flatten_dataclass(
        value=vector.away_starting_pitcher,
        prefix="away_starting_pitcher",
        destination=flattened,
    )

    return flattened


def _flatten_dataclass(
    *,
    value: object,
    prefix: str,
    destination: FlatFeatureMapping,
) -> None:
    if not is_dataclass(value):
        raise TypeError(
            f"Expected dataclass value for prefix '{prefix}'."
        )

    for field_definition in fields(value):
        field_name = field_definition.name

        if field_name in _EXCLUDED_FIELDS:
            continue

        field_value = getattr(
            value,
            field_name,
        )
        feature_name = (
            f"{prefix}_{field_name}"
            if prefix
            else field_name
        )

        if is_dataclass(field_value):
            _flatten_dataclass(
                value=field_value,
                prefix=feature_name,
                destination=destination,
            )
            continue

        _validate_flat_feature_value(
            feature_name=feature_name,
            value=field_value,
        )

        if feature_name in destination:
            raise ValueError(
                f"Duplicate flattened feature name: {feature_name}"
            )

        destination[feature_name] = field_value


def _validate_flat_feature_value(
    *,
    feature_name: str,
    value: object,
) -> None:
    if value is None:
        return

    if isinstance(
        value,
        (bool, int, float),
    ):
        return

    raise TypeError(
        "Unsupported flattened feature value for "
        f"'{feature_name}': {type(value).__name__}."
    )
