from pathlib import Path


ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "database" / "migrations" / "024_create_nfl_team_game_statistics.sql"


def test_migration_024_is_additive_typed_and_canonical() -> None:
    sql = MIGRATION.read_text(encoding="utf-8-sig")
    assert "CREATE TABLE nfl_team_game_statistics" in sql
    assert "CREATE TABLE nfl_team_game_statistics_source_observations" in sql
    assert "UNIQUE (game_id, team_id)" in sql
    assert "REFERENCES nfl_games(game_id)" in sql
    assert "REFERENCES teams(team_id)" in sql
    assert "raw_payload JSONB NOT NULL" in sql
    assert "completions SMALLINT NOT NULL" in sql
    assert "CHECK (completions <= pass_attempts)" in sql
    assert "ALTER TABLE" not in sql
    assert "DELETE FROM" not in sql


def test_migration_024_has_provenance_identity_and_access_indexes() -> None:
    sql = MIGRATION.read_text(encoding="utf-8-sig")
    assert "REFERENCES nfl_ingestion_runs(nfl_ingestion_run_id)" in sql
    assert "raw_row_sha256 CHAR(64) NOT NULL" in sql
    assert "uq_nfl_team_stats_observation_per_run" in sql
    assert "idx_nfl_team_game_statistics_team" in sql
    assert "idx_nfl_team_stats_observations_canonical" in sql
