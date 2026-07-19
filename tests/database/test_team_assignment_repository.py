from datetime import date, datetime, timezone
from typing import Any

import pytest

from sportsmodel.database.team_assignment_repository import (
    add_baseball_team_source,
    close_current_player_team_assignment,
    create_player_team_assignment,
    get_current_player_team_assignment,
    get_team_id_by_name,
    get_team_id_by_source,
    update_current_player_team_assignment,
)
from sportsmodel.models.baseball_player_team_assignment import (
    BaseballPlayerTeamAssignment,
)
from sportsmodel.models.baseball_team_source import BaseballTeamSource


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


def _assignment_row(
    *,
    assignment_id: int = 301,
    player_id: int = 101,
    team_id: int = 2,
    is_current: bool = True,
    valid_through: date | None = None,
) -> tuple[Any, ...]:
    timestamp = datetime(
        2026,
        7,
        18,
        20,
        0,
        tzinfo=timezone.utc,
    )

    return (
        assignment_id,
        player_id,
        team_id,
        "A",
        "Active",
        "39",
        "2",
        "Catcher",
        date(2026, 7, 18),
        valid_through,
        is_current,
        timestamp,
        timestamp,
        timestamp,
    )


def test_add_baseball_team_source_returns_mapping() -> None:
    timestamp = datetime(
        2026,
        7,
        18,
        20,
        0,
        tzinfo=timezone.utc,
    )

    row = (
        201,
        2,
        "mlb_stats",
        "147",
        timestamp,
    )

    cursor = FakeCursor(row)
    connection = FakeConnection(cursor)

    source = BaseballTeamSource(
        baseball_team_source_id=None,
        team_id=2,
        source_name="mlb_stats",
        external_team_id="147",
    )

    result = add_baseball_team_source(
        source,
        connection_factory=lambda: connection,
    )

    assert result.baseball_team_source_id == 201
    assert result.team_id == 2
    assert result.external_team_id == "147"
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True


def test_get_team_id_by_source_returns_team_id() -> None:
    cursor = FakeCursor((2,))
    connection = FakeConnection(cursor)

    result = get_team_id_by_source(
        "mlb_stats",
        "147",
        connection_factory=lambda: connection,
    )

    assert result == 2
    assert cursor.executed_parameters == ("mlb_stats", "147")
    assert connection.closed is True


def test_get_team_id_by_source_returns_none() -> None:
    cursor = FakeCursor(None)
    connection = FakeConnection(cursor)

    result = get_team_id_by_source(
        "mlb_stats",
        "999",
        connection_factory=lambda: connection,
    )

    assert result is None
    assert connection.closed is True


def test_get_team_id_by_name_returns_team_id() -> None:
    cursor = FakeCursor((2,))
    connection = FakeConnection(cursor)

    result = get_team_id_by_name(
        "New York Yankees",
        connection_factory=lambda: connection,
    )

    assert result == 2
    assert cursor.executed_parameters == ("New York Yankees",)
    assert connection.closed is True


def test_create_player_team_assignment_returns_assignment() -> None:
    row = _assignment_row()
    cursor = FakeCursor(row)
    connection = FakeConnection(cursor)

    assignment = BaseballPlayerTeamAssignment(
        baseball_player_team_assignment_id=None,
        baseball_player_id=101,
        team_id=2,
        roster_status_code="A",
        roster_status_description="Active",
        jersey_number="39",
        position_code="2",
        position_name="Catcher",
        valid_from=date(2026, 7, 18),
    )

    result = create_player_team_assignment(
        assignment,
        connection_factory=lambda: connection,
    )

    assert result.baseball_player_team_assignment_id == 301
    assert result.baseball_player_id == 101
    assert result.team_id == 2
    assert result.is_current is True
    assert connection.committed is True
    assert connection.closed is True


def test_get_current_player_team_assignment_returns_assignment() -> None:
    cursor = FakeCursor(_assignment_row())
    connection = FakeConnection(cursor)

    result = get_current_player_team_assignment(
        101,
        connection_factory=lambda: connection,
    )

    assert result is not None
    assert result.baseball_player_id == 101
    assert result.team_id == 2
    assert cursor.executed_parameters == (101,)
    assert connection.closed is True


def test_update_current_player_team_assignment() -> None:
    cursor = FakeCursor(_assignment_row())
    connection = FakeConnection(cursor)

    timestamp = datetime(
        2026,
        7,
        18,
        21,
        0,
        tzinfo=timezone.utc,
    )

    assignment = BaseballPlayerTeamAssignment(
        baseball_player_team_assignment_id=301,
        baseball_player_id=101,
        team_id=2,
        roster_status_code="A",
        roster_status_description="Active",
        jersey_number="39",
        position_code="2",
        position_name="Catcher",
        last_synced_at=timestamp,
    )

    result = update_current_player_team_assignment(
        assignment,
        connection_factory=lambda: connection,
    )

    assert result.baseball_player_team_assignment_id == 301
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True
    assert cursor.executed_parameters == (
        "A",
        "Active",
        "39",
        "2",
        "Catcher",
        timestamp,
        301,
    )


def test_update_current_player_team_assignment_requires_id() -> None:
    assignment = BaseballPlayerTeamAssignment(
        baseball_player_team_assignment_id=None,
        baseball_player_id=101,
        team_id=2,
    )

    with pytest.raises(
        ValueError,
        match="baseball_player_team_assignment_id is required",
    ):
        update_current_player_team_assignment(assignment)


def test_close_current_player_team_assignment() -> None:
    closed_date = date(2026, 7, 19)

    cursor = FakeCursor(
        _assignment_row(
            is_current=False,
            valid_through=closed_date,
        )
    )
    connection = FakeConnection(cursor)

    result = close_current_player_team_assignment(
        101,
        closed_date,
        connection_factory=lambda: connection,
    )

    assert result is not None
    assert result.is_current is False
    assert result.valid_through == closed_date
    assert cursor.executed_parameters == (
        closed_date,
        101,
    )
    assert connection.committed is True
    assert connection.closed is True


def test_repository_rolls_back_on_failure() -> None:
    class FailingCursor(FakeCursor):
        def execute(
            self,
            query: str,
            parameters: tuple[Any, ...] | None = None,
        ) -> None:
            raise RuntimeError("database failure")

    cursor = FailingCursor()
    connection = FakeConnection(cursor)

    source = BaseballTeamSource(
        baseball_team_source_id=None,
        team_id=2,
        source_name="mlb_stats",
        external_team_id="147",
    )

    with pytest.raises(RuntimeError, match="database failure"):
        add_baseball_team_source(
            source,
            connection_factory=lambda: connection,
        )

    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.closed is True