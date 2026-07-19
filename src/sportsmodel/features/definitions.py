from dataclasses import dataclass
from enum import StrEnum


class FeatureGroup(StrEnum):
    """
    Logical feature groups supported by the MLB prediction pipeline.
    """

    TEAM_BATTING = "team_batting"

    TEAM_PITCHING = "team_pitching"

    STARTING_PITCHER = "starting_pitcher"

    BULLPEN = "bullpen"

    SCHEDULE = "schedule"

    MARKET = "market"


class FeatureDataType(StrEnum):
    """
    Data types supported by the feature registry.
    """

    BOOLEAN = "boolean"

    INTEGER = "integer"

    FLOAT = "float"

    DECIMAL = "decimal"


@dataclass(frozen=True)
class FeatureDefinition:
    """
    Describes one stable machine-learning feature.

    Feature definitions form the contract between feature builders,
    training datasets, exported files, and trained models.
    """

    name: str

    group: FeatureGroup

    data_type: FeatureDataType

    nullable: bool

    description: str

    version: int = 1

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()

        if not normalized_name:
            raise ValueError(
                "Feature definition name cannot be empty."
            )

        if normalized_name != self.name:
            raise ValueError(
                "Feature definition name cannot contain leading or "
                "trailing whitespace."
            )

        if not self.description.strip():
            raise ValueError(
                "Feature definition description cannot be empty."
            )

        if self.version < 1:
            raise ValueError(
                "Feature definition version must be at least 1."
            )
