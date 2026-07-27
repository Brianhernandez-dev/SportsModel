from datetime import date

import pytest

from sportsmodel.ingest.mlb_results_cli import (
    DEFAULT_START_DATE,
    build_parser,
    main,
    parse_iso_date,
)
from sportsmodel.ingest.mlb_stats import (
    HistoricalResultsBackfillSummary,
    HistoricalResultsDateSummary,
)


def test_parse_iso_date_accepts_expected_format() -> None:
    assert parse_iso_date(
        "2025-04-01"
    ) == date(
        2025,
        4,
        1,
    )


def test_parse_iso_date_rejects_invalid_value() -> None:
    with pytest.raises(
        Exception,
        match="Expected YYYY-MM-DD",
    ):
        parse_iso_date(
            "04/01/2025"
        )


def test_parser_preserves_compatible_defaults() -> None:
    arguments = build_parser().parse_args([])

    assert arguments.start_date == DEFAULT_START_DATE
    assert arguments.end_date is None
    assert arguments.reingest_complete_boxscores is False


def test_main_forwards_dates_and_reingest_option() -> None:
    received_arguments = {}

    def fetcher(
        **kwargs,
    ) -> HistoricalResultsBackfillSummary:
        received_arguments.update(kwargs)

        return _summary(
            failed=False,
        )

    exit_code = main(
        [
            "--start-date",
            "2025-04-01",
            "--end-date",
            "2025-04-30",
            "--reingest-complete-boxscores",
        ],
        historical_results_fetcher=fetcher,
    )

    assert exit_code == 0

    assert received_arguments == {
        "start_date": date(
            2025,
            4,
            1,
        ),
        "end_date": date(
            2025,
            4,
            30,
        ),
        "skip_complete_boxscores": False,
    }


def test_main_returns_failure_for_partial_backfill() -> None:
    exit_code = main(
        [
            "--start-date",
            "2025-04-01",
            "--end-date",
            "2025-04-01",
        ],
        historical_results_fetcher=lambda **kwargs: (
            _summary(
                failed=True,
            )
        ),
    )

    assert exit_code == 1


def _summary(
    *,
    failed: bool,
) -> HistoricalResultsBackfillSummary:
    schedule_error = (
        "RuntimeError: schedule unavailable"
        if failed
        else None
    )

    date_summary = HistoricalResultsDateSummary(
        schedule_date=date(
            2025,
            4,
            1,
        ),
        schedule_games_received=0,
        finalized_games_processed=0,
        games_skipped=0,
        boxscores_processed=0,
        boxscores_skipped_complete=0,
        boxscores_failed=0,
        schedule_error=schedule_error,
    )

    return HistoricalResultsBackfillSummary(
        start_date=date(
            2025,
            4,
            1,
        ),
        end_date=date(
            2025,
            4,
            1,
        ),
        date_summaries=(
            date_summary,
        ),
    )
