from sportsmodel.database.connection import get_connection
from sportsmodel.models import MarketSnapshot


def get_market_snapshots() -> list[MarketSnapshot]:
    """
    Return all market snapshots ordered chronologically.
    """

    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    odds_market_snapshot_id,
                    game_id,
                    sportsbook_id,
                    market_type,
                    selection_name,
                    line_value,
                    price,
                    snapshot_time
                FROM odds_market_snapshots
                ORDER BY
                    snapshot_time,
                    game_id,
                    sportsbook_id,
                    market_type,
                    selection_name;
                """
            )

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