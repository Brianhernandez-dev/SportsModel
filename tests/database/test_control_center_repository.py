from datetime import date, datetime, timezone

from sportsmodel.database.control_center_repository import (
    get_system_health_summary,
)


class FakeCursor:
    def __init__(
        self,
        rows: list[tuple | None],
    ) -> None:
        self.rows = list(rows)
        self.queries: list[str] = []

    def __enter__(self):
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
        parameters=None,
    ) -> None:
        self.queries.append(query)

    def fetchone(self):
        return self.rows.pop(0)


class FakeConnection:
    def __init__(
        self,
        rows: list[tuple | None],
    ) -> None:
        self.cursor_instance = FakeCursor(rows)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_get_system_health_summary() -> None:
    latest_snapshot_time = datetime(
        2026,
        7,
        12,
        1,
        14,
        tzinfo=timezone.utc,
    )
    latest_run_started_at = datetime(
        2026,
        7,
        12,
        1,
        13,
        tzinfo=timezone.utc,
    )
    latest_run_completed_at = datetime(
        2026,
        7,
        12,
        1,
        14,
        tzinfo=timezone.utc,
    )

    connection = FakeConnection(
        [
            (8037,),
            (7999, date(2026, 7, 28)),
            (7998,),
            (7999,),
            (141450, latest_snapshot_time),
            (
                "completed",
                latest_run_started_at,
                latest_run_completed_at,
                None,
            ),
        ]
    )

    summary = get_system_health_summary(
        connection_factory=lambda: connection,
    )

    assert summary.canonical_games_count == 8037
    assert summary.completed_games_count == 7999
    assert (
        summary.latest_completed_game_date
        == date(2026, 7, 28)
    )
    assert (
        summary.games_with_complete_team_statistics_count
        == 7998
    )
    assert (
        summary.games_with_pitching_statistics_count
        == 7999
    )
    assert summary.odds_snapshot_count == 141450
    assert (
        summary.latest_odds_snapshot_time
        == latest_snapshot_time
    )
    assert summary.latest_odds_run_status == "completed"
    assert (
        summary.latest_odds_run_started_at
        == latest_run_started_at
    )
    assert (
        summary.latest_odds_run_completed_at
        == latest_run_completed_at
    )
    assert summary.latest_odds_run_error_message is None
    assert connection.closed is True
    assert len(connection.cursor_instance.queries) == 6


def test_get_system_health_summary_handles_no_odds_run() -> None:
    connection = FakeConnection(
        [
            (20,),
            (15, date(2026, 7, 28)),
            (14,),
            (14,),
            (0, None),
            None,
        ]
    )

    summary = get_system_health_summary(
        connection_factory=lambda: connection,
    )

    assert summary.odds_snapshot_count == 0
    assert summary.latest_odds_snapshot_time is None
    assert summary.latest_odds_run_status is None
    assert summary.latest_odds_run_started_at is None
    assert summary.latest_odds_run_completed_at is None
    assert summary.latest_odds_run_error_message is None
    assert connection.closed is True
