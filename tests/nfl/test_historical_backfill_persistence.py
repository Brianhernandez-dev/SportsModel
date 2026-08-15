from dataclasses import replace

import pytest

from sportsmodel.nfl.game_persistence import NflIngestionResult
from sportsmodel.nfl.historical_backfill import HistoricalBackfillPlan
from sportsmodel.nfl.historical_backfill_cli import (
    AssetProvenance,
    PreparedHistoricalBackfill,
)
from sportsmodel.nfl.historical_backfill_persistence import (
    HistoricalBackfillValidationError,
    IntegrityCheck,
    build_integrity_result,
    persist_validated_historical_backfill,
)
from sportsmodel.nfl.historical_backfill_persistence_cli import (
    describe_database_target,
    main,
)


def _ingestion(run_id, processed, inserted, updated, quarantined=0):
    return NflIngestionResult(
        run_id, processed, processed, inserted, updated, quarantined
    )


def _prepared(*, ready=True, accepted_schedule=None):
    schedules = accepted_schedule or tuple(
        {"game_id": f"g{index:04d}", "season": 2018}
        for index in range(2227)
    )
    stats = tuple(
        {"game_id": f"g{season}", "season": season, "team": "DAL"}
        for season in range(2018, 2026)
    )
    plan = HistoricalBackfillPlan(
        season_from=2018, season_to=2025,
        selected_schedule_rows=tuple(schedules),
        accepted_schedule_rows=tuple(schedules),
        quarantined_schedule_rows=(),
        selected_team_statistics_rows=stats,
        accepted_team_statistics_rows=stats,
        issues=(), reviewed_override_game_ids=(),
        cancelled_buf_cin_absent=True,
    )
    provenance = (
        AssetProvenance("schedules", None, "schedule.csv", 1, 1, "a" * 64,
                        "2026-08-15T05:36:29Z"),
        AssetProvenance("teams", None, "teams.csv", 1, 32, "b" * 64,
                        "2026-08-15T05:36:29Z"),
    ) + tuple(
        AssetProvenance("team_statistics", season, f"stats-{season}.csv",
                        1, 1, str(season)[-1] * 64,
                        "2026-08-15T05:36:29Z")
        for season in range(2018, 2026)
    )
    report = {
        "backfill_ready": ready,
        "reconciliation": {"issue_count": 0 if ready else 1},
        "approved_schedule_contract": {"contract_satisfied": ready},
        "provenance": [{"retrieved_at": "2026-08-15T05:36:29Z"}],
    }
    return PreparedHistoricalBackfill(
        report=report, plan=plan, team_identities={"DAL": "1200"},
        provenance=provenance,
    )


def _ready_audit(*args, **kwargs):
    return build_integrity_result([IntegrityCheck("ok", True, 1, 1)])


def test_failed_validation_gate_makes_zero_persistence_calls():
    calls = []
    with pytest.raises(HistoricalBackfillValidationError):
        persist_validated_historical_backfill(
            object(), prepared=_prepared(ready=False),
            game_ingest=lambda *a, **k: calls.append("game"),
            statistics_ingest=lambda *a, **k: calls.append("stats"),
            audit=_ready_audit,
        )
    assert calls == []


def test_default_contract_is_recomputed_from_retained_plan():
    forged = _prepared(accepted_schedule=(
        {"game_id": "only-one", "season": 2018},
    ))
    with pytest.raises(HistoricalBackfillValidationError):
        persist_validated_historical_backfill(
            object(), prepared=forged,
            game_ingest=lambda *a, **k: pytest.fail("must not persist"),
            statistics_ingest=lambda *a, **k: pytest.fail("must not persist"),
            audit=_ready_audit,
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_later_annual_provenance_failure_precedes_schedule_writer(mutation):
    prepared = _prepared()
    annual_2025 = next(
        item for item in prepared.provenance
        if item.logical_role == "team_statistics" and item.season == 2025
    )
    if mutation == "missing":
        provenance = tuple(
            item for item in prepared.provenance if item is not annual_2025
        )
    else:
        provenance = prepared.provenance + (annual_2025,)
    prepared = replace(prepared, provenance=provenance)
    calls = []
    with pytest.raises(HistoricalBackfillValidationError):
        persist_validated_historical_backfill(
            object(), prepared=prepared,
            game_ingest=lambda *a, **k: calls.append("game"),
            statistics_ingest=lambda *a, **k: calls.append("stats"),
            audit=_ready_audit,
        )
    assert calls == []


def test_valid_gate_persists_accepted_schedule_once():
    accepted = tuple(
        {"game_id": f"accepted-{index:04d}", "season": 2018}
        for index in range(2227)
    )
    calls = []
    result = persist_validated_historical_backfill(
        object(), prepared=_prepared(accepted_schedule=accepted),
        game_ingest=lambda connection, **kwargs: (
            calls.append(kwargs) or _ingestion(1, 1, 1, 0)
        ),
        statistics_ingest=lambda connection, **kwargs: _ingestion(
            int(kwargs["rows"][0]["season"]), 1, 1, 0
        ),
        audit=_ready_audit,
    )
    assert len(calls) == 1
    assert calls[0]["rows"] == accepted
    assert result.schedule.rows_inserted == 1


def test_annual_stats_are_separate_ordered_and_keep_provenance():
    calls = []
    result = persist_validated_historical_backfill(
        object(), prepared=_prepared(),
        game_ingest=lambda *a, **k: _ingestion(1, 1, 1, 0),
        statistics_ingest=lambda connection, **kwargs: (
            calls.append(kwargs) or _ingestion(len(calls) + 1, 1, 1, 0)
        ),
        audit=_ready_audit,
    )
    assert [int(call["rows"][0]["season"]) for call in calls] == list(range(2018, 2026))
    assert all(len(call["rows"]) == 1 for call in calls)
    assert [call["source_asset"] for call in calls] == [
        f"stats-{season}.csv" for season in range(2018, 2026)
    ]
    assert len({call["source_sha256"] for call in calls}) == 8
    assert (result.team_statistics.processed,
            result.team_statistics.inserted,
            result.team_statistics.updated) == (8, 8, 0)


def test_second_pass_aggregate_reports_updates():
    result = persist_validated_historical_backfill(
        object(), prepared=_prepared(),
        game_ingest=lambda *a, **k: _ingestion(1, 1, 0, 1),
        statistics_ingest=lambda *a, **k: _ingestion(2, 1, 0, 1),
        audit=_ready_audit,
    )
    assert (result.team_statistics.processed,
            result.team_statistics.inserted,
            result.team_statistics.updated) == (8, 0, 8)


def _minimal_cli_args():
    return ["--schedules", "missing.csv", "--teams", "missing-teams.csv",
            "--team-stats-dir", "missing-stats", "--retrieved-at",
            "2026-08-15T05:36:29Z"]


def test_cli_refuses_missing_confirmation_without_connection():
    calls = []
    assert main(_minimal_cli_args() + ["--database-url", "postgresql://u:p@h/db"],
                connect=lambda url: calls.append(url)) == 2
    assert calls == []


def test_cli_refuses_missing_database_url_without_environment_fallback(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://production.example/prod")
    monkeypatch.setenv("SPORTSMODEL_TEST_DATABASE_URL", "postgresql://test/db")
    calls = []
    assert main(_minimal_cli_args() + ["--confirm-persist"],
                connect=lambda url: calls.append(url)) == 2
    assert calls == []


def test_target_description_never_exposes_password():
    description = describe_database_target(
        "postgresql://user:top-secret@db.example:5544/disposable"
    )
    assert description == "host=db.example port=5544 database=disposable"
    assert "top-secret" not in description


def test_target_description_wraps_malformed_port_as_input_error():
    from sportsmodel.nfl.historical_backfill_cli import (
        HistoricalBackfillInputError,
    )

    with pytest.raises(HistoricalBackfillInputError, match="invalid port"):
        describe_database_target("postgresql://db.example:not-a-port/disposable")


def test_integrity_result_structure_and_ready_behavior():
    ready = build_integrity_result([IntegrityCheck("count", True, 2, 2)])
    failed = build_integrity_result([
        IntegrityCheck("count", True, 2, 2),
        IntegrityCheck("orphan", False, 1, 0),
    ])
    assert ready.ready and ready.failed_checks == ()
    assert not failed.ready
    assert failed.failed_checks == ("orphan",)
