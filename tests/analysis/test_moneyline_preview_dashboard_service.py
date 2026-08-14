from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from sportsmodel.analysis import (
    moneyline_preview_dashboard_service
    as service,
)
from sportsmodel.models.snapshot import (
    MarketSnapshot,
)


TARGET_DATE = date(2026, 8, 8)

SNAPSHOT_TIME = datetime(
    2026,
    8,
    7,
    18,
    30,
    tzinfo=timezone.utc,
)

PREDICTION_TIME = datetime(
    2026,
    8,
    7,
    20,
    0,
    tzinfo=timezone.utc,
)

GAME_START_TIME = datetime(
    2026,
    8,
    8,
    23,
    0,
    tzinfo=timezone.utc,
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
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_builds_read_only_preview_value_card(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    monkeypatch.setattr(
        service,
        "_load_latest_preview_run",
        lambda cursor, **kwargs: (
            service._PreviewRunMetadata(
                prediction_run_id=8,
                model_version="mlb_moneyline_v1",
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "_load_latest_opening_run",
        lambda cursor, **kwargs: 192,
    )

    monkeypatch.setattr(
        service,
        "_load_preview_predictions",
        lambda cursor, **kwargs: (
            service._StoredPreviewPrediction(
                moneyline_game_prediction_id=501,
                game_id=1001,
                prediction_time=PREDICTION_TIME,
                game_start_time=GAME_START_TIME,
                away_team_name="New York Mets",
                home_team_name="Pittsburgh Pirates",
                selection_name="New York Mets",
                model_probability=Decimal("0.52"),
                starter_coverage="both",
                home_starter_features_available=True,
                away_starter_features_available=True,
                missing_raw_value_count=2,
            ),
        ),
    )

    snapshots = []

    for sportsbook_id in range(1, 6):
        snapshots.extend(
            (
                MarketSnapshot(
                    odds_market_snapshot_id=(
                        sportsbook_id * 10
                    ),
                    game_id=1001,
                    sportsbook_id=sportsbook_id,
                    market_type="h2h",
                    selection_name="New York Mets",
                    line_value=None,
                    price=120,
                    snapshot_time=SNAPSHOT_TIME,
                ),
                MarketSnapshot(
                    odds_market_snapshot_id=(
                        sportsbook_id * 10 + 1
                    ),
                    game_id=1001,
                    sportsbook_id=sportsbook_id,
                    market_type="h2h",
                    selection_name="Pittsburgh Pirates",
                    line_value=None,
                    price=-140,
                    snapshot_time=SNAPSHOT_TIME,
                ),
            )
        )

    monkeypatch.setattr(
        service,
        "_load_opening_snapshots",
        lambda cursor, **kwargs: (
            tuple(snapshots),
            {
                sportsbook_id: f"Book {sportsbook_id}"
                for sportsbook_id in range(1, 6)
            },
        ),
    )

    result = (
        service.build_moneyline_preview_dashboard(
            target_date=TARGET_DATE,
            connection_factory=lambda: connection,
        )
    )

    assert result.prediction_run_id == 8
    assert result.odds_ingestion_run_id == 192
    assert result.model_version == "mlb_moneyline_v1"
    assert result.predictions_loaded == 1
    assert len(result.games) == 1
    assert result.unavailable_games == ()

    game = result.games[0]

    assert game.predicted_team_name == "New York Mets"
    assert game.price == 120
    assert game.sportsbook_count == 5
    assert game.preview_value_signal is True
    assert game.preview_policy_pass is True
    assert game.model_expected_value > Decimal("0.03")
    assert game.model_market_edge > Decimal("0.02")
    assert game.missing_raw_value_count == 2

    assert connection.commits == 0
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_closes_connection_when_preview_missing(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    def raise_missing_preview(
        cursor,
        **kwargs,
    ):
        raise LookupError(
            "No completed Moneyline preview run exists."
        )

    monkeypatch.setattr(
        service,
        "_load_latest_preview_run",
        raise_missing_preview,
    )

    with pytest.raises(
        LookupError,
        match="preview run",
    ):
        service.build_moneyline_preview_dashboard(
            target_date=TARGET_DATE,
            connection_factory=lambda: connection,
        )

    assert connection.commits == 0
    assert connection.rollbacks == 0
    assert connection.closed is True



def test_records_unavailable_market_without_failing_preview(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    monkeypatch.setattr(
        service,
        "_load_latest_preview_run",
        lambda cursor, **kwargs: (
            service._PreviewRunMetadata(
                prediction_run_id=10,
                model_version="mlb_moneyline_v1",
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "_load_latest_opening_run",
        lambda cursor, **kwargs: 196,
    )

    monkeypatch.setattr(
        service,
        "_load_preview_predictions",
        lambda cursor, **kwargs: (
            service._StoredPreviewPrediction(
                moneyline_game_prediction_id=601,
                game_id=8215,
                prediction_time=PREDICTION_TIME,
                game_start_time=GAME_START_TIME,
                away_team_name="Athletics",
                home_team_name="Boston Red Sox",
                selection_name="Boston Red Sox",
                model_probability=Decimal("0.64"),
                starter_coverage="partial",
                home_starter_features_available=False,
                away_starter_features_available=True,
                missing_raw_value_count=11,
            ),
        ),
    )

    incomplete_snapshot = MarketSnapshot(
        odds_market_snapshot_id=9001,
        game_id=8215,
        sportsbook_id=1,
        market_type="h2h",
        selection_name="Boston Red Sox",
        line_value=None,
        price=-180,
        snapshot_time=SNAPSHOT_TIME,
    )

    monkeypatch.setattr(
        service,
        "_load_opening_snapshots",
        lambda cursor, **kwargs: (
            (incomplete_snapshot,),
            {1: "Book One"},
        ),
    )

    result = (
        service.build_moneyline_preview_dashboard(
            target_date=TARGET_DATE,
            connection_factory=lambda: connection,
        )
    )

    assert result.predictions_loaded == 1
    assert result.games == ()
    assert len(result.unavailable_games) == 1

    unavailable = result.unavailable_games[0]

    assert unavailable.game_id == 8215
    assert unavailable.predicted_team_name == "Boston Red Sox"
    assert unavailable.model_probability == Decimal("0.64")
    assert unavailable.missing_raw_value_count == 11
    assert unavailable.reason == "Current preview market consensus unavailable"

    assert connection.commits == 0
    assert connection.rollbacks == 0
    assert connection.closed is True



@pytest.mark.parametrize(
    (
        "role",
        "opening_pass",
        "current_pass",
        "current_signal",
        "expected",
    ),
    (
        (
            "opening",
            True,
            True,
            True,
            "OPENING ONLY",
        ),
        (
            "late_night",
            False,
            True,
            True,
            "NEW VALUE",
        ),
        (
            "late_night",
            True,
            True,
            True,
            "STILL VALUE",
        ),
        (
            "late_night",
            True,
            False,
            False,
            "VALUE LOST",
        ),
        (
            "late_night",
            False,
            False,
            True,
            "POLICY BLOCKED",
        ),
        (
            "late_night",
            False,
            False,
            False,
            "NO VALUE",
        ),
        (
            "late_night",
            None,
            True,
            True,
            "LATE-NIGHT VALUE",
        ),
    ),
)
def test_classifies_preview_movement(
    role,
    opening_pass,
    current_pass,
    current_signal,
    expected,
) -> None:
    assert (
        service._classify_preview_movement(
            market_snapshot_role=role,
            opening_policy_pass=opening_pass,
            current_policy_pass=current_pass,
            current_value_signal=current_signal,
        )
        == expected
    )



def test_builds_late_night_value_comparison(
    monkeypatch,
) -> None:
    connection = FakeConnection()

    late_snapshot_time = datetime(
        2026,
        8,
        8,
        7,
        0,
        tzinfo=timezone.utc,
    )

    monkeypatch.setattr(
        service,
        "_load_latest_preview_run",
        lambda cursor, **kwargs: (
            service._PreviewRunMetadata(
                prediction_run_id=20,
                model_version="mlb_moneyline_v1",
            )
        ),
    )

    def load_market_run(
        cursor,
        *,
        target_date,
        include_late_night=True,
        include_role=False,
    ):
        run_id = (
            201
            if include_late_night
            else 192
        )

        if include_role:
            return (
                run_id,
                (
                    "late_night"
                    if include_late_night
                    else "opening"
                ),
            )

        return run_id

    monkeypatch.setattr(
        service,
        "_load_latest_opening_run",
        load_market_run,
    )

    monkeypatch.setattr(
        service,
        "_load_preview_predictions",
        lambda cursor, **kwargs: (
            service._StoredPreviewPrediction(
                moneyline_game_prediction_id=701,
                game_id=2001,
                prediction_time=PREDICTION_TIME,
                game_start_time=GAME_START_TIME,
                away_team_name="New York Mets",
                home_team_name="Pittsburgh Pirates",
                selection_name="New York Mets",
                model_probability=Decimal("0.55"),
                starter_coverage="both",
                home_starter_features_available=True,
                away_starter_features_available=True,
                missing_raw_value_count=0,
            ),
        ),
    )

    opening_snapshots = []
    late_snapshots = []

    for sportsbook_id in range(1, 6):
        opening_snapshots.extend(
            (
                MarketSnapshot(
                    odds_market_snapshot_id=(
                        1000 + sportsbook_id * 10
                    ),
                    game_id=2001,
                    sportsbook_id=sportsbook_id,
                    market_type="h2h",
                    selection_name="New York Mets",
                    line_value=None,
                    price=-130,
                    snapshot_time=SNAPSHOT_TIME,
                ),
                MarketSnapshot(
                    odds_market_snapshot_id=(
                        1001 + sportsbook_id * 10
                    ),
                    game_id=2001,
                    sportsbook_id=sportsbook_id,
                    market_type="h2h",
                    selection_name="Pittsburgh Pirates",
                    line_value=None,
                    price=110,
                    snapshot_time=SNAPSHOT_TIME,
                ),
            )
        )

        late_snapshots.extend(
            (
                MarketSnapshot(
                    odds_market_snapshot_id=(
                        2000 + sportsbook_id * 10
                    ),
                    game_id=2001,
                    sportsbook_id=sportsbook_id,
                    market_type="h2h",
                    selection_name="New York Mets",
                    line_value=None,
                    price=110,
                    snapshot_time=late_snapshot_time,
                ),
                MarketSnapshot(
                    odds_market_snapshot_id=(
                        2001 + sportsbook_id * 10
                    ),
                    game_id=2001,
                    sportsbook_id=sportsbook_id,
                    market_type="h2h",
                    selection_name="Pittsburgh Pirates",
                    line_value=None,
                    price=-130,
                    snapshot_time=late_snapshot_time,
                ),
            )
        )

    def load_snapshots(
        cursor,
        *,
        prediction_run_id,
        odds_ingestion_run_id,
    ):
        snapshots = (
            tuple(late_snapshots)
            if odds_ingestion_run_id == 201
            else tuple(opening_snapshots)
        )

        return (
            snapshots,
            {
                sportsbook_id: f"Book {sportsbook_id}"
                for sportsbook_id in range(1, 6)
            },
        )

    monkeypatch.setattr(
        service,
        "_load_opening_snapshots",
        load_snapshots,
    )

    result = (
        service.build_moneyline_preview_dashboard(
            target_date=TARGET_DATE,
            connection_factory=lambda: connection,
        )
    )

    assert result.market_snapshot_role == "late_night"
    assert result.odds_ingestion_run_id == 201
    assert result.opening_odds_ingestion_run_id == 192

    game = result.games[0]

    assert game.price == 110
    assert game.opening_price == -130
    assert game.opening_policy_pass is False
    assert game.preview_policy_pass is True
    assert game.movement_status == "NEW VALUE"

    assert connection.commits == 0
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_evening_preview_timeline_support() -> None:
    assert (
        service._classify_preview_movement(
            market_snapshot_role="evening",
            opening_policy_pass=None,
            current_policy_pass=True,
            current_value_signal=True,
        )
        == "EVENING VALUE"
    )

    assert (
        service._classify_preview_movement(
            market_snapshot_role="evening",
            opening_policy_pass=True,
            current_policy_pass=True,
            current_value_signal=True,
        )
        == "STILL VALUE"
    )

    assert (
        service._classify_preview_movement(
            market_snapshot_role="evening",
            opening_policy_pass=True,
            current_policy_pass=False,
            current_value_signal=False,
        )
        == "VALUE LOST"
    )


def test_evening_loader_returns_role_when_requested() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.parameters = None

        def execute(self, query, parameters) -> None:
            self.parameters = parameters

        def fetchone(self):
            return (
                777,
                "evening",
            )

    cursor = Cursor()

    result = service._load_latest_opening_run(
        cursor,
        target_date=TARGET_DATE,
        include_role=True,
    )

    assert result == (
        777,
        "evening",
    )

    assert cursor.parameters[1] == [
        "opening",
        "evening",
        "late_night",
    ]
