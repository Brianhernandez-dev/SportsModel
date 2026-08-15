from pathlib import Path


ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "database" / "migrations" / "023_create_nfl_game_persistence.sql"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8-sig")


def test_migration_023_is_additive_and_has_required_relationships() -> None:
    sql = _sql()
    assert "CREATE TABLE nfl_ingestion_runs" in sql
    assert "CREATE TABLE nfl_games" in sql
    assert "CREATE TABLE nfl_game_source_observations" in sql
    assert "REFERENCES games(game_id)" in sql
    assert "REFERENCES nfl_games(game_id)" in sql
    assert "REFERENCES nfl_ingestion_runs(nfl_ingestion_run_id)" in sql
    assert "ALTER TABLE games" not in sql
    assert "UPDATE games" not in sql
    assert "DELETE FROM" not in sql


def test_provider_evidence_and_status_constraints_are_explicit() -> None:
    sql = _sql()
    assert "source_asset TEXT NOT NULL" in sql
    assert "source_sha256 CHAR(64) NOT NULL" in sql
    assert "raw_payload JSONB NOT NULL" in sql
    assert "raw_row_sha256 CHAR(64) NOT NULL" in sql
    assert "provider_updated_at TIMESTAMPTZ" in sql
    assert "status IN ('final', 'unplayed')" in sql
    assert "season_type = 'postseason'" in sql
    assert "UNIQUE (nfl_ingestion_run_id, source_name, external_game_id," in sql


def test_migration_does_not_generalize_mlb_or_add_lifecycle_guesses() -> None:
    sql = _sql()
    assert "moneyline" not in sql.lower()
    assert "cancelled" not in sql.lower()
    assert "postponed" not in sql.lower()
    assert "suspended" not in sql.lower()
