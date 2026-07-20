from datetime import datetime, timezone
from typing import Any

import pytest

from sportsmodel.database.game_repository import (
    GET_GAME_BY_ID_QUERY,
    GET_NEXT_UPCOMING_GAME_QUERY,
    PostgresGameRepository,
)


class FakeCursor:
    def __init__(
        self,
        *,
        row: tuple[Any, ...] | None,
    ) -> None:
        self._row = row
        self.executed_query: str | None = None
        self.executed_parameters: tuple[Any, ...] | None = None

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
        parameters: tuple[Any, ...],
    ) -> None:
        self.executed_query = query
        self.executed_parameters = parameters

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class FakeConnection:
    def __init__(
        self,
        *,
        row: tuple[Any, ...] | None,
    ) -> None:
        self.cursor_instance = FakeCursor(row=row)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_get_by_id_returns_game() -> None:
    game_start_time = datetime(
        2026,
        7,
        20,
        19,
        10,
        tzinfo=timezone.utc,
    )

    connection = FakeConnection(
        row=(
            101,
            game_start_time,
            10,
            20,
        )
    )

    repository = PostgresGameRepository(
        connection_factory=lambda: connection,
    )

    game = repository.get_by_id(game_id=101)

    assert game is not None
    assert game.game_id == 101
    assert game.game_start_time == game_start_time
    assert game.home_team_id == 10
    assert game.away_team_id == 20

    assert (
        connection.cursor_instance.executed_query
        == GET_GAME_BY_ID_QUERY
    )
    assert (
        connection.cursor_instance.executed_parameters
        == (101,)
    )
    assert connection.closed is True


def test_get_by_id_returns_none_when_game_is_missing() -> None:
    connection = FakeConnection(row=None)

    repository = PostgresGameRepository(
        connection_factory=lambda: connection,
    )

    game = repository.get_by_id(game_id=999)

    assert game is None
    assert connection.closed is True


def test_get_by_id_rejects_invalid_identifier() -> None:
    repository = PostgresGameRepository(
        connection_factory=lambda: FakeConnection(
            row=None,
        )
    )

    with pytest.raises(
        ValueError,
        match="Game ID must be greater than zero",
    ):
        repository.get_by_id(game_id=0)


def test_get_next_upcoming_game_returns_game() -> None:
    cutoff_time = datetime(
        2026,
        7,
        19,
        12,
        0,
        tzinfo=timezone.utc,
    )

    game_start_time = datetime(
        2026,
        7,
        20,
        19,
        10,
        tzinfo=timezone.utc,
    )

    connection = FakeConnection(
        row=(
            101,
            game_start_time,
            10,
            20,
        )
    )

    repository = PostgresGameRepository(
        connection_factory=lambda: connection,
    )

    game = repository.get_next_upcoming_game(
        cutoff_time=cutoff_time,
    )

    assert game is not None
    assert game.game_id == 101
    assert game.game_start_time == game_start_time

    assert (
        connection.cursor_instance.executed_query
        == GET_NEXT_UPCOMING_GAME_QUERY
    )
    assert (
        connection.cursor_instance.executed_parameters
        == (cutoff_time,)
    )
    assert connection.closed is True


def test_get_next_upcoming_game_returns_none_when_missing() -> None:
    cutoff_time = datetime(
        2026,
        7,
        19,
        12,
        0,
        tzinfo=timezone.utc,
    )

    connection = FakeConnection(row=None)

    repository = PostgresGameRepository(
        connection_factory=lambda: connection,
    )

    game = repository.get_next_upcoming_game(
        cutoff_time=cutoff_time,
    )

    assert game is None
    assert connection.closed is True


def test_get_next_upcoming_game_rejects_naive_cutoff() -> None:
    repository = PostgresGameRepository(
        connection_factory=lambda: FakeConnection(
            row=None,
        )
    )

    with pytest.raises(
        ValueError,
        match="Cutoff time must be timezone-aware",
    ):
        repository.get_next_upcoming_game(
            cutoff_time=datetime(
                2026,
                7,
                19,
                12,
                0,
            ),
        )
