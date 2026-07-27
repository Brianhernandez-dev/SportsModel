from datetime import date

import pytest

from sportsmodel.ingest.mlb_stats import (
    fetch_historical_results,
)


class FakeCursor:
    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(
        self,
        exception_type,
        exception,
        traceback,
    ) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_backfill_processes_and_skips_complete_boxscores() -> None:
    connection = FakeConnection()
    ingested_boxscores: list[tuple[int, int]] = []
    saved_results: list[int] = []

    game_ids = iter(
        [
            101,
            102,
        ]
    )

    summary = fetch_historical_results(
        start_date=date(2025, 4, 1),
        end_date=date(2025, 4, 1),
        progress_callback=None,
        schedule_fetcher=lambda _: {
            "dates": [
                {
                    "games": [
                        _game(
                            game_pk=1,
                            final=True,
                        ),
                        _game(
                            game_pk=2,
                            final=True,
                        ),
                        _game(
                            game_pk=3,
                            final=False,
                        ),
                    ]
                }
            ]
        },
        connection_factory=lambda: connection,
        team_id_resolver=lambda cursor, name: (
            10 if name == "Home" else 20
        ),
        canonical_game_resolver=(
            lambda cursor, **kwargs: next(game_ids)
        ),
        historical_result_saver=(
            lambda **kwargs: saved_results.append(
                kwargs["mlb_game_id"]
            )
        ),
        complete_game_ids_getter=lambda ids: (
            frozenset(
                {
                    101,
                }
            )
        ),
        boxscore_ingestor=(
            lambda *, game_id, game_pk: (
                ingested_boxscores.append(
                    (
                        game_id,
                        game_pk,
                    )
                )
            )
        ),
    )

    assert summary.dates_attempted == 1
    assert summary.dates_failed == 0
    assert summary.games_received == 3
    assert summary.games_processed == 2
    assert summary.games_skipped == 1
    assert summary.boxscores_processed == 1
    assert summary.boxscores_skipped_complete == 1
    assert summary.boxscores_failed == 0

    assert saved_results == [
        1,
        2,
    ]

    assert ingested_boxscores == [
        (
            102,
            2,
        )
    ]

    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True


def test_schedule_failure_does_not_stop_later_dates() -> None:
    requested_dates: list[date] = []
    connections: list[FakeConnection] = []

    def schedule_fetcher(
        schedule_date: date,
    ):
        requested_dates.append(schedule_date)

        if schedule_date == date(2025, 4, 1):
            raise RuntimeError(
                "temporary schedule failure"
            )

        return {
            "dates": [],
        }

    def connection_factory() -> FakeConnection:
        connection = FakeConnection()
        connections.append(connection)
        return connection

    summary = fetch_historical_results(
        start_date=date(2025, 4, 1),
        end_date=date(2025, 4, 2),
        progress_callback=None,
        schedule_fetcher=schedule_fetcher,
        connection_factory=connection_factory,
    )

    assert requested_dates == [
        date(2025, 4, 1),
        date(2025, 4, 2),
    ]

    assert summary.dates_attempted == 2
    assert summary.dates_failed == 1
    assert len(connections) == 1
    assert connections[0].committed is True
    assert connections[0].closed is True


def test_database_failure_rolls_back_one_date() -> None:
    connection = FakeConnection()
    boxscore_called = False

    def failing_team_resolver(
        cursor,
        team_name,
    ):
        raise RuntimeError(
            "database write failed"
        )

    def boxscore_ingestor(**kwargs):
        nonlocal boxscore_called
        boxscore_called = True

    summary = fetch_historical_results(
        start_date=date(2025, 4, 1),
        end_date=date(2025, 4, 1),
        progress_callback=None,
        schedule_fetcher=lambda _: {
            "dates": [
                {
                    "games": [
                        _game(
                            game_pk=1,
                            final=True,
                        ),
                    ]
                }
            ]
        },
        connection_factory=lambda: connection,
        team_id_resolver=failing_team_resolver,
        boxscore_ingestor=boxscore_ingestor,
    )

    assert summary.dates_failed == 1
    assert summary.games_processed == 0
    assert summary.boxscores_processed == 0
    assert boxscore_called is False

    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.closed is True


def test_backfill_rejects_reversed_date_range() -> None:
    with pytest.raises(
        ValueError,
        match="cannot be after",
    ):
        fetch_historical_results(
            start_date=date(2025, 4, 2),
            end_date=date(2025, 4, 1),
            progress_callback=None,
        )


def _game(
    *,
    game_pk: int,
    final: bool,
) -> dict:
    return {
        "gamePk": game_pk,
        "gameDate": "2025-04-01T19:05:00Z",
        "status": {
            "detailedState": (
                "Final"
                if final
                else "Scheduled"
            ),
            "abstractGameState": (
                "Final"
                if final
                else "Preview"
            ),
        },
        "teams": {
            "home": {
                "team": {
                    "name": "Home",
                },
                "score": 5,
            },
            "away": {
                "team": {
                    "name": "Away",
                },
                "score": 3,
            },
        },
    }
