from collections import defaultdict
from decimal import Decimal

from sportsmodel.database.connection import get_connection


def american_to_implied_probability(price):
    """Convert American odds to implied probability."""

    if price > 0:
        return Decimal("100") / Decimal(price + 100)

    return Decimal(abs(price)) / Decimal(abs(price) + 100)


def analyze_markets():
    """
    Analyze stored odds snapshots and populate market_analysis.

    Markets are grouped by:
    - game
    - market type
    - line value
    - snapshot time

    Within each group, sportsbook prices are compared for each selection.
    """

    connection = get_connection()

    groups = defaultdict(list)
    analysis_rows = []

    try:
        with connection:
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
                        game_id,
                        market_type,
                        line_value,
                        snapshot_time,
                        selection_name;
                    """
                )

                snapshots = cursor.fetchall()

                for snapshot in snapshots:
                    (
                        snapshot_id,
                        game_id,
                        sportsbook_id,
                        market_type,
                        selection_name,
                        line_value,
                        price,
                        snapshot_time,
                    ) = snapshot

                    group_key = (
                        game_id,
                        market_type,
                        line_value,
                        snapshot_time,
                    )

                    groups[group_key].append(
                        {
                            "snapshot_id": snapshot_id,
                            "sportsbook_id": sportsbook_id,
                            "selection_name": selection_name,
                            "price": price,
                        }
                    )

                for group in groups.values():
                    selections = defaultdict(list)

                    for row in group:
                        selections[row["selection_name"]].append(row)

                    implied_by_selection = {}

                    for selection_name, rows in selections.items():
                        implied_values = [
                            american_to_implied_probability(row["price"])
                            for row in rows
                        ]

                        implied_by_selection[selection_name] = (
                            sum(implied_values) / Decimal(len(implied_values))
                        )

                    total_market_probability = sum(
                        implied_by_selection.values()
                    )

                    for selection_name, rows in selections.items():
                        prices = [row["price"] for row in rows]
                        average_price = (
                            sum(Decimal(price) for price in prices)
                            / Decimal(len(prices))
                        )
                        best_price = max(prices)
                        sportsbook_count = len(
                            {row["sportsbook_id"] for row in rows}
                        )

                        for row in rows:
                            implied_probability = (
                                american_to_implied_probability(
                                    row["price"]
                                )
                            )

                            no_vig_probability = None

                            if total_market_probability > 0:
                                no_vig_probability = (
                                    implied_by_selection[selection_name]
                                    / total_market_probability
                                )

                            analysis_rows.append(
                                (
                                    row["snapshot_id"],
                                    implied_probability,
                                    no_vig_probability,
                                    average_price,
                                    best_price,
                                    sportsbook_count,
                                )
                            )

                cursor.executemany(
                    """
                    INSERT INTO market_analysis (
                        odds_market_snapshot_id,
                        implied_probability,
                        no_vig_probability,
                        market_average_price,
                        market_best_price,
                        sportsbook_count
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (odds_market_snapshot_id)
                    DO UPDATE SET
                        implied_probability =
                            EXCLUDED.implied_probability,
                        no_vig_probability =
                            EXCLUDED.no_vig_probability,
                        market_average_price =
                            EXCLUDED.market_average_price,
                        market_best_price =
                            EXCLUDED.market_best_price,
                        sportsbook_count =
                            EXCLUDED.sportsbook_count,
                        created_at = CURRENT_TIMESTAMP;
                    """,
                    analysis_rows,
                )

    finally:
        connection.close()

    print(f"Market analysis rows processed: {len(analysis_rows)}")