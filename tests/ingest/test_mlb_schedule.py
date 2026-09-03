from datetime import date
from typing import Any

import pytest

from sportsmodel.ingest.mlb_schedule import (
    sync_mlb_schedule,
)


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False


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


def test_syncs_regular_season_schedule_games() -> None:
    connection = FakeConnection()
    resolver_calls: list[dict[str, Any]] = []
    updater_calls: list[dict[str, Any]] = []

    game_ids = iter(
        [
            1001,
            1002,
        ]
    )

    summary = sync_mlb_schedule(
        start_date=date(2026, 7, 29),
        days_ahead=0,
        progress_callback=None,
        schedule_fetcher=lambda _: {
            "dates": [
                {
                    "games": [
                        _game(
                            game_pk=700001,
                            game_type="R",
                            state="Scheduled",
                            home_team="Home One",
                            away_team="Away One",
                        ),
                        _game(
                            game_pk=700002,
                            game_type="R",
                            state="Final",
                            home_team="Home Two",
                            away_team="Away Two",
                        ),
                        _game(
                            game_pk=700003,
                            game_type="S",
                            state="Scheduled",
                            home_team="Spring Home",
                            away_team="Spring Away",
                        ),
                    ]
                }
            ]
        },
        connection_factory=lambda: connection,
        team_id_resolver=lambda cursor, name: {
            "Home One": 11,
            "Away One": 12,
            "Home Two": 21,
            "Away Two": 22,
        }[name],
        canonical_game_resolver=(
            lambda cursor, **kwargs: (
                resolver_calls.append(kwargs)
                or next(game_ids)
            )
        ),
        canonical_game_updater=(
            lambda cursor, **kwargs: (
                updater_calls.append(kwargs)
            )
        ),
    )

    assert summary.dates_attempted == 1
    assert summary.dates_failed == 0
    assert summary.games_received == 3
    assert summary.games_synchronized == 2
    assert summary.games_skipped == 1

    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True

    assert [
        call["external_game_id"]
        for call in resolver_calls
    ] == [
        "700001",
        "700002",
    ]

    assert [
        call["game_id"]
        for call in updater_calls
    ] == [
        1001,
        1002,
    ]


def test_schedule_failure_does_not_stop_later_dates() -> None:
    requested_dates: list[date] = []
    connections: list[FakeConnection] = []
    progress: list[str] = []

    def fetcher(
        schedule_date: date,
    ) -> dict[str, Any]:
        requested_dates.append(schedule_date)

        if schedule_date == date(
            2026,
            7,
            29,
        ):
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

    summary = sync_mlb_schedule(
        start_date=date(2026, 7, 29),
        days_ahead=1,
        progress_callback=progress.append,
        schedule_fetcher=fetcher,
        connection_factory=connection_factory,
    )

    assert requested_dates == [
        date(2026, 7, 29),
        date(2026, 7, 30),
    ]
    assert summary.dates_attempted == 2
    assert summary.dates_failed == 1
    assert len(connections) == 1
    assert connections[0].committed is True
    assert connections[0].closed is True
    assert progress[0] == (
        "2026-07-29: failed - RuntimeError: "
        "temporary schedule failure"
    )
    assert (
        "MLB schedule synchronization partially completed."
        in progress
    )
    assert "MLB schedule synchronization complete." not in progress


def test_sync_rejects_negative_days_ahead() -> None:
    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        sync_mlb_schedule(
            start_date=date(2026, 7, 29),
            days_ahead=-1,
            progress_callback=None,
        )


def _game(
    *,
    game_pk: int,
    game_type: str,
    state: str,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    return {
        "gamePk": game_pk,
        "gameType": game_type,
        "gameDate": "2026-07-29T19:05:00Z",
        "status": {
            "detailedState": state,
        },
        "teams": {
            "home": {
                "team": {
                    "name": home_team,
                },
            },
            "away": {
                "team": {
                    "name": away_team,
                },
            },
        },
    }
