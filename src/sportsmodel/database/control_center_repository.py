from collections.abc import Callable
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.models.system_health_summary import (
    SystemHealthSummary,
)


ConnectionFactory = Callable[[], Any]


def get_system_health_summary(
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> SystemHealthSummary:
    """
    Return current read-only health metrics for SportsModel.
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM games;
                """
            )
            canonical_games_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    MAX(game_date)
                FROM historical_games
                WHERE game_id IS NOT NULL
                  AND home_score IS NOT NULL
                  AND away_score IS NOT NULL;
                """
            )
            (
                completed_games_count,
                latest_completed_game_date,
            ) = cursor.fetchone()

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT game_id
                    FROM team_game_statistics
                    GROUP BY game_id
                    HAVING COUNT(*) = 2
                       AND COUNT(*) FILTER (
                           WHERE is_home = TRUE
                       ) = 1
                       AND COUNT(*) FILTER (
                           WHERE is_home = FALSE
                       ) = 1
                ) AS complete_team_statistics;
                """
            )
            (
                games_with_complete_team_statistics_count
            ) = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(DISTINCT game_id)
                FROM player_game_pitching_statistics;
                """
            )
            games_with_pitching_statistics_count = (
                cursor.fetchone()[0]
            )

            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    MAX(snapshot_time)
                FROM odds_market_snapshots;
                """
            )
            (
                odds_snapshot_count,
                latest_odds_snapshot_time,
            ) = cursor.fetchone()

            cursor.execute(
                """
                SELECT
                    status,
                    started_at,
                    completed_at,
                    error_message
                FROM odds_ingestion_runs
                ORDER BY odds_ingestion_run_id DESC
                LIMIT 1;
                """
            )
            latest_odds_run = cursor.fetchone()

        if latest_odds_run is None:
            latest_odds_run_status = None
            latest_odds_run_started_at = None
            latest_odds_run_completed_at = None
            latest_odds_run_error_message = None
        else:
            (
                latest_odds_run_status,
                latest_odds_run_started_at,
                latest_odds_run_completed_at,
                latest_odds_run_error_message,
            ) = latest_odds_run

        return SystemHealthSummary(
            canonical_games_count=canonical_games_count,
            completed_games_count=completed_games_count,
            latest_completed_game_date=(
                latest_completed_game_date
            ),
            games_with_complete_team_statistics_count=(
                games_with_complete_team_statistics_count
            ),
            games_with_pitching_statistics_count=(
                games_with_pitching_statistics_count
            ),
            odds_snapshot_count=odds_snapshot_count,
            latest_odds_snapshot_time=(
                latest_odds_snapshot_time
            ),
            latest_odds_run_status=(
                latest_odds_run_status
            ),
            latest_odds_run_started_at=(
                latest_odds_run_started_at
            ),
            latest_odds_run_completed_at=(
                latest_odds_run_completed_at
            ),
            latest_odds_run_error_message=(
                latest_odds_run_error_message
            ),
        )

    finally:
        connection.close()
