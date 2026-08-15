import pytest

from sportsmodel.database.nfl_team_repository import (
    list_active_nfl_teams,
    load_nfl_team_by_franchise_key,
    load_nfl_team_by_id,
    load_nfl_team_season,
    resolve_nfl_team_by_source,
    upsert_nfl_team_source,
)
from sportsmodel.nfl.team_identity import (
    NflConference,
    NflDivision,
)


FRANCHISE_KEY = (
    "nfl_franchise_38f7d31e-ff94-48ec-905a-0c80ca64c6db"
)
PROFILE_ROW = (101, FRANCHISE_KEY, "LV", True)


class FakeCursor:
    def __init__(self, *, rows=(), row_batches=()) -> None:
        self.rows = list(rows)
        self.row_batches = list(row_batches)
        self.executions = []

    def execute(self, query, parameters=None) -> None:
        self.executions.append((query, parameters))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return self.row_batches.pop(0) if self.row_batches else []


def test_loads_team_by_project_identities() -> None:
    by_key_cursor = FakeCursor(rows=(PROFILE_ROW,))
    by_id_cursor = FakeCursor(rows=(PROFILE_ROW,))

    by_key = load_nfl_team_by_franchise_key(
        by_key_cursor,
        franchise_key=FRANCHISE_KEY,
    )
    by_id = load_nfl_team_by_id(by_id_cursor, team_id=101)

    assert by_key == by_id
    assert by_key.current_abbreviation == "LV"
    assert by_key_cursor.executions[0][1] == (FRANCHISE_KEY,)
    assert by_id_cursor.executions[0][1] == (101,)


def test_resolves_stable_nflverse_identity() -> None:
    cursor = FakeCursor(rows=(PROFILE_ROW, PROFILE_ROW))

    oakland_alias = resolve_nfl_team_by_source(
        cursor,
        source_name="nflverse",
        external_team_id="2520",
    )
    las_vegas_alias = resolve_nfl_team_by_source(
        cursor,
        source_name="nflverse",
        external_team_id="2520",
    )

    assert oakland_alias == las_vegas_alias
    assert oakland_alias.franchise_key == FRANCHISE_KEY


def test_unknown_provider_identity_is_explicit() -> None:
    cursor = FakeCursor()

    with pytest.raises(LookupError, match="nflverse/unknown"):
        resolve_nfl_team_by_source(
            cursor,
            source_name="nflverse",
            external_team_id="unknown",
        )


def test_lists_only_active_teams_in_abbreviation_order() -> None:
    cursor = FakeCursor(
        row_batches=(
            (
                (
                    102,
                    "nfl_franchise_115e5e7f-0cb9-4961-a6a2-4baa5ca5c26f",
                    "ARI",
                    True,
                ),
                PROFILE_ROW,
            ),
        )
    )

    teams = list_active_nfl_teams(cursor)

    assert tuple(team.current_abbreviation for team in teams) == (
        "ARI",
        "LV",
    )
    assert "WHERE is_active = TRUE" in cursor.executions[0][0]
    assert "ORDER BY current_abbreviation" in cursor.executions[0][0]


def test_loads_season_identity_separately_from_franchise() -> None:
    cursor = FakeCursor(
        rows=((101, 2019, "Oakland Raiders", "OAK", "AFC", "West"),)
    )

    season = load_nfl_team_season(cursor, team_id=101, season=2019)

    assert season.display_name == "Oakland Raiders"
    assert season.conference == NflConference.AFC
    assert season.division == NflDivision.WEST


def test_source_upsert_is_idempotent_for_same_team() -> None:
    source_row = (7, 101, "nflverse", "2520", "Las Vegas Raiders")
    cursor = FakeCursor(rows=(PROFILE_ROW, source_row))

    source = upsert_nfl_team_source(
        cursor,
        team_id=101,
        source_name="nflverse",
        external_team_id="2520",
        source_team_name="Las Vegas Raiders",
    )

    assert source.nfl_team_source_id == 7
    upsert_query = cursor.executions[1][0]
    assert "ON CONFLICT (source_name, external_team_id)" in upsert_query
    assert "nfl_team_sources.team_id = EXCLUDED.team_id" in upsert_query


def test_source_upsert_refuses_identity_reassignment() -> None:
    cursor = FakeCursor(rows=(PROFILE_ROW, None))

    with pytest.raises(ValueError, match="different team"):
        upsert_nfl_team_source(
            cursor,
            team_id=101,
            source_name="nflverse",
            external_team_id="2520",
        )


def test_source_upsert_requires_known_nfl_team() -> None:
    cursor = FakeCursor()

    with pytest.raises(LookupError, match="999"):
        upsert_nfl_team_source(
            cursor,
            team_id=999,
            source_name="nflverse",
            external_team_id="9999",
        )

    assert len(cursor.executions) == 1
