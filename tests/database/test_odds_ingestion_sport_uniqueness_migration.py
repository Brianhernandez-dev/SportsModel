from pathlib import Path


ROOT = Path(__file__).parents[2]
MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "027_make_odds_snapshot_uniqueness_sport_aware.sql"
)


def _sql() -> str:
    return " ".join(
        MIGRATION.read_text(encoding="utf-8").lower().split()
    )


def test_migration_027_replaces_scheduled_identity_with_sport() -> None:
    sql = _sql()

    assert (
        "drop index "
        "uq_odds_ingestion_runs_active_scheduled_snapshot"
    ) in sql
    assert (
        "create unique index "
        "uq_odds_ingestion_runs_active_scheduled_snapshot"
    ) in sql
    assert "on odds_ingestion_runs ( sport, target_date, snapshot_role )" in sql
    assert "status in ( 'running', 'completed' )" in sql


def test_migration_027_preserves_scheduled_and_manual_semantics() -> None:
    sql = _sql()

    for role in (
        "opening",
        "evening",
        "late_night",
        "morning",
        "entry",
        "afternoon",
        "near_close",
    ):
        assert f"'{role}'" in sql
    assert "'manual'" not in sql.split("where snapshot_role in", 1)[1]
    assert "update odds_ingestion_runs" not in sql
    assert "delete from odds_ingestion_runs" not in sql
