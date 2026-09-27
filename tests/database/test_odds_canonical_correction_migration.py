from pathlib import Path


ROOT = Path(__file__).parents[2]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "033_add_odds_canonical_corrections.sql"
)


def _sql() -> str:
    return " ".join(MIGRATION.read_text(encoding="utf-8").lower().split())


def test_migration_033_is_append_only_and_does_not_rewrite_evidence() -> None:
    sql = _sql()

    assert "create table odds_provider_event_canonical_corrections" in sql
    assert "unique (odds_provider_event_observation_id)" in sql
    assert "check (original_game_id <> corrected_game_id)" in sql
    assert "trg_odds_event_canonical_correction_immutable" in sql
    assert "reject_odds_source_identity_mutation()" in sql
    assert "update odds_market_snapshots" not in sql
    assert "delete from odds_market_snapshots" not in sql
    assert "update odds_provider_event_observations" not in sql
    assert "update odds_ingestion_runs" not in sql


def test_migration_033_validates_observation_identity_and_fails_closed() -> None:
    sql = _sql()

    assert "observation_source_name is distinct from 'odds_api'" in sql
    assert "observation_sport_key is distinct from 'baseball_mlb'" in sql
    assert "count(distinct snapshot.game_id)" in sql
    assert "snapshot_game_id is distinct from new.original_game_id" in sql
    assert "provider team orientation does not match corrected game" in sql
    assert "event_mapping_game_id is distinct from new.corrected_game_id" in sql
    assert "authoritative_candidate_count <> 1" in sql
    assert "authoritative_source.source_name = 'mlb_stats'" in sql


def test_migration_033_centralizes_raw_and_effective_identity() -> None:
    sql = _sql()

    assert "create view odds_market_snapshots_effective as" in sql
    assert "snapshot.game_id as raw_acquisition_game_id" in sql
    assert (
        "coalesce( correction.corrected_game_id, snapshot.game_id ) "
        "as effective_game_id"
    ) in sql
