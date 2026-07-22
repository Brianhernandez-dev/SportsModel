from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.models.baseball_game import BaseballGame
from sportsmodel.models.completed_game import CompletedGame


ConnectionFactory = Callable[[], Any]


GET_COMPLETED_GAMES_QUERY = """
    SELECT
        g.game_id,
        g.game_date,
        g.home_team_id,
        g.away_team_id,
        hg.home_score,
        hg.away_score
    FROM games AS g
    JOIN historical_games AS hg
        ON hg.game_id = g.game_id
    WHERE g.home_team_id IS NOT NULL
      AND g.away_team_id IS NOT NULL
      AND hg.home_score IS NOT NULL
      AND hg.away_score IS NOT NULL
    ORDER BY
        g.game_date ASC,
        g.game_id ASC;
"""


class CompletedGameRepository(ABC):
    """
    Read-only repository contract for completed canonical games.
    """

    @abstractmethod
    def get_all(self) -> list[CompletedGame]:
        """
        Return completed canonical games ordered chronologically.
        """


class PostgresCompletedGameRepository(
    CompletedGameRepository,
):
    """
    PostgreSQL implementation of the completed-game repository.
    """

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory = get_connection,
    ) -> None:
        self._connection_factory = connection_factory

    def get_all(self) -> list[CompletedGame]:
        connection = self._connection_factory()

        try:
            with connection.cursor() as cursor:
                cursor.execute(GET_COMPLETED_GAMES_QUERY)
                rows = cursor.fetchall()

            return [
                _map_completed_game(row)
                for row in rows
            ]

        finally:
            connection.close()


def _map_completed_game(
    row: tuple[Any, ...],
) -> CompletedGame:
    game = BaseballGame(
        game_id=row[0],
        game_start_time=row[1],
        home_team_id=row[2],
        away_team_id=row[3],
    )

    return CompletedGame(
        game=game,
        home_score=row[4],
        away_score=row[5],
    )
