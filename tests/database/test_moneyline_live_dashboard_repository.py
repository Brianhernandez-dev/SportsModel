from datetime import date, datetime, timezone
from decimal import Decimal

from sportsmodel.database.moneyline_live_dashboard_repository import (
    build_moneyline_live_performance,
    get_moneyline_live_games,
    list_moneyline_live_slates,
)


GAME_TIME = datetime(
    2026,
    7,
    30,
    19,
    10,
    tzinfo=timezone.utc,
)


class FakeCursor:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.query = None
        self.parameters = None

    def __enter__(self):
        return self

    def __exit__(
        self,
        exception_type,
        exception,
        traceback,
    ):
        return False

    def execute(
        self,
        query,
        parameters=None,
    ) -> None:
        self.query = query
        self.parameters = parameters

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows) -> None:
        self.cursor_instance = FakeCursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_lists_moneyline_live_slates() -> None:
    connection = FakeConnection(
        [
            (
                1,
                181,
                "1.0.0",
                date(2026, 7, 30),
                "entry",
                GAME_TIME,
                "official",
            )
        ]
    )

    slates = list_moneyline_live_slates(
        connection_factory=lambda: connection,
    )

    assert len(slates) == 1
    assert slates[0].prediction_run_id == 1
    assert slates[0].odds_ingestion_run_id == 181
    assert slates[0].policy_version == "1.0.0"
    assert slates[0].target_date == date(
        2026,
        7,
        30,
    )
    assert slates[0].snapshot_role == "entry"
    assert slates[0].snapshot_started_at == GAME_TIME
    assert slates[0].run_type == "official"
    assert "ingestion.snapshot_role" in (
        connection.cursor_instance.query
    )
    assert connection.closed is True


def test_loads_moneyline_live_games() -> None:
    connection = FakeConnection(
        [
            _row(
                outcome=None,
                profit_units=None,
                home_score=None,
                away_score=None,
            )
        ]
    )

    games = get_moneyline_live_games(
        prediction_run_id=1,
        odds_ingestion_run_id=181,
        policy_version="1.0.0",
        connection_factory=lambda: connection,
    )

    assert len(games) == 1

    game = games[0]

    assert game.moneyline_game_prediction_id == 501
    assert game.away_team_name == (
        "Kansas City Royals"
    )
    assert game.home_team_name == (
        "Minnesota Twins"
    )
    assert game.predicted_team_name == (
        "Kansas City Royals"
    )
    assert game.price == 119
    assert game.sportsbook_name == "DraftKings"
    assert game.qualifies_as_paper_candidate is True
    assert game.outcome is None
    assert "prediction.moneyline_game_prediction_id" in (
        connection.cursor_instance.query
    )

    assert (
        connection.cursor_instance.parameters
        == (
            1,
            181,
            "1.0.0",
        )
    )

    assert connection.closed is True


def test_builds_settled_performance() -> None:
    connection = FakeConnection(
        [
            _row(
                game_id=1,
                outcome="win",
                profit_units=Decimal("1.19"),
                home_score=3,
                away_score=5,
                model_expected_value=Decimal("0.10"),
            ),
            _row(
                game_id=2,
                outcome="loss",
                profit_units=Decimal("-1"),
                home_score=5,
                away_score=2,
                model_expected_value=Decimal("0.04"),
            ),
        ]
    )

    games = get_moneyline_live_games(
        prediction_run_id=1,
        odds_ingestion_run_id=181,
        policy_version="1.0.0",
        connection_factory=lambda: connection,
    )

    performance = (
        build_moneyline_live_performance(
            games
        )
    )

    assert performance.settlements == 2
    assert performance.wins == 1
    assert performance.losses == 1
    assert performance.pushes == 0
    assert performance.win_rate == Decimal("0.5")
    assert performance.units_staked == Decimal("2")
    assert performance.profit_units == Decimal("0.19")
    assert performance.roi == Decimal("0.095")

    assert (
        performance.average_model_expected_value
        == Decimal("0.07")
    )

    assert (
        performance.maximum_drawdown_units
        == Decimal("1")
    )


def test_unsettled_games_produce_zero_performance() -> None:
    connection = FakeConnection(
        [
            _row(
                outcome=None,
                profit_units=None,
                home_score=None,
                away_score=None,
            )
        ]
    )

    games = get_moneyline_live_games(
        prediction_run_id=1,
        odds_ingestion_run_id=181,
        policy_version="1.0.0",
        connection_factory=lambda: connection,
    )

    performance = (
        build_moneyline_live_performance(
            games
        )
    )

    assert performance.settlements == 0
    assert performance.profit_units == Decimal("0")
    assert performance.roi == Decimal("0")


def _row(
    *,
    game_id: int = 1,
    outcome,
    profit_units,
    home_score,
    away_score,
    model_expected_value: Decimal = Decimal(
        "0.1193"
    ),
):
    return (
        501,
        game_id,
        GAME_TIME,
        "Kansas City Royals",
        "Minnesota Twins",
        "Kansas City Royals",
        Decimal("0.5111"),
        "both",
        2,
        Decimal("0.4440"),
        Decimal("0.0671"),
        119,
        "DraftKings",
        model_expected_value,
        True,
        [],
        outcome,
        profit_units,
        home_score,
        away_score,
    )
