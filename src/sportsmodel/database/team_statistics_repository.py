from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.models.historical_team_game import (
    HistoricalTeamGame,
)
from sportsmodel.models.team_game_statistics import (
    TeamGameStatistics,
)


ConnectionFactory = Callable[[], Any]


GET_COMPLETED_GAMES_BEFORE_QUERY = """
    SELECT
        g.game_id,
        g.game_date,
        tgs.team_id,
        CASE
            WHEN g.home_team_id = tgs.team_id
                THEN g.away_team_id
            ELSE g.home_team_id
        END AS opponent_team_id,
        tgs.is_home,
        tgs.runs,
        tgs.hits,
        tgs.errors,
        tgs.at_bats,
        tgs.plate_appearances,
        tgs.doubles,
        tgs.triples,
        tgs.home_runs,
        tgs.walks,
        tgs.intentional_walks,
        tgs.strikeouts,
        tgs.hit_by_pitch,
        tgs.sacrifice_flies,
        tgs.stolen_bases,
        tgs.caught_stealing,
        tgs.pitching_outs,
        tgs.runs_allowed,
        tgs.earned_runs_allowed,
        tgs.hits_allowed,
        tgs.home_runs_allowed,
        tgs.walks_allowed,
        tgs.strikeouts_recorded,
        tgs.left_on_base,
        tgs.double_plays,
        tgs.source_name
    FROM team_game_statistics tgs
    JOIN games g
        ON g.game_id = tgs.game_id
    WHERE tgs.team_id = %s
      AND g.game_date < %s
      AND (
            g.home_team_id = tgs.team_id
            OR g.away_team_id = tgs.team_id
      )
      AND g.home_team_id IS NOT NULL
      AND g.away_team_id IS NOT NULL
    ORDER BY
        g.game_date DESC,
        g.game_id DESC
    LIMIT %s;
"""


class TeamStatisticsRepository(ABC):
    """
    Read-only repository contract for historical team statistics.

    All returned data must respect the caller-supplied point-in-time
    cutoff.
    """

    @abstractmethod
    def get_completed_games_before(
        self,
        *,
        team_id: int,
        cutoff_time: datetime,
        limit: int,
    ) -> tuple[HistoricalTeamGame, ...]:
        """
        Return completed games before the cutoff, newest first.
        """


class PostgresTeamStatisticsRepository(
    TeamStatisticsRepository,
):
    """
    PostgreSQL implementation of the historical team-statistics
    repository.
    """

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory = get_connection,
    ) -> None:
        self._connection_factory = connection_factory

    def get_completed_games_before(
        self,
        *,
        team_id: int,
        cutoff_time: datetime,
        limit: int,
    ) -> tuple[HistoricalTeamGame, ...]:
        """
        Return a team's completed games strictly before the cutoff.

        The presence of a team_game_statistics record represents a
        completed game with final box-score statistics.
        """

        _validate_positive_identifier(
            value=team_id,
            field_name="Team ID",
        )
        _validate_cutoff_time(cutoff_time)
        _validate_limit(limit)

        connection = self._connection_factory()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    GET_COMPLETED_GAMES_BEFORE_QUERY,
                    (
                        team_id,
                        cutoff_time,
                        limit,
                    ),
                )

                rows = cursor.fetchall()

            return tuple(
                _map_historical_team_game(row)
                for row in rows
            )

        finally:
            connection.close()


def _map_historical_team_game(
    row: tuple[Any, ...],
) -> HistoricalTeamGame:
    statistics = TeamGameStatistics(
        game_id=row[0],
        team_id=row[2],
        is_home=row[4],
        runs=row[5],
        hits=row[6],
        errors=row[7],
        at_bats=row[8],
        plate_appearances=row[9],
        doubles=row[10],
        triples=row[11],
        home_runs=row[12],
        walks=row[13],
        intentional_walks=row[14],
        strikeouts=row[15],
        hit_by_pitch=row[16],
        sacrifice_flies=row[17],
        stolen_bases=row[18],
        caught_stealing=row[19],
        pitching_outs=row[20],
        runs_allowed=row[21],
        earned_runs_allowed=row[22],
        hits_allowed=row[23],
        home_runs_allowed=row[24],
        walks_allowed=row[25],
        strikeouts_recorded=row[26],
        left_on_base=row[27],
        double_plays=row[28],
        source_name=row[29],
    )

    return HistoricalTeamGame(
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
    if cutoff_time.tzinfo is None:
        raise ValueError(
            "Cutoff time must be timezone-aware."
        )


def _validate_limit(
    limit: int,
) -> None:
    if limit <= 0:
        raise ValueError(
            "Limit must be greater than zero."
        )