from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sportsmodel.database.connection import get_connection


ConnectionFactory = Callable[[], Any]


COMPLETE_BOX_SCORE_GAME_IDS_QUERY = """
    SELECT requested.game_id
    FROM unnest(%s::integer[]) AS requested(game_id)
    WHERE
        EXISTS (
            SELECT 1
            FROM games
            WHERE game_id = requested.game_id
        )
        AND (
            SELECT COUNT(*)
            FROM team_game_statistics
            WHERE game_id = requested.game_id
        ) = 2
        AND (
            SELECT COUNT(*)
            FROM player_game_pitching_statistics
            WHERE
                game_id = requested.game_id
                AND is_starter IS TRUE
        ) = 2;
"""


BOX_SCORE_COMPLETENESS_QUERY = """
    SELECT
        EXISTS (
            SELECT 1
            FROM games
            WHERE game_id = %s
        ) AS game_exists,
        (
            SELECT COUNT(*)
            FROM team_game_statistics
            WHERE game_id = %s
        ) AS team_statistics_count,
        (
            SELECT COUNT(*)
            FROM player_game_pitching_statistics
            WHERE
                game_id = %s
                AND is_starter IS TRUE
        ) AS starting_pitcher_count;
"""


@dataclass(frozen=True)
class BoxScoreCompleteness:
    """
    Persisted box-score coverage for one canonical game.
    """

    game_id: int

    game_exists: bool

    team_statistics_count: int

    starting_pitcher_count: int

    @property
    def is_complete(self) -> bool:
        """
        Return whether all minimum box-score components exist.
        """

        return (
            self.game_exists
            and self.team_statistics_count == 2
            and self.starting_pitcher_count == 2
        )


def get_complete_box_score_game_ids(
    game_ids: Iterable[int],
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> frozenset[int]:
    """
    Return canonical game IDs with complete persisted box scores.

    The check is performed in one database query so a historical
    schedule date does not require a separate connection per game.
    """

    unique_game_ids = tuple(
        dict.fromkeys(game_ids)
    )

    if not unique_game_ids:
        return frozenset()

    if any(game_id <= 0 for game_id in unique_game_ids):
        raise ValueError(
            "Game IDs must be greater than zero."
        )

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                COMPLETE_BOX_SCORE_GAME_IDS_QUERY,
                (
                    list(unique_game_ids),
                ),
            )

            rows = cursor.fetchall()

        return frozenset(
            int(row[0])
            for row in rows
        )

    finally:
        connection.close()


def get_box_score_completeness(
    game_id: int,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BoxScoreCompleteness:
    """
    Read persisted box-score completeness for one canonical game.
    """

    if game_id <= 0:
        raise ValueError(
            "Game ID must be greater than zero."
        )

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                BOX_SCORE_COMPLETENESS_QUERY,
                (
                    game_id,
                    game_id,
                    game_id,
                ),
            )

            row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "Box-score completeness query returned no result."
            )

        return BoxScoreCompleteness(
            game_id=game_id,
            game_exists=bool(row[0]),
            team_statistics_count=int(row[1]),
            starting_pitcher_count=int(row[2]),
        )

    finally:
        connection.close()


def is_box_score_complete(
    game_id: int,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> bool:
    """
    Return whether one game's complete box score is already stored.
    """

    return get_box_score_completeness(
        game_id,
        connection_factory=connection_factory,
    ).is_complete
