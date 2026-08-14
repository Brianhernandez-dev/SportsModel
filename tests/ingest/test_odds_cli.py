from datetime import date
from types import SimpleNamespace

import pytest

from sportsmodel.ingest.odds_cli import (
    main,
)


def _result(
    *,
    target_date: date | None,
    snapshot_role: str,
):
    return SimpleNamespace(
        odds_ingestion_run_id=184,
        target_date=target_date,
        snapshot_role=snapshot_role,
        status_code=200,
        remaining_requests=486,
        used_requests=14,
        games_returned=12,
        games_processed=12,
        selections_inserted=240,
        selections_skipped=0,
    )


def test_help_does_not_execute_ingestion(
    capsys,
) -> None:
    calls = 0

    def fake_fetcher(**unused_arguments):
        nonlocal calls
        calls += 1

    with pytest.raises(SystemExit) as error:
        main(
            ["--help"],
            odds_fetcher=fake_fetcher,
        )

    assert error.value.code == 0
    assert calls == 0

    output = capsys.readouterr().out

    assert "ingestion-only" in output
    assert "--snapshot-role" in output
    assert "--target-date" in output


def test_executes_manual_snapshot_by_default(
    capsys,
) -> None:
    calls = []

    def fake_fetcher(**arguments):
        calls.append(arguments)
        return _result(
            target_date=None,
            snapshot_role="manual",
        )

    exit_code = main(
        [],
        odds_fetcher=fake_fetcher,
    )

    assert exit_code == 0
    assert calls == [
        {
            "target_date": None,
            "snapshot_role": "manual",
        }
    ]

    output = capsys.readouterr().out

    assert "Ingestion run ID:  184" in output
    assert "Snapshot role:     manual" in output
    assert "Requests remaining: 486" in output


@pytest.mark.parametrize(
    "snapshot_role",
    (
        "evening",
        "late_night",
        "morning",
    ),
)
def test_executes_scheduled_auxiliary_snapshot(
    capsys,
    snapshot_role: str,
) -> None:
    calls = []

    def fake_fetcher(**arguments):
        calls.append(arguments)
        return _result(
            target_date=date(2026, 8, 7),
            snapshot_role=snapshot_role,
        )

    exit_code = main(
        [
            "--snapshot-role",
            snapshot_role,
            "--target-date",
            "2026-08-07",
        ],
        odds_fetcher=fake_fetcher,
    )

    assert exit_code == 0
    assert calls == [
        {
            "target_date": date(2026, 8, 7),
            "snapshot_role": snapshot_role,
        }
    ]

    output = capsys.readouterr().out

    assert "Target date:       2026-08-07" in output
    assert f"Snapshot role:     {snapshot_role}" in output


def test_scheduled_role_requires_target_date(
    capsys,
) -> None:
    calls = 0

    def fake_fetcher(**unused_arguments):
        nonlocal calls
        calls += 1

    with pytest.raises(SystemExit) as error:
        main(
            [
                "--snapshot-role",
                "afternoon",
            ],
            odds_fetcher=fake_fetcher,
        )

    assert error.value.code == 2
    assert calls == 0

    output = capsys.readouterr().err

    assert (
        "--target-date is required for scheduled "
        "snapshot roles"
        in output
    )


def test_entry_role_is_not_available_to_cli(
    capsys,
) -> None:
    calls = 0

    def fake_fetcher(**unused_arguments):
        nonlocal calls
        calls += 1

    with pytest.raises(SystemExit) as error:
        main(
            [
                "--snapshot-role",
                "entry",
                "--target-date",
                "2026-08-07",
            ],
            odds_fetcher=fake_fetcher,
        )

    assert error.value.code == 2
    assert calls == 0

    output = capsys.readouterr().err

    assert "invalid choice" in output
    assert "entry" in output


def test_returns_failure_when_ingestion_raises(
    capsys,
) -> None:
    def failing_fetcher(**arguments):
        assert arguments == {
            "target_date": None,
            "snapshot_role": "manual",
        }

        raise RuntimeError(
            "quota unavailable"
        )

    exit_code = main(
        [],
        odds_fetcher=failing_fetcher,
    )

    assert exit_code == 1

    output = capsys.readouterr().out

    assert (
        "MLB Moneyline odds ingestion failed"
        in output
    )
    assert "quota unavailable" in output
