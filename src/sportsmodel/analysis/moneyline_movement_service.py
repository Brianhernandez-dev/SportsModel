from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sportsmodel.analysis.closing_line_value import (
    calculate_closing_line_value_markets,
)
from sportsmodel.analysis.line_movement import (
    calculate_line_movements,
)
from sportsmodel.analysis.market_builder import (
    build_complete_markets,
)
from sportsmodel.analysis.market_timeline import (
    build_market_timelines,
)
from sportsmodel.analysis.probability import (
    american_to_implied_probability,
)
from sportsmodel.database.connection import get_connection
from sportsmodel.models.closing_line_value import (
    ClosingLineValueMarket,
)
from sportsmodel.models.movement import LineMovement
from sportsmodel.models.snapshot import MarketSnapshot


ConnectionFactory = Callable[[], Any]

MONEYLINE_MOVEMENT_SNAPSHOT_ROLES = (
    "opening",
    "morning",
    "entry",
    "afternoon",
    "near_close",
)

MovementKey = tuple[int, int, str, str]
MarketMetadataKey = tuple[
    int,
    int,
    str,
    datetime,
]


@dataclass(frozen=True)
class MoneylineSnapshotRun:
    """
    One completed role-based odds run selected for a target date.
    """

    odds_ingestion_run_id: int
    snapshot_role: str


@dataclass(frozen=True)
class RoleTaggedMarketSnapshot:
    """
    One stored market snapshot with its ingestion-run context.
    """

    snapshot: MarketSnapshot
    odds_ingestion_run_id: int
    snapshot_role: str


@dataclass(frozen=True)
class MoneylineSelectionMovement:
    """
    Role-aware opening-to-latest movement for one selection.
    """

    movement: LineMovement

    opening_snapshot_role: str
    latest_snapshot_role: str

    opening_odds_ingestion_run_id: int
    latest_odds_ingestion_run_id: int

    opening_implied_probability: Decimal
    latest_implied_probability: Decimal
    implied_probability_change: Decimal


@dataclass(frozen=True)
class MoneylineClosingLineValue:
    """
    Role-aware CLV comparison for one complete sportsbook market.
    """

    clv_market: ClosingLineValueMarket

    bet_snapshot_role: str
    closing_snapshot_role: str

    bet_odds_ingestion_run_id: int
    closing_odds_ingestion_run_id: int


@dataclass(frozen=True)
class MoneylineMovementReport:
    """
    Read-only movement and CLV report for one target slate.
    """

    target_date: date

    snapshot_runs: tuple[
        MoneylineSnapshotRun,
        ...,
    ]

    snapshots_loaded: int

    movements: tuple[
        MoneylineSelectionMovement,
        ...,
    ]

    closing_line_values: tuple[
        MoneylineClosingLineValue,
        ...,
    ]

    @property
    def roles_loaded(self) -> tuple[str, ...]:
        return tuple(
            run.snapshot_role
            for run in self.snapshot_runs
        )


def build_moneyline_movement_report(
    *,
    target_date: date,
    connection_factory: ConnectionFactory = get_connection,
) -> MoneylineMovementReport:
    """
    Build a read-only role-aware Moneyline movement and CLV report.

    For each supported snapshot role, only the newest completed run for
    the target date is selected.

    Opening-to-latest movement requires a true ``opening`` snapshot.
    The derived close is the latest complete pregame market available
    for each game and sportsbook timeline.
    """

    if not isinstance(target_date, date):
        raise TypeError(
            "Target date must be a datetime.date value."
        )

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            snapshot_runs = (
                _load_completed_snapshot_runs(
                    cursor,
                    target_date=target_date,
                )
            )

            role_snapshots = _load_role_snapshots(
                cursor,
                snapshot_runs=snapshot_runs,
            )

        return MoneylineMovementReport(
            target_date=target_date,
            snapshot_runs=snapshot_runs,
            snapshots_loaded=len(role_snapshots),
            movements=tuple(
                _build_selection_movements(
                    role_snapshots
                )
            ),
            closing_line_values=tuple(
                _build_closing_line_values(
                    role_snapshots
                )
            ),
        )

    finally:
        connection.close()


def _load_completed_snapshot_runs(
    cursor: Any,
    *,
    target_date: date,
) -> tuple[MoneylineSnapshotRun, ...]:
    cursor.execute(
        """
        WITH selected_runs AS (
            SELECT DISTINCT ON (snapshot_role)
                odds_ingestion_run_id,
                snapshot_role
            FROM odds_ingestion_runs
            WHERE target_date = %s
              AND status = 'completed'
              AND snapshot_role = ANY(%s)
            ORDER BY
                snapshot_role,
                odds_ingestion_run_id DESC
        )
        SELECT
            odds_ingestion_run_id,
            snapshot_role
        FROM selected_runs
        ORDER BY
            CASE snapshot_role
                WHEN 'opening' THEN 1
                WHEN 'morning' THEN 2
                WHEN 'entry' THEN 3
                WHEN 'afternoon' THEN 4
                WHEN 'near_close' THEN 5
                ELSE 99
            END,
            odds_ingestion_run_id;
        """,
        (
            target_date,
            list(
                MONEYLINE_MOVEMENT_SNAPSHOT_ROLES
            ),
        ),
    )

    return tuple(
        MoneylineSnapshotRun(
            odds_ingestion_run_id=row[0],
            snapshot_role=row[1],
        )
        for row in cursor.fetchall()
    )


def _load_role_snapshots(
    cursor: Any,
    *,
    snapshot_runs: tuple[
        MoneylineSnapshotRun,
        ...,
    ],
) -> tuple[RoleTaggedMarketSnapshot, ...]:
    if not snapshot_runs:
        return ()

    role_by_run_id = {
        run.odds_ingestion_run_id:
            run.snapshot_role
        for run in snapshot_runs
    }

    run_ids = list(role_by_run_id)

    cursor.execute(
        """
        SELECT
            snapshot.odds_market_snapshot_id,
            snapshot.game_id,
            snapshot.sportsbook_id,
            snapshot.market_type,
            snapshot.selection_name,
            snapshot.line_value,
            snapshot.price,
            snapshot.snapshot_time,
            snapshot.odds_ingestion_run_id
        FROM odds_market_snapshots AS snapshot
        WHERE
            snapshot.odds_ingestion_run_id = ANY(%s)
            AND snapshot.market_type = 'h2h'
        ORDER BY
            snapshot.snapshot_time,
            snapshot.game_id,
            snapshot.sportsbook_id,
            snapshot.selection_name,
            snapshot.odds_market_snapshot_id;
        """,
        (run_ids,),
    )

    snapshots: list[
        RoleTaggedMarketSnapshot
    ] = []

    for row in cursor.fetchall():
        odds_ingestion_run_id = row[8]

        snapshots.append(
            RoleTaggedMarketSnapshot(
                snapshot=MarketSnapshot(
                    odds_market_snapshot_id=row[0],
                    game_id=row[1],
                    sportsbook_id=row[2],
                    market_type=row[3],
                    selection_name=row[4],
                    line_value=row[5],
                    price=row[6],
                    snapshot_time=row[7],
                ),
                odds_ingestion_run_id=(
                    odds_ingestion_run_id
                ),
                snapshot_role=role_by_run_id[
                    odds_ingestion_run_id
                ],
            )
        )

    return tuple(snapshots)


def _build_selection_movements(
    role_snapshots: tuple[
        RoleTaggedMarketSnapshot,
        ...,
    ],
) -> list[MoneylineSelectionMovement]:
    grouped: dict[
        MovementKey,
        list[RoleTaggedMarketSnapshot],
    ] = defaultdict(list)

    for role_snapshot in role_snapshots:
        snapshot = role_snapshot.snapshot

        key = (
            snapshot.game_id,
            snapshot.sportsbook_id,
            snapshot.market_type,
            snapshot.selection_name,
        )

        grouped[key].append(role_snapshot)

    results: list[
        MoneylineSelectionMovement
    ] = []

    for group in grouped.values():
        opening_candidates = [
            role_snapshot
            for role_snapshot in group
            if role_snapshot.snapshot_role
            == "opening"
        ]

        if not opening_candidates:
            continue

        opening = min(
            opening_candidates,
            key=_role_snapshot_order,
        )

        comparable_snapshots = [
            role_snapshot
            for role_snapshot in group
            if _role_snapshot_order(role_snapshot)
            >= _role_snapshot_order(opening)
        ]

        if len(comparable_snapshots) < 2:
            continue

        latest = max(
            comparable_snapshots,
            key=_role_snapshot_order,
        )

        raw_movements = calculate_line_movements(
            role_snapshot.snapshot
            for role_snapshot in comparable_snapshots
        )

        if not raw_movements:
            continue

        movement = raw_movements[0]

        opening_probability = (
            american_to_implied_probability(
                opening.snapshot.price
            )
        )

        latest_probability = (
            american_to_implied_probability(
                latest.snapshot.price
            )
        )

        results.append(
            MoneylineSelectionMovement(
                movement=movement,
                opening_snapshot_role=(
                    opening.snapshot_role
                ),
                latest_snapshot_role=(
                    latest.snapshot_role
                ),
                opening_odds_ingestion_run_id=(
                    opening.odds_ingestion_run_id
                ),
                latest_odds_ingestion_run_id=(
                    latest.odds_ingestion_run_id
                ),
                opening_implied_probability=(
                    opening_probability
                ),
                latest_implied_probability=(
                    latest_probability
                ),
                implied_probability_change=(
                    latest_probability
                    - opening_probability
                ),
            )
        )

    results.sort(
        key=lambda result: (
            result.movement.game_id,
            result.movement.sportsbook_id,
            result.movement.selection_name,
        )
    )

    return results


def _build_closing_line_values(
    role_snapshots: tuple[
        RoleTaggedMarketSnapshot,
        ...,
    ],
) -> list[MoneylineClosingLineValue]:
    complete_markets = build_complete_markets(
        role_snapshot.snapshot
        for role_snapshot in role_snapshots
    )

    timelines = build_market_timelines(
        complete_markets
    )

    raw_clv_markets = (
        calculate_closing_line_value_markets(
            timelines
        )
    )

    metadata_by_market: dict[
        MarketMetadataKey,
        RoleTaggedMarketSnapshot,
    ] = {}

    for role_snapshot in role_snapshots:
        snapshot = role_snapshot.snapshot

        metadata_by_market[
            (
                snapshot.game_id,
                snapshot.sportsbook_id,
                snapshot.market_type,
                snapshot.snapshot_time,
            )
        ] = role_snapshot

    results: list[
        MoneylineClosingLineValue
    ] = []

    for clv_market in raw_clv_markets:
        bet_metadata = metadata_by_market.get(
            (
                clv_market.game_id,
                clv_market.sportsbook_id,
                clv_market.market_type,
                clv_market.bet_snapshot_time,
            )
        )

        closing_metadata = (
            metadata_by_market.get(
                (
                    clv_market.game_id,
                    clv_market.sportsbook_id,
                    clv_market.market_type,
                    clv_market.closing_snapshot_time,
                )
            )
        )

        if (
            bet_metadata is None
            or closing_metadata is None
        ):
            continue

        results.append(
            MoneylineClosingLineValue(
                clv_market=clv_market,
                bet_snapshot_role=(
                    bet_metadata.snapshot_role
                ),
                closing_snapshot_role=(
                    closing_metadata.snapshot_role
                ),
                bet_odds_ingestion_run_id=(
                    bet_metadata
                    .odds_ingestion_run_id
                ),
                closing_odds_ingestion_run_id=(
                    closing_metadata
                    .odds_ingestion_run_id
                ),
            )
        )

    results.sort(
        key=lambda result: (
            result.clv_market.bet_snapshot_time,
            result.clv_market.game_id,
            result.clv_market.sportsbook_id,
        )
    )

    return results


def _role_snapshot_order(
    role_snapshot: RoleTaggedMarketSnapshot,
) -> tuple[datetime, int]:
    return (
        role_snapshot.snapshot.snapshot_time,
        role_snapshot
        .snapshot
        .odds_market_snapshot_id,
    )
