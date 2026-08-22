from pathlib import Path


ROOT = Path(__file__).parents[2]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "028_add_odds_source_provenance.sql"
)


def _sql() -> str:
    return " ".join(
        MIGRATION.read_text(encoding="utf-8").lower().split()
    )


def test_migration_028_adds_secret_free_run_request_response_context() -> None:
    sql = _sql()

    for column in (
        "request_path",
        "request_regions",
        "request_markets",
        "request_odds_format",
        "request_commence_time_from",
        "request_commence_time_to",
        "request_started_at",
        "response_received_at",
    ):
        assert f"add column {column}" in sql
    assert "position('apikey' in lower(request_path)) = 0" in sql
    assert "api_key" not in sql
    assert "raw_payload" not in sql


def test_migration_028_adds_provider_book_and_event_identity() -> None:
    sql = _sql()

    assert "create table sportsbook_provider_identities" in sql
    assert "unique (provider_name, provider_bookmaker_key)" in sql
    assert "unique (sportsbook_id, provider_name)" in sql
    assert "create table odds_provider_event_observations" in sql
    assert "provider_sport_key varchar(50) not null" in sql
    assert "external_event_id varchar(255) not null" in sql
    assert "provider_commence_time timestamptz not null" in sql
    assert "provider_home_team_name varchar(150) not null" in sql
    assert "provider_away_team_name varchar(150) not null" in sql


def test_migration_028_enforces_cross_row_source_consistency() -> None:
    sql = _sql()

    assert "fk_odds_event_observation_run_source" in sql
    assert "provider_sport_key, source_name, observed_at" in sql
    assert "sport, source_name, response_received_at" in sql
    assert "fk_odds_snapshot_event_observation" in sql
    assert "fk_odds_snapshot_provider_sportsbook" in sql
    assert "snapshot_time = observed_at" in sql


def test_migration_028_protects_only_new_provenance_rows() -> None:
    sql = _sql()

    assert "trg_sportsbook_provider_identity_immutable" in sql
    assert "trg_odds_event_observation_immutable" in sql
    assert "trg_odds_snapshot_provenance_immutable" in sql
    assert "trg_odds_ingestion_run_provenance_immutable" in sql
    assert "old.request_started_at is not null" in sql
    assert "old.odds_provider_event_observation_id is not null" in sql
    assert "update odds_ingestion_runs set" not in sql
    assert "update odds_market_snapshots set" not in sql
