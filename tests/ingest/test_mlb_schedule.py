from datetime import date, datetime, timezone
from typing import Any

import pytest

from sportsmodel.database.scheduled_execution_repository import (
    GET_EARLIEST_MLB_GAME_START_QUERY,
    get_earliest_mlb_game_start_for_pacific_date,
)
from sportsmodel.ingest.mlb_schedule import (
    sync_mlb_schedule,
)
from sportsmodel.orchestration.scheduled_execution import (
    MONEYLINE_PREGAME_TASK,
    PACIFIC_TIME_ZONE,
)
from sportsmodel.orchestration.scheduled_execution_cli import main as scheduled_main


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
                    "date": "2026-07-29",
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


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"dates": [{"date": "2026-07-30", "games": []}]},
    ],
    ids=["malformed-envelope", "wrong-returned-date"],
)
def test_schedule_envelope_failure_makes_no_database_writes(payload) -> None:
    connections: list[FakeConnection] = []

    summary = sync_mlb_schedule(
        start_date=date(2026, 7, 29),
        days_ahead=0,
        progress_callback=None,
        schedule_fetcher=lambda _: payload,
        connection_factory=lambda: connections.append(FakeConnection()),
    )

    assert summary.dates_failed == 1
    assert summary.games_synchronized == 0
    assert connections == []
    assert "ValueError" in summary.date_summaries[0].error_message


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


class ScriptedCursor(FakeCursor):
    """Exercise real matching/update SQL with only predetermined local rows."""

    def __init__(self, rows: list[Any]) -> None:
        self.rows = iter(rows)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, query: str, parameters: tuple[Any, ...]) -> None:
        self.calls.append((query, parameters))

    def fetchone(self):
        return next(self.rows)


def _sync_one_game(game: dict[str, Any], cursor: ScriptedCursor):
    connection = FakeConnection()
    connection.cursor_instance = cursor
    summary = sync_mlb_schedule(
        start_date=date(2026, 10, 7),
        days_ahead=0,
        progress_callback=None,
        schedule_fetcher=lambda _: {
            "dates": [{"date": "2026-10-07", "games": [game]}]
        },
        connection_factory=lambda: connection,
        team_id_resolver=lambda _, name: {"Chicago White Sox": 11, "Cleveland Guardians": 12}[name],
        # Keep the real canonical resolver and updater, including source linking.
    )
    return summary, connection


def _championship_game(game_type: Any) -> dict[str, Any]:
    game = _game(
        game_pk=849833,
        game_type=game_type,
        state="Scheduled",
        home_team="Chicago White Sox",
        away_team="Cleveland Guardians",
    )
    game["gameDate"] = "2026-10-07T20:00:00Z"
    game["ifNecessary"] = "N"
    game["teams"]["home"]["team"]["id"] = 145
    game["teams"]["away"]["team"]["id"] = 114
    return game


@pytest.mark.parametrize("game_type", ["R", "F", "D", "L", "W"])
def test_championship_game_uses_canonical_creation_and_source_linking(
    game_type: str,
) -> None:
    cursor = ScriptedCursor([None, (0, None), (0, None), (1001,)])
    summary, connection = _sync_one_game(_championship_game(game_type), cursor)

    assert summary.dates_failed == 0
    assert summary.games_synchronized == 1
    assert summary.games_skipped == 0
    assert connection.committed and connection.closed
    assert not connection.rolled_back
    start = datetime(2026, 10, 7, 20, tzinfo=timezone.utc)
    assert [args for sql, args in cursor.calls if "INSERT INTO games (" in sql] == [
        (start, 11, 12),
    ]
    assert [args for sql, args in cursor.calls if "INSERT INTO game_sources" in sql] == [
        (1001, "mlb_stats", "849833"),
    ]
    assert [args for sql, args in cursor.calls if "UPDATE games" in sql] == [
        (start, 11, 12, 1001),
    ]
    assert next(cursor.rows, "exhausted") == "exhausted"


@pytest.mark.parametrize("game_type", ["R", "F", "D", "L", "W"])
def test_championship_game_links_existing_canonical_game_and_is_idempotent(
    game_type: str,
) -> None:
    # An existing same-orientation Odds game is the sole nearby candidate.
    first = ScriptedCursor([None, (1, 1001)])
    start = datetime(2026, 10, 7, 20, tzinfo=timezone.utc)
    second = ScriptedCursor([(1001, start, 11, 12), (0, None)])

    for cursor in (first, second):
        summary, connection = _sync_one_game(_championship_game(game_type), cursor)
        assert summary.dates_failed == 0
        assert summary.games_synchronized == 1
        assert connection.committed and connection.closed
        assert not connection.rolled_back
        assert not any("INSERT INTO games (" in sql for sql, _ in cursor.calls)
        assert [args for sql, args in cursor.calls if "UPDATE games" in sql] == [
            (start, 11, 12, 1001),
        ]
        assert next(cursor.rows, "exhausted") == "exhausted"

    assert [args for sql, args in first.calls if "INSERT INTO game_sources" in sql] == [
        (1001, "mlb_stats", "849833"),
    ]
    assert not any("INSERT INTO game_sources" in sql for sql, _ in second.calls)


@pytest.mark.parametrize(
    "game_type",
    ["S", "E", "A", "I"],
)
def test_unsupported_or_malformed_game_type_is_skipped_without_persistence(
    game_type: Any,
) -> None:
    cursor = ScriptedCursor([])
    summary, connection = _sync_one_game(_championship_game(game_type), cursor)

    assert summary.dates_failed == 0
    assert summary.games_synchronized == 0
    assert summary.games_skipped == 1
    assert cursor.calls == []
    assert connection.committed and connection.closed
    assert not connection.rolled_back


def test_missing_game_type_is_skipped_without_persistence() -> None:
    game = _championship_game("D")
    del game["gameType"]
    cursor = ScriptedCursor([])
    summary, connection = _sync_one_game(game, cursor)
    assert summary.dates_failed == 1
    assert summary.games_synchronized == 0
    assert summary.games_skipped == 0
    assert cursor.calls == []
    assert connection.rolled_back and connection.closed
    assert not connection.committed


@pytest.mark.parametrize("game_type", ["P", "C", "X", "", "r", " D ", None, 1, True, [], {}, ["D"]])
def test_unknown_game_type_fails_date_without_persistence(game_type: Any) -> None:
    cursor = ScriptedCursor([])
    summary, connection = _sync_one_game(_championship_game(game_type), cursor)
    assert summary.dates_failed == 1
    assert summary.games_synchronized == 0
    assert cursor.calls == []
    assert connection.rolled_back and connection.closed
    assert not connection.committed


@pytest.mark.parametrize(
    "rows",
    [
        [None, (2, 1001)],
        [(1001, datetime(2026, 10, 7, 20, tzinfo=timezone.utc), 12, 11)],
    ],
    ids=["ambiguous-nearby-games", "reversed-existing-mapping"],
)
def test_postseason_identity_conflict_still_rolls_back(rows: list[Any]) -> None:
    cursor = ScriptedCursor(rows)
    summary, connection = _sync_one_game(_championship_game("D"), cursor)
    assert summary.dates_failed == 1
    assert summary.games_synchronized == 0
    assert "CanonicalGameIdentityConflictError" in summary.date_summaries[0].error_message
    assert connection.rolled_back and connection.closed
    assert not connection.committed
    assert not any("INSERT" in sql or "UPDATE" in sql for sql, _ in cursor.calls)


def test_postseason_canonical_source_supplies_pregame_semantic_deadline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A fake query result connects the real schedule linking path to the real
    # deadline loader/guard. This is SQL-contract coverage, not a database test.
    cursor = ScriptedCursor([None, (1, 1001)])
    summary, _ = _sync_one_game(_championship_game("D"), cursor)
    assert summary.games_synchronized == 1
    assert (1001, "mlb_stats", "849833") in [args for _, args in cursor.calls]
    start = datetime(2026, 10, 7, 20, tzinfo=timezone.utc)
    deadline_cursor = ScriptedCursor([(start,)])
    connection = FakeConnection()
    connection.cursor_instance = deadline_cursor

    def load_deadline(target_date: date) -> datetime | None:
        assert target_date == date(2026, 10, 7)
        return get_earliest_mlb_game_start_for_pacific_date(
            target_date, connection_factory=lambda: connection,
        )

    result = scheduled_main(
        ["--task-identity", MONEYLINE_PREGAME_TASK,
         "--enforce-canonical-pregame-deadline"],
        current_time=datetime(2026, 10, 7, 8, 10, tzinfo=PACIFIC_TIME_ZONE),
        semantic_deadline_loader=load_deadline,
    )
    assert result == 0
    output = capsys.readouterr().out
    assert "Semantic point-in-time deadline: 2026-10-07T13:00:00" in output
    assert "Canonical Pregame deadline: UNKNOWN" not in output
    assert deadline_cursor.calls == [
        (GET_EARLIEST_MLB_GAME_START_QUERY,
         ("mlb_stats", datetime(2026, 10, 7, 7, tzinfo=timezone.utc),
          datetime(2026, 10, 8, 7, tzinfo=timezone.utc))),
    ]
    assert connection.closed


@pytest.mark.parametrize("change", ["conditional", "tbd-time", "placeholder"])
def test_unresolved_postseason_never_calls_team_or_game_persistence(change):
    game = _championship_game("D")
    if change == "conditional":
        game["ifNecessary"] = "Y"
    elif change == "tbd-time":
        game["status"]["startTimeTBD"] = True
    else:
        game["teams"]["home"]["team"] = {"id": 5521, "name": "AL Lower Seed"}
    cursor = ScriptedCursor([])
    summary, connection = _sync_one_game(game, cursor)
    assert summary.games_synchronized == 0
    assert cursor.calls == []
    if change == "placeholder":
        assert summary.dates_failed == 1
        assert connection.rolled_back and not connection.committed
    else:
        assert summary.dates_failed == 0
        assert summary.games_skipped == 1


def test_conditional_game_can_later_be_confirmed_without_placeholder_or_split_game():
    game = _championship_game("D")
    game["ifNecessary"] = "Y"
    deferred = ScriptedCursor([])
    assert _sync_one_game(game, deferred)[0].games_synchronized == 0
    assert deferred.calls == []
    game["ifNecessary"] = "N"
    confirmed = ScriptedCursor([None, (1, 1001)])
    assert _sync_one_game(game, confirmed)[0].games_synchronized == 1
    assert not any("INSERT INTO games (" in sql for sql, _ in confirmed.calls)
    assert (1001, "mlb_stats", "849833") in [args for _, args in confirmed.calls]


def _game(
    *,
    game_pk: int,
    game_type: Any,
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
