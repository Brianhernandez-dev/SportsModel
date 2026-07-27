import pytest

from sportsmodel.features import (
    FeatureDataType,
    FeatureDefinition,
    FeatureGroup,
)


def test_feature_definition_stores_registry_metadata() -> None:
    definition = FeatureDefinition(
        name="home_batting_runs_per_game_10",
        group=FeatureGroup.TEAM_BATTING,
        data_type=FeatureDataType.FLOAT,
        nullable=False,
        description=(
            "Home team average runs scored over its previous "
            "10 completed games."
        ),
        version=1,
    )

    assert definition.name == (
        "home_batting_runs_per_game_10"
    )
    assert definition.group == FeatureGroup.TEAM_BATTING
    assert definition.data_type == FeatureDataType.FLOAT
    assert definition.nullable is False
    assert definition.version == 1


@pytest.mark.parametrize(
    "name",
    [
        "",
        " ",
        " feature_name",
        "feature_name ",
    ],
)
def test_feature_definition_rejects_invalid_names(
    name: str,
) -> None:
    with pytest.raises(ValueError):
        FeatureDefinition(
            name=name,
            group=FeatureGroup.TEAM_BATTING,
            data_type=FeatureDataType.FLOAT,
            nullable=False,
            description="Valid description.",
        )


def test_feature_definition_rejects_empty_description() -> None:
    with pytest.raises(ValueError):
        FeatureDefinition(
            name="feature_name",
            group=FeatureGroup.TEAM_BATTING,
            data_type=FeatureDataType.FLOAT,
            nullable=False,
            description=" ",
        )


def test_feature_definition_rejects_version_below_one() -> None:
    with pytest.raises(ValueError):
        FeatureDefinition(
            name="feature_name",
            group=FeatureGroup.TEAM_BATTING,
            data_type=FeatureDataType.FLOAT,
            nullable=False,
            description="Valid description.",
            version=0,
        )
