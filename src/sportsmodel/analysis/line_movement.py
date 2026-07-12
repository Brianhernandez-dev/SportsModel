from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from sportsmodel.models import LineMovement, MarketSnapshot


MovementKey = tuple[int, int, str, str]


def calculate_line_movements(
    snapshots: Iterable[MarketSnapshot],
) -> list[LineMovement]:
    """
    Calculate opening-to-latest movement for each sportsbook selection.

    Snapshots are grouped by:
    - game
    - sportsbook
    - market type
    - selection

    Each group produces one LineMovement record.
    """

    grouped_snapshots: dict[
        MovementKey,
        list[MarketSnapshot],
    ] = defaultdict(list)

    for snapshot in snapshots:
        key = (
            snapshot.game_id,
            snapshot.sportsbook_id,
            snapshot.market_type,
            snapshot.selection_name,
        )

        grouped_snapshots[key].append(snapshot)

    movements: list[LineMovement] = []

    for group in grouped_snapshots.values():
        ordered = sorted(
            group,
            key=lambda snapshot: (
                snapshot.snapshot_time,
                snapshot.odds_market_snapshot_id,
            ),
        )

        opening = ordered[0]
        latest = ordered[-1]

        line_change = _calculate_line_change(
            opening.line_value,
            latest.line_value,
        )

        movements.append(
            LineMovement(
                game_id=opening.game_id,
                sportsbook_id=opening.sportsbook_id,
                market_type=opening.market_type,
                selection_name=opening.selection_name,
                opening_line=opening.line_value,
                latest_line=latest.line_value,
                line_change=line_change,
                opening_price=opening.price,
                latest_price=latest.price,
                price_change=latest.price - opening.price,
                first_snapshot=opening.snapshot_time,
                latest_snapshot=latest.snapshot_time,
                snapshot_count=len(ordered),
            )
        )

    movements.sort(
        key=lambda movement: (
            movement.game_id,
            movement.sportsbook_id,
            movement.market_type,
            movement.selection_name,
        )
    )

    return movements


def _calculate_line_change(
    opening_line: Decimal | None,
    latest_line: Decimal | None,
) -> Decimal | None:
    """
    Return the numeric line difference when both line values exist.

    Moneyline markets have no line value and therefore return None.
    """

    if opening_line is None or latest_line is None:
        return None

    return latest_line - opening_line