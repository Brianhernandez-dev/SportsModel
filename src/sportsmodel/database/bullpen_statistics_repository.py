from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.models.historical_bullpen_appearance import (
    HistoricalBullpenAppearance,
)
from sportsmodel.models.player_game_pitching_statistics import (
    PitchingDecision,
    PlayerGamePitchingStatistics,
)


ConnectionFactory = Callable[[], Any]


GET_COMPLETED_RELIEF_APPEARANCES_BEFORE_QUERY = """
    SELECT
        g.game_id,
        g.game_date,
        pgps.team_id,
        CASE
            WHEN g.home_team_id = pgps.team_id
                THEN g.away_team_id
            ELSE g.home_team_id
        END AS opponent_team_id,
        CASE
            WHEN g.home_team_id = pgps.team_id
                THEN TRUE
            ELSE FALSE
        END AS is_home,
        pgps.baseball_player_id,
        pgps.appearance_order,
        pgps.is_starter,
        pgps.pitching_outs,
        pgps.batters_faced,
        pgps.hits_allowed,
        pgps.runs_allowed,
        pgps.earned_runs_allowed,
        pgps.home_runs_allowed,
        pgps.walks_allowed,
        pgps.intentional_walks_allowed,
        pgps.strikeouts,
        pgps.hit_batters,
        pgps.pitches_thrown,
        pgps.strikes_thrown,
        pgps.decision,
        pgps.save_recorded,
        pgps.hold_recorded,
        pgps.blown_save_recorded,
        pgps.source_name
    FROM player_game_pitching_statistics AS pgps
    JOIN games AS g
        ON g.game_id = pgps.game_id
    WHERE pgps.team_id = %s
      AND pgps.is_starter = FALSE
      AND g.game_date < %s
      AND EXTRACT(YEAR FROM g.game_date) = (
          EXTRACT(YEAR FROM %s::timestamptz)
      )
      AND (
          g.home_team_id = pgps.team_id
          OR g.away_team_id = pgps.team_id
      )
      AND g.home_team_id IS NOT NULL
      AND g.away_team_id IS NOT NULL
    ORDER BY
        g.game_date DESC,
        g.game_id DESC,
        pgps.appearance_order ASC,
        pgps.baseball_player_id ASC;
"""


class BullpenStatisticsRepository(ABC):
    """
    Read-only repository for point-in-time bullpen appearances.
    """

    @abstractmethod
    def get_completed_relief_appearances_before(
        self,
        *,
        team_id: int,
        cutoff_time: datetime,
    ) -> tuple[HistoricalBullpenAppearance, ...]:
        """
        Return same-season relief appearances before the cutoff.

        Results are ordered newest game first.
        """


class PostgresBullpenStatisticsRepository(
    BullpenStatisticsRepository,
):
    """
    PostgreSQL implementation of the bullpen-statistics repository.
    """

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory = get_connection,
    ) -> None:
        self._connection_factory = connection_factory

    def get_completed_relief_appearances_before(
        self,
        *,
        team_id: int,
        cutoff_time: datetime,
    ) -> tuple[HistoricalBullpenAppearance, ...]:
        _validate_positive_identifier(
            value=team_id,
            field_name="Team ID",
        )
        _validate_cutoff_time(cutoff_time)

        connection = self._connection_factory()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    GET_COMPLETED_RELIEF_APPEARANCES_BEFORE_QUERY,
                    (
                        team_id,
                        cutoff_time,
                        cutoff_time,
                    ),
                )

                rows = cursor.fetchall()

            return tuple(
                _map_historical_bullpen_appearance(row)
                for row in rows
            )

        finally:
            connection.close()


def _map_historical_bullpen_appearance(
    row: tuple[Any, ...],
) -> HistoricalBullpenAppearance:
    decision = (
        PitchingDecision(row[20])
        if row[20] is not None
        else None
    )

    statistics = PlayerGamePitchingStatistics(
        game_id=row[0],
        team_id=row[2],
        baseball_player_id=row[5],
        appearance_order=row[6],
        is_starter=row[7],
        pitching_outs=row[8],
        batters_faced=row[9],
        hits_allowed=row[10],
        runs_allowed=row[11],
        earned_runs_allowed=row[12],
        home_runs_allowed=row[13],
        walks_allowed=row[14],
        intentional_walks_allowed=row[15],
        strikeouts=row[16],
        hit_batters=row[17],
        pitches_thrown=row[18],
        strikes_thrown=row[19],
        decision=decision,
        save_recorded=row[21],
        hold_recorded=row[22],
        blown_save_recorded=row[23],
        source_name=row[24],
    )

    return HistoricalBullpenAppearance(
        game_id=row[0],
        game_start_time=row[1],
        team_id=row[2],
        opponent_team_id=row[3],
        is_home=row[4],
        statistics=statistics,
    )


def _validate_positive_identifier(
    *,
    value: int,
    field_name: str,
) -> None:
    if value <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero."
        )


def _validate_cutoff_time(
    cutoff_time: datetime,
) -> None:
    if (
        cutoff_time.tzinfo is None
        or cutoff_time.utcoffset() is None
    ):
        raise ValueError(
            "Cutoff time must be timezone-aware."
        )
