from datetime import date
from types import SimpleNamespace

import pytest

from sportsmodel.analysis.moneyline_early_entry_service import (
    capture_moneyline_early_entry,
)


TARGET_DATE = date(2026, 8, 12)


class FakeCursor:
    def __init__(self, preview_run_id=44, odds_run_id=211):
        self.preview_run_id = preview_run_id
        self.odds_run_id = odds_run_id
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, parameters) -> None:
        if "FROM moneyline_prediction_runs" in query:
            self.row = (
                None
                if self.preview_run_id is None
                else (self.preview_run_id,)
            )
        elif "FROM odds_ingestion_runs" in query:
            self.row = (
                None
                if self.odds_run_id is None
                else (self.odds_run_id,)
            )

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, preview_run_id=44, odds_run_id=211):
        self.cursor_instance = FakeCursor(
            preview_run_id,
            odds_run_id,
        )
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_captures_preview_against_late_night_odds() -> None:
    connection = FakeConnection()
    calls = []
    evaluation_result = SimpleNamespace(
        evaluations_saved=15,
        paper_candidates=3,
        evaluations=(),
    )

    result = capture_moneyline_early_entry(
        target_date=TARGET_DATE,
        connection_factory=lambda: connection,
        evaluator=lambda **arguments: (
            calls.append(arguments)
            or evaluation_result
        ),
    )

    assert result.prediction_run_id == 44
    assert result.odds_ingestion_run_id == 211
    assert result.early_entry_candidates == 3
    assert calls == [
        {
            "prediction_run_id": 44,
            "odds_ingestion_run_id": 211,
            "require_complete_market_coverage": False,
        }
    ]
    assert connection.closed is True


@pytest.mark.parametrize(
    ("preview_run_id", "odds_run_id", "message"),
    (
        (None, 211, "preview prediction run"),
        (44, None, "late-night odds snapshot"),
    ),
)
def test_requires_completed_early_entry_inputs(
    preview_run_id,
    odds_run_id,
    message,
) -> None:
    connection = FakeConnection(preview_run_id, odds_run_id)

    with pytest.raises(LookupError, match=message):
        capture_moneyline_early_entry(
            target_date=TARGET_DATE,
            connection_factory=lambda: connection,
        )

    assert connection.closed is True
