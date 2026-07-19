from collections.abc import Callable
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.models.baseball_player import BaseballPlayer
from sportsmodel.models.baseball_player_source import BaseballPlayerSource


ConnectionFactory = Callable[[], Any]


def _row_to_baseball_player(row: tuple[Any, ...]) -> BaseballPlayer:
    return BaseballPlayer(
        baseball_player_id=row[0],
        full_name=row[1],
        bats=row[2],
        throws=row[3],
        primary_position=row[4],
        active_from=row[5],
        active_through=row[6],
        is_active=row[7],
        last_synced_at=row[8],
        created_at=row[9],
        updated_at=row[10],
    )


def _row_to_baseball_player_source(
    row: tuple[Any, ...],
) -> BaseballPlayerSource:
    return BaseballPlayerSource(
        baseball_player_source_id=row[0],
        baseball_player_id=row[1],
        source_name=row[2],
        external_player_id=row[3],
        created_at=row[4],
    )


def create_baseball_player(
    player: BaseballPlayer,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BaseballPlayer:
    """
    Insert and return a canonical baseball player.
    """

    query = """
        INSERT INTO baseball_players (
            full_name,
            bats,
            throws,
            primary_position,
            active_from,
            active_through,
            is_active,
            last_synced_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING
            baseball_player_id,
            full_name,
            bats,
            throws,
            primary_position,
            active_from,
            active_through,
            is_active,
            last_synced_at,
            created_at,
            updated_at;
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    player.full_name,
                    player.bats,
                    player.throws,
                    player.primary_position,
                    player.active_from,
                    player.active_through,
                    player.is_active,
                    player.last_synced_at,
                ),
            )
            row = cursor.fetchone()

        connection.commit()

        if row is None:
            raise RuntimeError("Baseball player insert returned no row.")

        return _row_to_baseball_player(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def update_baseball_player(
    player: BaseballPlayer,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BaseballPlayer:
    """
    Update and return an existing canonical baseball player.
    """

    if player.baseball_player_id is None:
        raise ValueError(
            "baseball_player_id is required when updating a player."
        )

    query = """
        UPDATE baseball_players
        SET
            full_name = %s,
            bats = %s,
            throws = %s,
            primary_position = %s,
            active_from = %s,
            active_through = %s,
            is_active = %s,
            last_synced_at = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE baseball_player_id = %s
        RETURNING
            baseball_player_id,
            full_name,
            bats,
            throws,
            primary_position,
            active_from,
            active_through,
            is_active,
            last_synced_at,
            created_at,
            updated_at;
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    player.full_name,
                    player.bats,
                    player.throws,
                    player.primary_position,
                    player.active_from,
                    player.active_through,
                    player.is_active,
                    player.last_synced_at,
                    player.baseball_player_id,
                ),
            )
            row = cursor.fetchone()

        if row is None:
            raise LookupError(
                "Baseball player does not exist: "
                f"{player.baseball_player_id}"
            )

        connection.commit()

        return _row_to_baseball_player(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_baseball_player_by_id(
    baseball_player_id: int,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BaseballPlayer | None:
    """
    Return a canonical baseball player by internal ID.
    """

    query = """
        SELECT
            baseball_player_id,
            full_name,
            bats,
            throws,
            primary_position,
            active_from,
            active_through,
            is_active,
            last_synced_at,
            created_at,
            updated_at
        FROM baseball_players
        WHERE baseball_player_id = %s;
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(query, (baseball_player_id,))
            row = cursor.fetchone()

        if row is None:
            return None

        return _row_to_baseball_player(row)

    finally:
        connection.close()


def get_baseball_player_by_source(
    source_name: str,
    external_player_id: str,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BaseballPlayer | None:
    """
    Return a canonical player using an external source identifier.
    """

    query = """
        SELECT
            bp.baseball_player_id,
            bp.full_name,
            bp.bats,
            bp.throws,
            bp.primary_position,
            bp.active_from,
            bp.active_through,
            bp.is_active,
            bp.last_synced_at,
            bp.created_at,
            bp.updated_at
        FROM baseball_players bp
        JOIN baseball_player_sources bps
            ON bps.baseball_player_id = bp.baseball_player_id
        WHERE bps.source_name = %s
          AND bps.external_player_id = %s;
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    source_name,
                    str(external_player_id),
                ),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return _row_to_baseball_player(row)

    finally:
        connection.close()


def add_baseball_player_source(
    source: BaseballPlayerSource,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BaseballPlayerSource:
    """
    Add and return an external identifier for a canonical player.
    """

    query = """
        INSERT INTO baseball_player_sources (
            baseball_player_id,
            source_name,
            external_player_id
        )
        VALUES (%s, %s, %s)
        RETURNING
            baseball_player_source_id,
            baseball_player_id,
            source_name,
            external_player_id,
            created_at;
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    source.baseball_player_id,
                    source.source_name,
                    str(source.external_player_id),
                ),
            )
            row = cursor.fetchone()

        connection.commit()

        if row is None:
            raise RuntimeError("Baseball player source insert returned no row.")

        return _row_to_baseball_player_source(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()