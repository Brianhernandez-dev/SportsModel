from pathlib import Path


WRAPPER_PATH = (
    Path(__file__).parents[2]
    / "scripts"
    / "run_moneyline_odds_snapshot.ps1"
)


def test_live_snapshot_uses_shared_database_readiness() -> None:
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8-sig")

    assert (
        '"scripts\\wait_for_sportsmodel_database.ps1"'
        in wrapper
    )
    assert ". $DatabaseReadinessPath" in wrapper
    assert "Wait-SportsModelDatabaseReady" in wrapper


def test_non_live_modes_exit_before_database_readiness() -> None:
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8-sig")

    readiness_call = wrapper.index(
        "Wait-SportsModelDatabaseReady"
    )

    assert wrapper.index("if ($ValidateOnly)") < readiness_call
    assert wrapper.index("if ($DryRun)") < readiness_call
    assert wrapper.index("exit 0", wrapper.index("if ($ValidateOnly)")) < (
        readiness_call
    )
    assert wrapper.index("exit 0", wrapper.index("if ($DryRun)")) < (
        readiness_call
    )


def test_database_readiness_precedes_live_odds_ingestion() -> None:
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8-sig")

    readiness_call = wrapper.index(
        "Wait-SportsModelDatabaseReady"
    )
    ingestion_call = wrapper.index(
        "& $PythonPath `",
        readiness_call,
    )

    assert readiness_call < ingestion_call
