from datetime import datetime, timezone
from typing import Any

from sportsmodel.database.completed_game_repository import (
    GET_COMPLETED_GAMES_QUERY,
    PostgresCompletedGameRepository,
)


class FakeCursor:
    def __init__(
        self,
        *,
        rows: list[tuple[Any, ...]],
    ) -> None:
        self._rows = rows
        self.executed_query: str | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        return None

    def execute(
        self,
        query: str,
    ) -> None:
        self.executed_query = query

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class FakeConnection:
    def __init__(
        self,
        *,
        rows: list[tuple[Any, ...]],
    ) -> None:
        self.cursor_instance = FakeCursor(rows=rows)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_get_all_returns_completed_games() -> None:
    first_start_time = datetime(
        2026,
        7,
        20,
        19,
        10,
        tzinfo=timezone.utc,
    )
    second_start_time = datetime(
        2026,
        7,
        21,
        20,
        5,
        tzinfo=timezone.utc,
    )

    connection = FakeConnection(
        rows=[
            (
                101,
                first_start_time,
                10,
                20,
                5,
                3,
            ),
            (
                102,
                second_start_time,
                30,
                40,
                2,
                6,
            ),
        ]
    )

    repository = PostgresCompletedGameRepository(
        connection_factory=lambda: connection,
    )

    games = repository.get_all()

    assert len(games) == 2

    assert games[0].game.game_id == 101
    assert games[0].game.game_start_time == first_start_time
    assert games[0].game.home_team_id == 10
    assert games[0].game.away_team_id == 20
    assert games[0].home_score == 5
    assert games[0].away_score == 3
    assert games[0].home_team_won is True

    assert games[1].game.game_id == 102
    assert games[1].home_team_won is False

    assert (
        connection.cursor_instance.executed_query
        == GET_COMPLETED_GAMES_QUERY
    )
    assert connection.closed is True


def test_get_all_returns_empty_list_without_results() -> None:
    connection = FakeConnection(rows=[])

    repository = PostgresCompletedGameRepository(
        connection_factory=lambda: connection,
    )

    games = repository.get_all()

    assert games == []
    assert connection.closed is True
