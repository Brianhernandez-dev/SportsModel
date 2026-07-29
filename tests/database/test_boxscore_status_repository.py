import pytest

from sportsmodel.database.boxscore_status_repository import (
    BOX_SCORE_COMPLETENESS_QUERY,
    get_box_score_completeness,
    is_box_score_complete,
)


class FakeCursor:
    def __init__(
        self,
        row: tuple[bool, int, int] | None,
    ) -> None:
        self.row = row
        self.executed_query: str | None = None
        self.executed_parameters: tuple[int, ...] | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(
        self,
        exception_type,
        exception,
        traceback,
    ) -> None:
        return None

    def execute(
        self,
        query: str,
        parameters: tuple[int, ...],
    ) -> None:
        self.executed_query = query
        self.executed_parameters = parameters

    def fetchone(
        self,
    ) -> tuple[bool, int, int] | None:
        return self.row


class FakeConnection:
    def __init__(
        self,
        row: tuple[bool, int, int] | None,
    ) -> None:
        self.cursor_instance = FakeCursor(row)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_complete_box_score_requires_two_teams_and_starters() -> None:
    connection = FakeConnection(
        (
            True,
            2,
            2,
        )
    )

    completeness = get_box_score_completeness(
        42,
        connection_factory=lambda: connection,
    )

    assert completeness.game_id == 42
    assert completeness.game_exists is True
    assert completeness.team_statistics_count == 2
    assert completeness.starting_pitcher_count == 2
    assert completeness.is_complete is True

    assert (
        connection.cursor_instance.executed_query
        == BOX_SCORE_COMPLETENESS_QUERY
    )

    assert (
        connection.cursor_instance.executed_parameters
        == (
            42,
            42,
            42,
        )
    )

    assert connection.closed is True


@pytest.mark.parametrize(
    (
        "row",
        "expected_complete",
    ),
    [
        (
            (
                False,
                0,
                0,
            ),
            False,
        ),
        (
            (
                True,
                1,
                2,
            ),
            False,
        ),
        (
            (
                True,
                2,
                1,
            ),
            False,
        ),
        (
            (
                True,
                2,
                2,
            ),
            True,
        ),
    ],
)
def test_is_box_score_complete(
    row: tuple[bool, int, int],
    expected_complete: bool,
) -> None:
    connection = FakeConnection(row)

    assert (
        is_box_score_complete(
            7,
            connection_factory=lambda: connection,
        )
        is expected_complete
    )


def test_completeness_rejects_invalid_game_id() -> None:
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        get_box_score_completeness(
            0,
            connection_factory=lambda: FakeConnection(
                (
                    True,
                    2,
                    2,
                )
            ),
        )


def test_completeness_raises_when_query_returns_no_row() -> None:
    connection = FakeConnection(None)

    with pytest.raises(
        RuntimeError,
        match="returned no result",
    ):
        get_box_score_completeness(
            99,
            connection_factory=lambda: connection,
        )

    assert connection.closed is True


class BatchFakeCursor:
    def __init__(
        self,
        rows: list[tuple[int]],
    ) -> None:
        self.rows = rows
        self.executed_query: str | None = None
        self.executed_parameters = None

    def __enter__(self) -> "BatchFakeCursor":
        return self

    def __exit__(
        self,
        exception_type,
        exception,
        traceback,
    ) -> None:
        return None

    def execute(
        self,
        query: str,
        parameters,
    ) -> None:
        self.executed_query = query
        self.executed_parameters = parameters

    def fetchall(self) -> list[tuple[int]]:
        return self.rows


class BatchFakeConnection:
    def __init__(
        self,
        rows: list[tuple[int]],
    ) -> None:
        self.cursor_instance = BatchFakeCursor(rows)
        self.closed = False

    def cursor(self) -> BatchFakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_batch_completeness_returns_complete_game_ids() -> None:
    from sportsmodel.database.boxscore_status_repository import (
        COMPLETE_BOX_SCORE_GAME_IDS_QUERY,
        get_complete_box_score_game_ids,
    )

    connection = BatchFakeConnection(
        [
            (7,),
            (9,),
        ]
    )

    result = get_complete_box_score_game_ids(
        [
            7,
            8,
            9,
            9,
        ],
        connection_factory=lambda: connection,
    )

    assert result == frozenset(
        {
            7,
            9,
        }
    )

    assert (
        connection.cursor_instance.executed_query
        == COMPLETE_BOX_SCORE_GAME_IDS_QUERY
    )

    assert (
        connection.cursor_instance.executed_parameters
        == (
            [
                7,
                8,
                9,
            ],
        )
    )

    assert connection.closed is True


def test_batch_completeness_returns_empty_without_database() -> None:
    from sportsmodel.database.boxscore_status_repository import (
        get_complete_box_score_game_ids,
    )

    connection_requested = False

    def connection_factory():
        nonlocal connection_requested
        connection_requested = True
        raise AssertionError(
            "Database should not be accessed."
        )

    assert (
        get_complete_box_score_game_ids(
            [],
            connection_factory=connection_factory,
        )
        == frozenset()
    )

    assert connection_requested is False


def test_batch_completeness_rejects_invalid_game_ids() -> None:
    from sportsmodel.database.boxscore_status_repository import (
        get_complete_box_score_game_ids,
    )

    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        get_complete_box_score_game_ids(
            [
                1,
                0,
                2,
            ]
        )
