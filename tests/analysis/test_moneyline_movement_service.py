from datetime import date, datetime, timezone
from decimal import Decimal

from sportsmodel.analysis import (
    moneyline_movement_service as service,
)
from sportsmodel.models.snapshot import MarketSnapshot


TARGET_DATE = date(2026, 8, 7)


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
        self.closed = False

    def cursor(self):
        return FakeCursor()

    def close(self) -> None:
        self.closed = True


def test_builds_role_aware_movement_and_clv_report(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    runs = _snapshot_runs()

    monkeypatch.setattr(
        service,
        "_load_completed_snapshot_runs",
        lambda cursor, **kwargs: runs,
    )

    monkeypatch.setattr(
        service,
        "_load_role_snapshots",
        lambda cursor, **kwargs: (
            _role_snapshots()
        ),
    )

    report = (
        service.build_moneyline_movement_report(
            target_date=TARGET_DATE,
            connection_factory=lambda: connection,
        )
    )

    assert report.roles_loaded == (
        "opening",
        "morning",
        "entry",
        "afternoon",
    )

    assert report.snapshots_loaded == 8
    assert len(report.movements) == 2
    assert len(report.closing_line_values) == 3

    team_a = next(
        result
        for result in report.movements
        if (
            result.movement.selection_name
            == "Team A"
        )
    )

    assert (
        team_a.opening_snapshot_role
        == "opening"
    )

    assert (
        team_a.latest_snapshot_role
        == "afternoon"
    )

    assert (
        team_a
        .opening_odds_ingestion_run_id
        == 188
    )

    assert (
        team_a
        .latest_odds_ingestion_run_id
        == 191
    )

    assert team_a.movement.opening_price == 120
    assert team_a.movement.latest_price == 100
    assert team_a.movement.price_change == -20
    assert team_a.movement.snapshot_count == 4

    assert (
        team_a.implied_probability_change.quantize(
            Decimal("0.000001")
        )
        == Decimal("0.045455")
    )

    assert {
        (
            result.bet_snapshot_role,
            result.closing_snapshot_role,
        )
        for result
        in report.closing_line_values
    } == {
        ("opening", "afternoon"),
        ("morning", "afternoon"),
        ("entry", "afternoon"),
    }

    assert connection.closed is True


def test_movement_requires_true_opening_role(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    runs = (
        service.MoneylineSnapshotRun(
            odds_ingestion_run_id=189,
            snapshot_role="morning",
        ),
        service.MoneylineSnapshotRun(
            odds_ingestion_run_id=191,
            snapshot_role="afternoon",
        ),
    )

    snapshots = tuple(
        role_snapshot
        for role_snapshot in _role_snapshots()
        if role_snapshot.snapshot_role
        in {"morning", "afternoon"}
    )

    monkeypatch.setattr(
        service,
        "_load_completed_snapshot_runs",
        lambda cursor, **kwargs: runs,
    )

    monkeypatch.setattr(
        service,
        "_load_role_snapshots",
        lambda cursor, **kwargs: snapshots,
    )

    report = (
        service.build_moneyline_movement_report(
            target_date=TARGET_DATE,
            connection_factory=lambda: connection,
        )
    )

    assert report.movements == ()
    assert len(report.closing_line_values) == 1
    assert connection.closed is True


def test_empty_target_date_returns_empty_report(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    monkeypatch.setattr(
        service,
        "_load_completed_snapshot_runs",
        lambda cursor, **kwargs: (),
    )

    monkeypatch.setattr(
        service,
        "_load_role_snapshots",
        lambda cursor, **kwargs: (),
    )

    report = (
        service.build_moneyline_movement_report(
            target_date=TARGET_DATE,
            connection_factory=lambda: connection,
        )
    )

    assert report.snapshot_runs == ()
    assert report.roles_loaded == ()
    assert report.snapshots_loaded == 0
    assert report.movements == ()
    assert report.closing_line_values == ()
    assert connection.closed is True


def test_snapshot_run_lookup_is_explicitly_mlb_scoped() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.query = None
            self.parameters = None

        def execute(self, query, parameters) -> None:
            self.query = query
            self.parameters = parameters

        def fetchall(self):
            return []

    cursor = Cursor()

    assert service._load_completed_snapshot_runs(
        cursor,
        target_date=TARGET_DATE,
    ) == ()
    assert "sport = %s" in cursor.query
    assert cursor.parameters[2] == "baseball_mlb"


def _snapshot_runs(
) -> tuple[service.MoneylineSnapshotRun, ...]:
    return (
        service.MoneylineSnapshotRun(
            odds_ingestion_run_id=188,
            snapshot_role="opening",
        ),
        service.MoneylineSnapshotRun(
            odds_ingestion_run_id=189,
            snapshot_role="morning",
        ),
        service.MoneylineSnapshotRun(
            odds_ingestion_run_id=190,
            snapshot_role="entry",
        ),
        service.MoneylineSnapshotRun(
            odds_ingestion_run_id=191,
            snapshot_role="afternoon",
        ),
    )


def _role_snapshots(
) -> tuple[
    service.RoleTaggedMarketSnapshot,
    ...,
]:
    role_prices = (
        (
            "opening",
            188,
            datetime(
                2026,
                8,
                7,
                1,
                45,
                tzinfo=timezone.utc,
            ),
            120,
            -130,
        ),
        (
            "morning",
            189,
            datetime(
                2026,
                8,
                7,
                13,
                0,
                tzinfo=timezone.utc,
            ),
            110,
            -120,
        ),
        (
            "entry",
            190,
            datetime(
                2026,
                8,
                7,
                15,
                0,
                tzinfo=timezone.utc,
            ),
            105,
            -115,
        ),
        (
            "afternoon",
            191,
            datetime(
                2026,
                8,
                7,
                19,
                0,
                tzinfo=timezone.utc,
            ),
            100,
            -110,
        ),
    )

    results: list[
        service.RoleTaggedMarketSnapshot
    ] = []

    snapshot_id = 1

    for (
        role,
        run_id,
        snapshot_time,
        team_a_price,
        team_b_price,
    ) in role_prices:
        for selection_name, price in (
            ("Team A", team_a_price),
            ("Team B", team_b_price),
        ):
            results.append(
                service.RoleTaggedMarketSnapshot(
                    snapshot=MarketSnapshot(
                        odds_market_snapshot_id=(
                            snapshot_id
                        ),
                        game_id=8184,
                        sportsbook_id=1,
                        market_type="h2h",
                        selection_name=(
                            selection_name
                        ),
                        line_value=None,
                        price=price,
                        snapshot_time=(
                            snapshot_time
                        ),
                    ),
                    odds_ingestion_run_id=run_id,
                    snapshot_role=role,
                )
            )

            snapshot_id += 1

    return tuple(results)


def test_single_opening_snapshot_does_not_create_movement(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    runs = (
        service.MoneylineSnapshotRun(
            odds_ingestion_run_id=188,
            snapshot_role="opening",
        ),
    )

    snapshots = tuple(
        role_snapshot
        for role_snapshot in _role_snapshots()
        if role_snapshot.snapshot_role == "opening"
    )

    monkeypatch.setattr(
        service,
        "_load_completed_snapshot_runs",
        lambda cursor, **kwargs: runs,
    )

    monkeypatch.setattr(
        service,
        "_load_role_snapshots",
        lambda cursor, **kwargs: snapshots,
    )

    report = (
        service.build_moneyline_movement_report(
            target_date=TARGET_DATE,
            connection_factory=lambda: connection,
        )
    )

    assert report.roles_loaded == ("opening",)
    assert report.snapshots_loaded == 2
    assert report.movements == ()
    assert report.closing_line_values == ()
    assert connection.closed is True
