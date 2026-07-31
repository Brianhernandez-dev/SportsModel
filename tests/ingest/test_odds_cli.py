import pytest

from sportsmodel.ingest.odds_cli import (
    main,
)


def test_help_does_not_execute_ingestion(
    capsys,
) -> None:
    calls = 0

    def fake_fetcher() -> None:
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

    assert (
        "Fetch and persist current pregame"
        in output
    )


def test_executes_one_ingestion_run() -> None:
    calls = 0

    def fake_fetcher() -> None:
        nonlocal calls
        calls += 1

    exit_code = main(
        [],
        odds_fetcher=fake_fetcher,
    )

    assert exit_code == 0
    assert calls == 1


def test_returns_failure_when_ingestion_raises(
    capsys,
) -> None:
    def failing_fetcher() -> None:
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
