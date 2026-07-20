from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.models.baseball_game import BaseballGame


ConnectionFactory = Callable[[], Any]


GET_GAME_BY_ID_QUERY = """
    SELECT
        game_id,
        game_date,
        home_team_id,
        away_team_id
    FROM games
    WHERE game_id = %s
      AND home_team_id IS NOT NULL
      AND away_team_id IS NOT NULL;
"""


GET_NEXT_UPCOMING_GAME_QUERY = """
    SELECT
        game_id,
        game_date,
        home_team_id,
        away_team_id
    FROM games
    WHERE game_date >= %s
      AND home_team_id IS NOT NULL
      AND away_team_id IS NOT NULL
    ORDER BY
        game_date ASC,
        game_id ASC
    LIMIT 1;
"""


class GameRepository(ABC):
    """
    Read-only repository contract for canonical games.
    """

    @abstractmethod
    def get_by_id(
        self,
        *,
        game_id: int,
    ) -> BaseballGame | None:
        """
        Return one canonical game or None when it is unavailable.
        """

    @abstractmethod
    def get_next_upcoming_game(
        self,
        *,
        cutoff_time: datetime,
    ) -> BaseballGame | None:
        """
        Return the earliest game at or after the supplied cutoff.
        """


class PostgresGameRepository(GameRepository):
    """
    PostgreSQL implementation of the canonical game repository.
    """

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory = get_connection,
    ) -> None:
        self._connection_factory = connection_factory

    def get_by_id(
        self,
        *,
        game_id: int,
    ) -> BaseballGame | None:
        _validate_positive_identifier(
            value=game_id,
            field_name="Game ID",
        )

        connection = self._connection_factory()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    GET_GAME_BY_ID_QUERY,
                    (game_id,),
                )

                row = cursor.fetchone()

            if row is None:
                return None

            return _map_baseball_game(row)

        finally:
            connection.close()

    def get_next_upcoming_game(
        self,
        *,
        cutoff_time: datetime,
    ) -> BaseballGame | None:
        _validate_cutoff_time(cutoff_time)

        connection = self._connection_factory()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    GET_NEXT_UPCOMING_GAME_QUERY,
                    (cutoff_time,),
                )

                row = cursor.fetchone()

            if row is None:
                return None

            return _map_baseball_game(row)

        finally:
            connection.close()


def _map_baseball_game(
    row: tuple[Any, ...],
) -> BaseballGame:
    return BaseballGame(
        game_id=row[0],
        game_start_time=row[1],
        home_team_id=row[2],
        away_team_id=row[3],
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
