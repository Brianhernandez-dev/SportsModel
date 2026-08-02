from datetime import date
from types import SimpleNamespace

import pytest

from sportsmodel.orchestration.moneyline_daily_cli import (
    main,
)


def test_help_does_not_execute_pregame(
    capsys,
) -> None:
    calls = 0

    def fake_runner(**arguments):
        nonlocal calls
        calls += 1

    with pytest.raises(SystemExit) as error:
        main(
            ["--help"],
            pregame_runner=fake_runner,
        )

    assert error.value.code == 0
    assert calls == 0

    output = capsys.readouterr().out

    assert (
        "Run or safely resume the daily MLB"
        in output
    )


def test_executes_daily_pregame_run(
    capsys,
) -> None:
    calls = []

    def fake_runner(**arguments):
        calls.append(arguments)

        return SimpleNamespace(
            workflow_run_id=12,
            target_date=date(2026, 8, 2),
            prediction_run_id=25,
            odds_ingestion_run_id=182,
            predictions_created=10,
            evaluations_saved=10,
            paper_candidates=5,
            odds_remaining_requests=487,
            pipeline_state="awaiting_results",
        )

    exit_code = main(
        [
            "--target-date",
            "2026-08-02",
            "--schedule-days-ahead",
            "5",
        ],
        pregame_runner=fake_runner,
    )

    assert exit_code == 0
    assert calls == [
        {
            "target_date": date(2026, 8, 2),
            "schedule_days_ahead": 5,
        }
    ]

    output = capsys.readouterr().out

    assert "Workflow run ID:    12" in output
    assert "Prediction run ID:  25" in output
    assert "Odds run ID:        182" in output
    assert "Paper candidates:   5" in output
    assert "Pipeline state:     awaiting_results" in output


def test_returns_failure_when_pregame_raises(
    capsys,
) -> None:
    def failing_runner(**arguments):
        raise RuntimeError(
            "Odds provider unavailable."
        )

    exit_code = main(
        [],
        pregame_runner=failing_runner,
    )

    assert exit_code == 1

    output = capsys.readouterr().out

    assert (
        "Daily Moneyline pregame run failed"
        in output
    )
    assert "Odds provider unavailable." in output
