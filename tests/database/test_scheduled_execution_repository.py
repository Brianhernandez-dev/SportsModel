from datetime import date, datetime, timezone
from typing import Any

from sportsmodel.database.scheduled_execution_repository import (
    GET_EARLIEST_MLB_GAME_START_QUERY,
    MLB_GAME_SOURCE_NAME,
    get_earliest_mlb_game_start_for_pacific_date,
)


class _Cursor:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row
        self.query: str | None = None
        self.parameters: tuple[Any, ...] | None = None

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *arguments: object) -> None:
        del arguments

    def execute(
        self,
        query: str,
        parameters: tuple[Any, ...],
    ) -> None:
        self.query = query
        self.parameters = parameters

    def fetchone(self) -> tuple[Any, ...]:
        return self._row


class _Connection:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self.cursor_instance = _Cursor(row)
        self.closed = False

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_loads_earliest_canonical_mlb_start_for_pacific_slate() -> None:
    earliest_start = datetime(
        2026,
        9,
        1,
        15,
        10,
        tzinfo=timezone.utc,
    )
    connection = _Connection((earliest_start,))

    result = get_earliest_mlb_game_start_for_pacific_date(
        date(2026, 9, 1),
        connection_factory=lambda: connection,
    )

    assert result == earliest_start
    assert connection.cursor_instance.query == (
        GET_EARLIEST_MLB_GAME_START_QUERY
    )
    assert connection.cursor_instance.parameters == (
        MLB_GAME_SOURCE_NAME,
        datetime(2026, 9, 1, 7, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 2, 7, 0, tzinfo=timezone.utc),
    )
    assert connection.closed


def test_returns_none_when_target_slate_has_no_canonical_mlb_games() -> None:
    connection = _Connection((None,))

    result = get_earliest_mlb_game_start_for_pacific_date(
        date(2026, 9, 1),
        connection_factory=lambda: connection,
    )

    assert result is None
    assert connection.closed
