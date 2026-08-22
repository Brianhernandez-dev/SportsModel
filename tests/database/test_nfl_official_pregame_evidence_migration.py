from pathlib import Path


ROOT = Path(__file__).parents[2]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "030_create_nfl_official_pregame_evidence.sql"
)


def _sql() -> str:
    return " ".join(MIGRATION.read_text(encoding="utf-8").lower().split())


def test_migration_030_creates_distinct_immutable_official_boundary() -> None:
    sql = _sql()

    assert "create table nfl_official_pregame_evidence" in sql
    assert "odds_market_snapshot_id bigint not null unique" in sql
    assert "trg_nfl_official_pregame_evidence_immutable" in sql
    assert "before update or delete on nfl_official_pregame_evidence" in sql


def test_migration_030_uses_strict_trusted_time_and_current_nfl_kickoff() -> None:
    sql = _sql()

    assert "trusted_observed_at < canonical_kickoff_at_qualification" in sql
    assert "source_row.snapshot_observed_at >= source_row.current_canonical_kickoff" in sql
    assert "nfl.scheduled_start_time as current_canonical_kickoff" in sql
    assert "provider_commence_time" in sql
    assert "bookmaker_updated_at" in sql
    assert "market_updated_at" in sql


def test_migration_030_enforces_nfl_mapping_game_and_selection_coherence() -> None:
    sql = _sql()

    assert "requires canonical nfl event mapping" in sql
    assert "snapshot_game_id <> source_row.mapped_game_id" in sql
    assert "canonical selection team does not match provider selection" in sql
    assert "run_sport <> 'americanfootball_nfl'" in sql
    assert "run_status <> 'completed'" in sql


def test_migration_030_is_additive_and_does_not_retrofit_raw_or_mlb_rows() -> None:
    sql = _sql()

    assert "update odds_market_snapshots" not in sql
    assert "update odds_provider_event_observations" not in sql
    assert "alter table odds_market_snapshots" not in sql
    assert "baseball_mlb" not in sql
