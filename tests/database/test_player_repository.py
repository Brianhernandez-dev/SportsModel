from datetime import date, datetime, timezone
from typing import Any

import pytest

from sportsmodel.database.player_repository import (
    add_baseball_player_source,
    create_baseball_player,
    get_baseball_player_by_id,
    get_baseball_player_by_source,
)
from sportsmodel.models.baseball_player import BaseballPlayer
from sportsmodel.models.baseball_player_source import BaseballPlayerSource


class FakeCursor:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.row = row
        self.executed_query: str | None = None
        self.executed_parameters: tuple[Any, ...] | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def execute(
        self,
        query: str,
        parameters: tuple[Any, ...] | None = None,
    ) -> None:
        self.executed_query = query
        self.executed_parameters = parameters

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.fake_cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_create_baseball_player_returns_inserted_player() -> None:
    created_at = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    row = (
        101,
        "Test Pitcher",
        "L",
        "R",
        "Pitcher",
        date(2020, 7, 24),
        None,
        True,
        created_at,
        created_at,
        created_at,
    )

    cursor = FakeCursor(row)
    connection = FakeConnection(cursor)

    player = BaseballPlayer(
        baseball_player_id=None,
        full_name="Test Pitcher",
        bats="L",
        throws="R",
        primary_position="Pitcher",
        active_from=date(2020, 7, 24),
        last_synced_at=created_at,
    )

    result = create_baseball_player(
        player,
        connection_factory=lambda: connection,
    )

    assert result.baseball_player_id == 101
    assert result.full_name == "Test Pitcher"
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True
    assert cursor.executed_parameters == (
        "Test Pitcher",
        "L",
        "R",
        "Pitcher",
        date(2020, 7, 24),
        None,
        True,
        created_at,
    )


def test_get_baseball_player_by_id_returns_none_when_missing() -> None:
    cursor = FakeCursor(None)
    connection = FakeConnection(cursor)

    result = get_baseball_player_by_id(
        999,
        connection_factory=lambda: connection,
    )

    assert result is None
    assert cursor.executed_parameters == (999,)
    assert connection.closed is True


def test_get_baseball_player_by_source_returns_player() -> None:
    timestamp = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    row = (
        101,
        "Mapped Player",
        "R",
        "R",
        "Pitcher",
        None,
        None,
        True,
        timestamp,
        timestamp,
        timestamp,
    )

    cursor = FakeCursor(row)
    connection = FakeConnection(cursor)

    result = get_baseball_player_by_source(
        "mlb",
        "123456",
        connection_factory=lambda: connection,
    )

    assert result is not None
    assert result.baseball_player_id == 101
    assert result.full_name == "Mapped Player"
    assert cursor.executed_parameters == ("mlb", "123456")
    assert connection.closed is True


def test_add_baseball_player_source_returns_mapping() -> None:
    created_at = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    row = (
        201,
        101,
        "mlb",
        "123456",
        created_at,
    )

    cursor = FakeCursor(row)
    connection = FakeConnection(cursor)

    source = BaseballPlayerSource(
        baseball_player_source_id=None,
        baseball_player_id=101,
        source_name="mlb",
        external_player_id="123456",
    )

    result = add_baseball_player_source(
        source,
        connection_factory=lambda: connection,
    )

    assert result.baseball_player_source_id == 201
    assert result.baseball_player_id == 101
    assert result.external_player_id == "123456"
    assert connection.committed is True
    assert connection.closed is True


def test_create_baseball_player_rolls_back_on_failure() -> None:
    class FailingCursor(FakeCursor):
        def execute(
            self,
            query: str,
            parameters: tuple[Any, ...] | None = None,
        ) -> None:
            raise RuntimeError("database failure")

    cursor = FailingCursor()
    connection = FakeConnection(cursor)

    player = BaseballPlayer(
        baseball_player_id=None,
        full_name="Failure Player",
    )

    with pytest.raises(RuntimeError, match="database failure"):
        create_baseball_player(
            player,
            connection_factory=lambda: connection,
        )

    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.closed is True