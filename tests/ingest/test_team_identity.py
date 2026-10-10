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
        ("Cleveland Guardians", "Cleveland Guardians"),
        ("Cleveland Indians", "Cleveland Guardians"),
        ("  Cleveland   Indians  ", "Cleveland Guardians"),
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


class PersistingTeamCursor:
    def __init__(self) -> None:
        self.team_ids: dict[str, int] = {}
        self.selected_name: str | None = None

    def execute(self, query: str, parameters: tuple[str]) -> None:
        team_name = parameters[0]
        if "INSERT INTO teams" in query:
            self.team_ids.setdefault(team_name, len(self.team_ids) + 1)
        elif "SELECT team_id" in query:
            self.selected_name = team_name

    def fetchone(self) -> tuple[int] | None:
        if self.selected_name is None:
            return None
        return (self.team_ids[self.selected_name],)


@pytest.mark.parametrize(
    "resolver",
    [
        get_mlb_stats_team_id,
        get_odds_api_team_id,
    ],
)
def test_cleveland_historical_alias_cannot_create_a_second_team(resolver) -> None:
    cursor = PersistingTeamCursor()

    guardians_id = resolver(cursor, "Cleveland Guardians")
    historical_id = resolver(cursor, "Cleveland Indians")

    assert guardians_id == historical_id == 1
    assert cursor.team_ids == {"Cleveland Guardians": 1}
