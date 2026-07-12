from sportsmodel.database.connection import get_connection
from sportsmodel.models import MarketSnapshot


def get_market_snapshots(
    game_id: int | None = None,
    include_live: bool = False,
) -> list[MarketSnapshot]:
    """
    Return market snapshots ordered chronologically.

    By default, only snapshots captured before the scheduled game start
    are returned. Set include_live=True to include live and post-start
    snapshots.

    Args:
        game_id:
            Optionally limit results to one canonical game.
        include_live:
            Include snapshots captured at or after the scheduled start.
    """

    conditions: list[str] = []
    parameters: list[object] = []

    if not include_live:
        conditions.append("oms.snapshot_time < g.game_date")

    if game_id is not None:
        conditions.append("oms.game_id = %s")
        parameters.append(game_id)

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            oms.odds_market_snapshot_id,
            oms.game_id,
            oms.sportsbook_id,
            oms.market_type,
            oms.selection_name,
            oms.line_value,
            oms.price,
            oms.snapshot_time
        FROM odds_market_snapshots oms
        JOIN games g
            ON g.game_id = oms.game_id
        {where_clause}
        ORDER BY
            oms.snapshot_time,
            oms.odds_market_snapshot_id;
    """

    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            rows = cursor.fetchall()

        return [
            MarketSnapshot(
                odds_market_snapshot_id=row[0],
                game_id=row[1],
                sportsbook_id=row[2],
                market_type=row[3],
                selection_name=row[4],
                line_value=row[5],
                price=row[6],
                snapshot_time=row[7],
            )
            for row in rows
        ]

    finally:
        connection.close()