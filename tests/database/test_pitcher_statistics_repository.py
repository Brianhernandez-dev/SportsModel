from datetime import datetime, timezone
from typing import Any

import pytest

from sportsmodel.database.pitcher_statistics_repository import (
    PostgresPitcherStatisticsRepository,
)
from sportsmodel.models.player_game_pitching_statistics import (
    PitchingDecision,
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


def build_row(
    *,
    game_id: int = 100,
    game_start_time: datetime | None = None,
    team_id: int = 10,
    opponent_team_id: int = 20,
    player_id: int = 30,
    decision: str | None = "W",
) -> tuple[Any, ...]:
    return (
        game_id,
        game_start_time
        or datetime(
            2026,
            7,
            20,
            20,
            10,
            tzinfo=timezone.utc,
        ),
        team_id,
        opponent_team_id,
        True,
        player_id,
        1,
        True,
        18,
        24,
        5,
        2,
        2,
        1,
        1,
        0,
        6,
        0,
        91,
        61,
        decision,
        False,
        False,
        False,
        "mlb_stats_api",
    )


def test_repository_returns_mapped_historical_starts() -> None:
    cutoff_time = datetime(
        2026,
        7,
        26,
        19,
        10,
        tzinfo=timezone.utc,
    )

    connection = FakeConnection(
        rows=[
            build_row(),
        ],
    )

    repository = PostgresPitcherStatisticsRepository(
        connection_factory=lambda: connection,
    )

    starts = repository.get_completed_starts_before(
        player_id=30,
        cutoff_time=cutoff_time,
        limit=50,
    )

    assert len(starts) == 1

    start = starts[0]

    assert start.game_id == 100
    assert start.team_id == 10
    assert start.opponent_team_id == 20
    assert start.is_home is True

    assert start.statistics.baseball_player_id == 30
    assert start.statistics.is_starter is True
    assert start.statistics.pitching_outs == 18
    assert start.statistics.hits_allowed == 5
    assert start.statistics.earned_runs_allowed == 2
    assert start.statistics.home_runs_allowed == 1
    assert start.statistics.walks_allowed == 1
    assert start.statistics.strikeouts == 6
    assert start.statistics.decision == PitchingDecision.WIN

    cursor = connection.cursor_instance

    assert cursor.executed_parameters == (
        30,
        cutoff_time,
        50,
    )

    assert cursor.executed_query is not None

    normalized_query = " ".join(
        cursor.executed_query.split()
    )

    assert "pgps.baseball_player_id = %s" in normalized_query
    assert "pgps.is_starter = TRUE" in normalized_query
    assert "g.game_date < %s" in normalized_query
    assert "g.game_date DESC" in normalized_query
    assert connection.closed is True


def test_repository_returns_empty_tuple_without_rows() -> None:
    cutoff_time = datetime(
        2026,
        7,
        26,
        tzinfo=timezone.utc,
    )

    connection = FakeConnection(rows=[])

    repository = PostgresPitcherStatisticsRepository(
        connection_factory=lambda: connection,
    )

    starts = repository.get_completed_starts_before(
        player_id=30,
        cutoff_time=cutoff_time,
        limit=10,
    )

    assert starts == ()
    assert connection.closed is True


@pytest.mark.parametrize(
    "player_id",
    [
        0,
        -1,
    ],
)
def test_repository_rejects_invalid_player_id(
    player_id: int,
) -> None:
    repository = PostgresPitcherStatisticsRepository(
        connection_factory=lambda: pytest.fail(
            "Connection should not be opened."
        ),
    )

    with pytest.raises(
        ValueError,
        match="Baseball player ID must be greater than zero",
    ):
        repository.get_completed_starts_before(
            player_id=player_id,
            cutoff_time=datetime(
                2026,
                7,
                26,
                tzinfo=timezone.utc,
            ),
            limit=10,
        )


def test_repository_rejects_naive_cutoff_time() -> None:
    repository = PostgresPitcherStatisticsRepository(
        connection_factory=lambda: pytest.fail(
            "Connection should not be opened."
        ),
    )

    with pytest.raises(
        ValueError,
        match="Cutoff time must be timezone-aware",
    ):
        repository.get_completed_starts_before(
            player_id=30,
            cutoff_time=datetime(
                2026,
                7,
                26,
            ),
            limit=10,
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
    repository = PostgresPitcherStatisticsRepository(
        connection_factory=lambda: pytest.fail(
            "Connection should not be opened."
        ),
    )

    with pytest.raises(
        ValueError,
        match="Limit must be greater than zero",
    ):
        repository.get_completed_starts_before(
            player_id=30,
            cutoff_time=datetime(
                2026,
                7,
                26,
                tzinfo=timezone.utc,
            ),
            limit=limit,
        )
