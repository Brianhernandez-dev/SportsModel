from pathlib import Path


ROOT = Path(__file__).parents[2]
MIGRATION = (
    ROOT / "database" / "migrations" / "029_add_nfl_odds_canonical_identity.sql"
)


def _sql() -> str:
    return " ".join(MIGRATION.read_text(encoding="utf-8").lower().split())


def test_migration_029_seeds_exact_existing_only_nfl_team_identities() -> None:
    sql = _sql()

    assert "insert into nfl_team_sources" in sql
    assert "join nfl_team_profiles" in sql
    assert "source_name = 'odds_api'" in sql
    assert "exactly 32 odds api nfl team identities are required" in sql
    assert "insert into nfl_team_profiles" not in sql
    assert "insert into teams" not in sql


def test_migration_029_adds_immutable_oriented_existing_game_mapping() -> None:
    sql = _sql()

    assert "create table nfl_odds_provider_event_mappings" in sql
    assert "references nfl_games(game_id)" in sql
    assert "fk_nfl_odds_mapping_canonical_matchup" in sql
    assert "canonical_home_team_id" in sql
    assert "canonical_away_team_id" in sql
    assert "unique ( provider_name, provider_sport_key, external_event_id )" in sql
    assert "trg_nfl_odds_provider_event_mapping_immutable" in sql


def test_migration_029_enforces_nfl_sport_and_fifteen_minute_drift() -> None:
    sql = _sql()

    assert "provider_sport_key = 'americanfootball_nfl'" in sql
    assert "between canonical_kickoff - interval '15 minutes'" in sql
    assert "nfl_odds_provider_event_mapping_id is null or provider_sport_key" in sql


def test_migration_029_links_observations_without_rewriting_existing_rows() -> None:
    sql = _sql()

    assert "alter table odds_provider_event_observations add column" in sql
    assert "fk_odds_event_observation_nfl_mapping" in sql
    assert "update odds_provider_event_observations" not in sql
    assert "update games" not in sql
