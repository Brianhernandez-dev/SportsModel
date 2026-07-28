from datetime import datetime, timezone
from typing import Any

import pytest

from sportsmodel.database.bullpen_statistics_repository import (
    PostgresBullpenStatisticsRepository,
)


class FakeCursor:
    def __init__(
        self,
        rows: list[tuple[Any, ...]],
    ) -> None:
        self.rows = rows
        self.executed_query: str | None = None
        self.executed_parameters: tuple[Any, ...] | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(
        self,
        exception_type: object,
        exception_value: object,
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

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class FakeConnection:
    def __init__(
        self,
        rows: list[tuple[Any, ...]],
    ) -> None:
        self.cursor_instance = FakeCursor(rows)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def build_row() -> tuple[Any, ...]:
    return (
        100,
        datetime(
            2026,
            7,
            20,
            20,
            10,
            tzinfo=timezone.utc,
        ),
        10,
        20,
        True,
        30,
        2,
        False,
        3,
        5,
        1,
        0,
        0,
        0,
        1,
        0,
        2,
        0,
        17,
        12,
        None,
        False,
        True,
        False,
        "mlb_stats_api",
    )


def test_repository_returns_mapped_relief_appearances() -> None:
    cutoff_time = datetime(
        2026,
        7,
        26,
        tzinfo=timezone.utc,
    )

    connection = FakeConnection(
        rows=[
            build_row(),
        ],
    )

    repository = PostgresBullpenStatisticsRepository(
        connection_factory=lambda: connection,
    )

    appearances = (
        repository.get_completed_relief_appearances_before(
            team_id=10,
            cutoff_time=cutoff_time,
        )
    )

    assert len(appearances) == 1

    appearance = appearances[0]

    assert appearance.game_id == 100
    assert appearance.team_id == 10
    assert appearance.opponent_team_id == 20
    assert appearance.statistics.is_starter is False
    assert appearance.statistics.baseball_player_id == 30
    assert appearance.statistics.pitching_outs == 3
    assert appearance.statistics.hold_recorded is True

    cursor = connection.cursor_instance

    assert cursor.executed_parameters == (
        10,
        cutoff_time,
        cutoff_time,
    )

    assert cursor.executed_query is not None

    normalized_query = " ".join(
        cursor.executed_query.split()
    )

    assert "pgps.team_id = %s" in normalized_query
    assert "pgps.is_starter = FALSE" in normalized_query
    assert "g.game_date < %s" in normalized_query
    assert "EXTRACT(YEAR FROM g.game_date)" in normalized_query
    assert connection.closed is True


@pytest.mark.parametrize(
    "team_id",
    [
        0,
        -1,
    ],
)
def test_repository_rejects_invalid_team_id(
    team_id: int,
) -> None:
    repository = PostgresBullpenStatisticsRepository(
        connection_factory=lambda: pytest.fail(
            "Connection should not be opened."
        ),
    )

    with pytest.raises(
        ValueError,
        match="Team ID must be greater than zero",
    ):
        repository.get_completed_relief_appearances_before(
            team_id=team_id,
            cutoff_time=datetime(
                2026,
                7,
                26,
                tzinfo=timezone.utc,
            ),
        )


def test_repository_rejects_naive_cutoff_time() -> None:
    repository = PostgresBullpenStatisticsRepository(
        connection_factory=lambda: pytest.fail(
            "Connection should not be opened."
        ),
    )

    with pytest.raises(
        ValueError,
        match="Cutoff time must be timezone-aware",
    ):
        repository.get_completed_relief_appearances_before(
            team_id=10,
            cutoff_time=datetime(
                2026,
                7,
                26,
            ),
        )
