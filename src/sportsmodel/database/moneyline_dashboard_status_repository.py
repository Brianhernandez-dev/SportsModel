from collections.abc import Callable
from typing import Any

from sportsmodel.database.connection import (
    get_connection,
)
from sportsmodel.models.moneyline_dashboard_status import (
    MoneylineRunTiming,
)


ConnectionFactory = Callable[[], Any]


def get_moneyline_run_timing(
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    connection_factory: ConnectionFactory = get_connection,
) -> MoneylineRunTiming:
    """
    Load authoritative persisted timing for one dashboard card.
    """

    if prediction_run_id <= 0:
        raise ValueError(
            "Prediction run ID must be positive."
        )

    if odds_ingestion_run_id <= 0:
        raise ValueError(
            "Odds ingestion run ID must be positive."
        )

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    prediction_run.completed_at,
                    odds_run.completed_at,
                    odds_run.snapshot_role,
                    (
                        SELECT MAX(
                            snapshot.snapshot_time
                        )
                        FROM odds_market_snapshots
                            AS snapshot
                        WHERE
                            snapshot.odds_ingestion_run_id =
                            odds_run.odds_ingestion_run_id
                    )
                FROM moneyline_prediction_runs
                    AS prediction_run
                CROSS JOIN odds_ingestion_runs
                    AS odds_run
                WHERE
                    prediction_run
                    .moneyline_prediction_run_id = %s
                    AND odds_run
                    .odds_ingestion_run_id = %s;
                """,
                (
                    prediction_run_id,
                    odds_ingestion_run_id,
                ),
            )

            row = cursor.fetchone()

        if row is None:
            raise LookupError(
                "Prediction/odds run timing was not found."
            )

        return MoneylineRunTiming(
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=(
                odds_ingestion_run_id
            ),
            prediction_completed_at=row[0],
            odds_completed_at=row[1],
            snapshot_role=row[2],
            market_snapshot_time=row[3],
        )

    finally:
        connection.close()
