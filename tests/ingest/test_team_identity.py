import pytest

from sportsmodel.ingest.mlb_stats import (
    get_team_id as get_mlb_stats_team_id,
)
from sportsmodel.ingest.odds_api import (
    get_team_id as get_odds_api_team_id,
)
from sportsmodel.ingest.team_identity import (
    normalize_team_name,
)


class RecordingCursor:
    def __init__(self) -> None:
        self.parameters: list[tuple[str]] = []

    def execute(
        self,
        query: str,
        parameters: tuple[str],
    ) -> None:
        self.parameters.append(parameters)

    def fetchone(self) -> tuple[int]:
        return (5,)


@pytest.mark.parametrize(
    ("source_name", "expected"),
    [
        ("Athletics", "Athletics"),
        ("Oakland Athletics", "Athletics"),
        ("  Oakland   Athletics  ", "Athletics"),
        ("Chicago Cubs", "Chicago Cubs"),
    ],
)
def test_normalize_team_name(
    source_name: str,
    expected: str,
) -> None:
    assert normalize_team_name(source_name) == expected


@pytest.mark.parametrize(
    "source_name",
    [
        "",
        " ",
        "\t",
    ],
)
def test_normalize_team_name_rejects_blank_values(
    source_name: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="team_name cannot be blank",
    ):
        normalize_team_name(source_name)


@pytest.mark.parametrize(
    "resolver",
    [
        get_mlb_stats_team_id,
        get_odds_api_team_id,
    ],
)
def test_ingestion_team_resolvers_use_canonical_name(
    resolver,
) -> None:
    cursor = RecordingCursor()

    team_id = resolver(
        cursor,
        "Oakland Athletics",
    )

    assert team_id == 5
    assert cursor.parameters == [
        ("Athletics",),
        ("Athletics",),
    ]
