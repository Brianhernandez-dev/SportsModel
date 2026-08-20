from pathlib import Path


ROOT = Path(__file__).parents[2]
MIGRATION = (
    ROOT / "database" / "migrations"
    / "026_create_nfl_moneyline_predictions.sql"
)


def _sql() -> str:
    return " ".join(MIGRATION.read_text(encoding="utf-8").lower().split())


def test_migration_026_creates_nfl_specific_run_and_prediction_tables() -> None:
    sql = _sql()
    assert "create table nfl_moneyline_prediction_runs" in sql
    assert "create table nfl_moneyline_game_predictions" in sql
    assert "run_key uuid not null unique" in sql
    assert "check (season >= 2026)" in sql
    assert "run_type in ('official', 'preview')" in sql
    assert "status in ('running', 'completed', 'failed')" in sql


def test_migration_026_enforces_forward_evidence_invariants() -> None:
    sql = _sql()
    assert "prediction_created_at < target_kickoff" in sql
    assert "feature_cutoff = target_kickoff" in sql
    assert "latest_source_kickoff < feature_cutoff" in sql
    assert "selected_route = 'mature'" in sql
    assert "home_current_prior_games >= 3" in sql
    assert "selected_route = 'early'" in sql
    assert "home_current_prior_games < 3" in sql
    assert "model_home_win_probability between 0 and 1" in sql
    assert "classification_threshold between 0 and 1" in sql
    assert "predicted_side = 'home'" in sql
    assert "predicted_side = 'away'" in sql
    assert "jsonb_typeof(feature_payload) = 'object'" in sql
    assert "jsonb_typeof(source_trace_payload) = 'object'" in sql


def test_migration_026_enforces_official_uniqueness_and_immutability() -> None:
    sql = _sql()
    assert "create unique index uq_nfl_moneyline_official_game_protocol" in sql
    assert "where run_type = 'official'" in sql
    assert "before update on nfl_moneyline_game_predictions" in sql
    assert "before delete on nfl_moneyline_game_predictions" in sql
    assert "before delete on nfl_moneyline_prediction_runs" in sql
    assert "on delete restrict" in sql
    assert "new.prediction_created_at := clock_timestamp()" in sql
    assert "canonical.status <> 'unplayed'" in sql
    assert "actual_prediction_count <> new.target_count" in sql


def test_prediction_schema_excludes_out_of_scope_results_and_odds() -> None:
    prediction_table = _sql().split(
        "create table nfl_moneyline_game_predictions", 1
    )[1].split("create unique index", 1)[0]
    for excluded in (
        "actual_result",
        "home_win_target",
        "tie_result",
        "sportsbook",
        "market_edge",
        "settlement",
        "odds",
    ):
        assert excluded not in prediction_table
