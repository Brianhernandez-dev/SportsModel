from pathlib import Path


ROOT = Path(__file__).parents[2]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "032_allow_mlb_odds_event_replacements.sql"
)
GAME_SOURCES_MIGRATION = (
    ROOT / "database" / "migrations" / "003_create_game_sources.sql"
)


def _sql() -> str:
    return " ".join(
        MIGRATION.read_text(encoding="utf-8").lower().split()
    )


def test_migration_allows_retained_replacement_event_ids() -> None:
    sql = _sql()

    assert "drop index idx_game_sources_game_id_source_name" in sql
    assert "create index idx_game_sources_game_id_source_name" in sql
    assert "create unique index idx_game_sources_game_id_source_name" not in sql
    assert "create unique index uq_game_sources_game_id_non_odds_source" in sql
    assert "where source_name <> 'odds_api'" in sql


def test_global_provider_event_identity_remains_unique() -> None:
    sql = _sql()
    source_schema = " ".join(
        GAME_SOURCES_MIGRATION.read_text(encoding="utf-8").lower().split()
    )

    assert "unique (source_name, external_game_id)" in source_schema
    assert "drop constraint uq_game_source" not in sql


def test_migration_does_not_relax_snapshot_provenance() -> None:
    sql = _sql()

    assert "protect_odds_snapshot_provenance" not in sql
    assert "odds_market_snapshots" not in sql
