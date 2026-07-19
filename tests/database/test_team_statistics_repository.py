from datetime import datetime, timezone
from typing import Any

import pytest

from sportsmodel.database.team_statistics_repository import (
    PostgresTeamStatisticsRepository,
    TeamStatisticsRepository,
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


def build_row(
    *,
    game_id: int = 100,
    team_id: int = 10,
    opponent_team_id: int = 20,
    is_home: bool = True,
) -> tuple[Any, ...]:
    return (
        game_id,
        datetime(
            2026,
            7,
            18,
            23,
            10,
            tzinfo=timezone.utc,
        ),
        team_id,
        opponent_team_id,
        is_home,
        5,
        9,
        1,
        34,
        38,
        2,
        0,
        1,
        4,
        0,
        8,
        1,
        1,
        2,
        0,
        27,
        3,
        3,
        7,
        1,
        2,
        10,
        6,
        1,
        "mlb_stats_api",
    )


def test_repository_is_abstract() -> None:
    with pytest.raises(TypeError):
        TeamStatisticsRepository()


def test_postgres_repository_maps_historical_game() -> None:
    fake_connection = FakeConnection(
        rows=[
            build_row(),
        ],
    )

    repository = PostgresTeamStatisticsRepository(
        connection_factory=lambda: fake_connection,
    )

    cutoff_time = datetime(
        2026,
        7,
        19,
        1,
        10,
        tzinfo=timezone.utc,
    )

    games = repository.get_completed_games_before(
        team_id=10,
        cutoff_time=cutoff_time,
        limit=5,
    )

    assert len(games) == 1

    game = games[0]

    assert game.game_id == 100
    assert game.team_id == 10
    assert game.opponent_team_id == 20
    assert game.is_home is True
    assert game.statistics.runs == 5
    assert game.statistics.runs_allowed == 3
    assert game.statistics.source_name == "mlb_stats_api"


def test_repository_passes_point_in_time_parameters() -> None:
    fake_connection = FakeConnection(rows=[])

    repository = PostgresTeamStatisticsRepository(
        connection_factory=lambda: fake_connection,
    )

    cutoff_time = datetime(
        2026,
        7,
        19,
        1,
        10,
        tzinfo=timezone.utc,
    )

    games = repository.get_completed_games_before(
        team_id=10,
        cutoff_time=cutoff_time,
        limit=7,
    )

    assert games == ()
    assert (
        fake_connection.cursor_instance.executed_parameters
        == (
            10,
            cutoff_time,
            7,
        )
    )


def test_repository_closes_connection() -> None:
    fake_connection = FakeConnection(rows=[])

    repository = PostgresTeamStatisticsRepository(
        connection_factory=lambda: fake_connection,
    )

    repository.get_completed_games_before(
        team_id=10,
        cutoff_time=datetime.now(timezone.utc),
        limit=5,
    )

    assert fake_connection.closed is True


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
    repository = PostgresTeamStatisticsRepository(
        connection_factory=lambda: FakeConnection([]),
    )

    with pytest.raises(
        ValueError,
        match="Team ID must be greater than zero",
    ):
        repository.get_completed_games_before(
            team_id=team_id,
            cutoff_time=datetime.now(timezone.utc),
            limit=5,
        )


@pytest.mark.parametrize(
    "limit",
    [
        0,
        -1,
    ],
)
def test_repository_rejects_invalid_limit(
    limit: int,
) -> None:
    repository = PostgresTeamStatisticsRepository(
        connection_factory=lambda: FakeConnection([]),
    )

    with pytest.raises(
        ValueError,
        match="Limit must be greater than zero",
    ):
        repository.get_completed_games_before(
            team_id=10,
            cutoff_time=datetime.now(timezone.utc),
            limit=limit,
        )


def test_repository_rejects_naive_cutoff_time() -> None:
    repository = PostgresTeamStatisticsRepository(
        connection_factory=lambda: FakeConnection([]),
    )

    with pytest.raises(
        ValueError,
        match="Cutoff time must be timezone-aware",
    ):
        repository.get_completed_games_before(
            team_id=10,
            cutoff_time=datetime(
                2026,
                7,
                19,
                1,
                10,
            ),
            limit=5,
        )