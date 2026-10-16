from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.database.mlb_canonical_time_repository import CertifiedReader, reject_uncertified036
from sportsmodel.database.mlb_operator_guard import aware
from sportsmodel.orchestration.odds_snapshot_schedule import (
    PACIFIC_TIME_ZONE,
)


ConnectionFactory = Callable[[], Any]

MLB_GAME_SOURCE_NAME = "mlb_stats"

GET_EARLIEST_MLB_GAME_START_QUERY = """
    SELECT MIN(game.game_date)
    FROM games AS game
    JOIN game_sources AS source
      ON source.game_id = game.game_id
    WHERE source.source_name = %s
      AND NOT mlb_identity_is_retired(game.game_id)
      AND game.game_date >= %s
      AND game.game_date < %s
      AND game.home_team_id IS NOT NULL
      AND game.away_team_id IS NOT NULL;
"""


def get_earliest_mlb_game_start_for_pacific_date(
    target_date: date,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> datetime | None:
    """Read the earliest canonical MLB start for one Pacific slate."""

    start_time = datetime.combine(
        target_date,
        time.min,
        tzinfo=PACIFIC_TIME_ZONE,
    ).astimezone(timezone.utc)
    end_time = datetime.combine(
        target_date + timedelta(days=1),
        time.min,
        tzinfo=PACIFIC_TIME_ZONE,
    ).astimezone(timezone.utc)

    if isinstance(connection_factory, CertifiedReader):
        rows = connection_factory.rows('earliest_start', start=start_time.isoformat(), end=end_time.isoformat())
        return min((aware(row['game_date']) for row in rows), default=None)

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            reject_uncertified036(cursor)
            cursor.execute(
                GET_EARLIEST_MLB_GAME_START_QUERY,
                (
                    MLB_GAME_SOURCE_NAME,
                    start_time,
                    end_time,
                ),
            )
            row = cursor.fetchone()
    finally:
        connection.close()

    earliest_start = row[0] if row is not None else None

    if earliest_start is None:
        return None
    if not isinstance(earliest_start, datetime):
        raise TypeError(
            "Canonical MLB game start must be a datetime."
        )
    if earliest_start.tzinfo is None:
        raise ValueError(
            "Canonical MLB game start must be timezone-aware."
        )

    return earliest_start
