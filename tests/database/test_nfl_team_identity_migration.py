from pathlib import Path
import re
from uuid import UUID


ROOT = Path(__file__).parents[2]
MIGRATION_PATH = (
    ROOT
    / "database"
    / "migrations"
    / "022_create_nfl_team_identity.sql"
)
FOUNDATION_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "database"
    / "sportsmodel_foundation_schema.sql"
)
SEED_ROW_PATTERN = re.compile(
    r"^\s*\('(?P<abbreviation>[A-Z0-9]+)', "
    r"'(?P<display_name>[^']+)', "
    r"'nfl_franchise_(?P<uuid>[0-9a-f-]+)', "
    r"'(?P<external_team_id>[0-9]+)', "
    r"'(?P<conference>AFC|NFC)', "
    r"'(?P<division>East|North|South|West)'\)[,;]$",
    re.MULTILINE,
)


def _migration() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8-sig")


def _seed_rows() -> tuple[dict[str, str], ...]:
    return tuple(match.groupdict() for match in SEED_ROW_PATTERN.finditer(_migration()))


def test_foundation_fixture_captures_missing_shared_contracts() -> None:
    foundation = FOUNDATION_PATH.read_text(encoding="utf-8-sig")

    assert "CREATE TABLE teams" in foundation
    assert "team_id SERIAL PRIMARY KEY" in foundation
    assert "team_name VARCHAR(150) NOT NULL UNIQUE" in foundation
    assert "CREATE TABLE games" in foundation
    assert "REFERENCES teams(team_id)" in foundation
    assert "CREATE TABLE sportsbooks" in foundation
    assert "VALUES (5, 'Athletics')" in foundation
    assert "mlb_game_id BIGINT NOT NULL UNIQUE" in foundation


def test_migration_is_additive_and_defines_required_foreign_keys() -> None:
    migration = _migration()

    assert "CREATE TABLE nfl_team_profiles" in migration
    assert "CREATE TABLE nfl_team_seasons" in migration
    assert "CREATE TABLE nfl_team_sources" in migration
    assert "REFERENCES teams(team_id)" in migration
    assert "REFERENCES nfl_team_profiles(team_id)" in migration
    assert "PRIMARY KEY (team_id, season)" in migration
    assert "UNIQUE (source_name, external_team_id)" in migration
    assert "ALTER TABLE teams" not in migration
    assert "UPDATE games" not in migration
    assert "DELETE FROM" not in migration


def test_seed_contains_exactly_32_stable_unique_franchises() -> None:
    rows = _seed_rows()

    assert len(rows) == 32
    assert len({row["abbreviation"] for row in rows}) == 32
    assert len({row["uuid"] for row in rows}) == 32
    assert len({row["external_team_id"] for row in rows}) == 32
    for row in rows:
        assert str(UUID(row["uuid"])) == row["uuid"]


def test_nflverse_relocation_ids_map_to_one_current_franchise() -> None:
    by_abbreviation = {row["abbreviation"]: row for row in _seed_rows()}

    assert by_abbreviation["LAR"]["external_team_id"] == "2510"
    assert by_abbreviation["LV"]["external_team_id"] == "2520"
    assert by_abbreviation["LAC"]["external_team_id"] == "4400"
    assert "OAK" not in by_abbreviation
    assert "SD" not in by_abbreviation
    assert "STL" not in by_abbreviation


def test_seed_statements_are_repeatable_without_duplicate_identity() -> None:
    migration = _migration()
    simulated_profiles = {}
    simulated_sources = {}

    for _ in range(2):
        for row in _seed_rows():
            simulated_profiles[row["uuid"]] = row["abbreviation"]
            simulated_sources[row["external_team_id"]] = row["uuid"]

    assert len(simulated_profiles) == 32
    assert len(simulated_sources) == 32
    assert "ON CONFLICT (team_name) DO NOTHING" in migration
    assert "ON CONFLICT (team_id)" in migration
    assert "ON CONFLICT (team_id, season)" in migration
    assert "ON CONFLICT (source_name, external_team_id)" in migration


def test_current_season_alignment_is_seeded() -> None:
    migration = _migration()

    assert "INSERT INTO nfl_team_seasons" in migration
    assert re.search(r"\n\s*2026,\n\s*seed\.display_name", migration)
