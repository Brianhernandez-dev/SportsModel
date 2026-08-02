from datetime import date
from types import SimpleNamespace

import pytest

from sportsmodel.orchestration.moneyline_daily_postgame_cli import (
    main,
)


def test_help_does_not_execute_postgame(
    capsys,
) -> None:
    calls = 0

    def fake_runner(**arguments):
        nonlocal calls
        calls += 1

    with pytest.raises(SystemExit) as error:
        main(
            ["--help"],
            postgame_runner=fake_runner,
        )

    assert error.value.code == 0
    assert calls == 0

    output = capsys.readouterr().out
    assert "Run or safely resume" in output


def test_executes_daily_postgame_run(
    capsys,
) -> None:
    calls = []

    def fake_runner(**arguments):
        calls.append(arguments)

        return SimpleNamespace(
            workflow_run_id=12,
            target_date=date(2026, 8, 3),
            prediction_run_id=25,
            odds_ingestion_run_id=182,
            games_processed=8,
            boxscores_processed=8,
            settlements_saved=1,
            pending_candidates=0,
            pipeline_state="complete",
        )

    exit_code = main(
        [
            "--target-date",
            "2026-08-03",
        ],
        postgame_runner=fake_runner,
    )

    assert exit_code == 0
    assert calls == [
        {
            "target_date": date(2026, 8, 3),
        }
    ]

    output = capsys.readouterr().out
    assert "Workflow run ID:    12" in output
    assert "Settlements saved:  1" in output
    assert "Pipeline state:     complete" in output


def test_returns_failure_when_postgame_raises(
    capsys,
) -> None:
    def failing_runner(**arguments):
        raise RuntimeError(
            "Results unavailable."
        )

    exit_code = main(
        [],
        postgame_runner=failing_runner,
    )

    assert exit_code == 1

    output = capsys.readouterr().out
    assert "Daily Moneyline postgame run failed" in output
    assert "Results unavailable." in output
