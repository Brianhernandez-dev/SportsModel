from datetime import date, datetime, timezone
from decimal import Decimal

from sportsmodel.analysis.moneyline_cohort_comparison import (
    AWAITING_OFFICIAL,
    EARLY_ENTRY_ONLY,
    OFFICIAL_ONLY,
    SURVIVED_TO_OFFICIAL,
    load_moneyline_cohort_comparison,
)


TARGET_DATE = date(2026, 8, 12)
START_TIME = datetime(2026, 8, 13, 2, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, *, official_exists, rows) -> None:
        self.official_exists = official_exists
        self.rows = rows
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, parameters) -> None:
        self.queries.append((query, parameters))

    def fetchone(self):
        return (self.official_exists,)

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, *, official_exists, rows) -> None:
        self.cursor_instance = FakeCursor(
            official_exists=official_exists,
            rows=rows,
        )
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def _row(
    *,
    cohort: str,
    evaluation_id: int,
    game_id: int,
    selection: str,
    price: int,
    outcome: str | None = None,
    profit: Decimal | None = None,
):
    return (
        cohort,
        evaluation_id,
        game_id,
        START_TIME,
        "Away",
        "Home",
        selection,
        price,
        "Book",
        outcome,
        profit,
        44 if cohort == "Early Entry" else 45,
        211 if cohort == "Early Entry" else 212,
    )


def test_keeps_cohorts_isolated_and_compares_stored_prices() -> None:
    connection = FakeConnection(
        official_exists=True,
        rows=(
            _row(
                cohort="Early Entry",
                evaluation_id=1,
                game_id=10,
                selection="Home",
                price=120,
                outcome="win",
                profit=Decimal("1.2"),
            ),
            _row(
                cohort="Early Entry",
                evaluation_id=2,
                game_id=11,
                selection="Away",
                price=-105,
            ),
            _row(
                cohort="Official",
                evaluation_id=3,
                game_id=10,
                selection="Home",
                price=105,
                outcome="loss",
                profit=Decimal("-1"),
            ),
            _row(
                cohort="Official",
                evaluation_id=4,
                game_id=12,
                selection="Home",
                price=-110,
            ),
        ),
    )

    result = load_moneyline_cohort_comparison(
        target_date=TARGET_DATE,
        connection_factory=lambda: connection,
    )

    assert result.early_entry.qualified_bets == 2
    assert result.early_entry.settled == 1
    assert result.early_entry.wins == 1
    assert result.early_entry.pending == 1
    assert result.early_entry.profit_units == Decimal("1.2")
    assert result.early_entry.roi == Decimal("1.2")
    assert result.official.qualified_bets == 2
    assert result.official.losses == 1
    assert result.official.pending == 1
    assert result.official.profit_units == Decimal("-1")

    rows = {row.game_id: row for row in result.rows}
    assert rows[10].status == SURVIVED_TO_OFFICIAL
    assert rows[10].early_entry_price == 120
    assert rows[10].official_price == 105
    assert rows[10].price_movement == -15
    assert rows[11].status == EARLY_ENTRY_ONLY
    assert rows[12].status == OFFICIAL_ONLY

    cohort_query, parameters = connection.cursor_instance.queries[1]
    assert parameters == (
        TARGET_DATE,
        TARGET_DATE,
        "baseball_mlb",
        TARGET_DATE,
    )
    assert "prediction_run.run_type = 'preview'" in cohort_query
    assert "odds_run.snapshot_role = 'late_night'" in cohort_query
    assert "odds_run.sport = %s" in cohort_query
    assert "workflow.moneyline_prediction_run_id" in cohort_query
    assert "prediction_run.run_type = 'official'" in cohort_query
    assert "ORDER BY" in cohort_query
    assert connection.closed is True


def test_pre_official_state_never_claims_selection_survived() -> None:
    connection = FakeConnection(
        official_exists=False,
        rows=(
            _row(
                cohort="Early Entry",
                evaluation_id=1,
                game_id=10,
                selection="Home",
                price=120,
            ),
        ),
    )

    result = load_moneyline_cohort_comparison(
        target_date=TARGET_DATE,
        connection_factory=lambda: connection,
    )

    assert result.official.qualified_bets == 0
    assert result.rows[0].status == AWAITING_OFFICIAL
    assert result.rows[0].official_price is None
    assert "survived" not in result.rows[0].status.lower()


def test_empty_cohorts_are_pending_safe_zeroes() -> None:
    connection = FakeConnection(official_exists=False, rows=())

    result = load_moneyline_cohort_comparison(
        target_date=TARGET_DATE,
        connection_factory=lambda: connection,
    )

    assert result.early_entry.qualified_bets == 0
    assert result.early_entry.pending == 0
    assert result.early_entry.roi == Decimal("0")
    assert result.official.qualified_bets == 0
    assert result.rows == ()
