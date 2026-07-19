from collections.abc import Callable
from datetime import date
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.models.baseball_player_team_assignment import (
    BaseballPlayerTeamAssignment,
)
from sportsmodel.models.baseball_team_source import BaseballTeamSource


ConnectionFactory = Callable[[], Any]


def _row_to_baseball_team_source(
    row: tuple[Any, ...],
) -> BaseballTeamSource:
    return BaseballTeamSource(
        baseball_team_source_id=row[0],
        team_id=row[1],
        source_name=row[2],
        external_team_id=row[3],
        created_at=row[4],
    )


def _row_to_player_team_assignment(
    row: tuple[Any, ...],
) -> BaseballPlayerTeamAssignment:
    return BaseballPlayerTeamAssignment(
        baseball_player_team_assignment_id=row[0],
        baseball_player_id=row[1],
        team_id=row[2],
        roster_status_code=row[3],
        roster_status_description=row[4],
        jersey_number=row[5],
        position_code=row[6],
        position_name=row[7],
        valid_from=row[8],
        valid_through=row[9],
        is_current=row[10],
        last_synced_at=row[11],
        created_at=row[12],
        updated_at=row[13],
    )


def add_baseball_team_source(
    source: BaseballTeamSource,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BaseballTeamSource:
    """
    Add and return an external identifier for a canonical team.
    """

    query = """
        INSERT INTO baseball_team_sources (
            team_id,
            source_name,
            external_team_id
        )
        VALUES (%s, %s, %s)
        ON CONFLICT (source_name, external_team_id)
        DO UPDATE SET
            team_id = EXCLUDED.team_id
        RETURNING
            baseball_team_source_id,
            team_id,
            source_name,
            external_team_id,
            created_at;
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    source.team_id,
                    source.source_name,
                    str(source.external_team_id),
                ),
            )
            row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "Baseball team source insert returned no row."
            )

        connection.commit()

        return _row_to_baseball_team_source(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_team_id_by_source(
    source_name: str,
    external_team_id: str,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> int | None:
    """
    Return the canonical team ID for an external team identifier.
    """

    query = """
        SELECT team_id
        FROM baseball_team_sources
        WHERE source_name = %s
          AND external_team_id = %s;
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    source_name,
                    str(external_team_id),
                ),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return row[0]

    finally:
        connection.close()


def get_team_id_by_name(
    team_name: str,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> int | None:
    """
    Return the canonical team ID for an exact team name.
    """

    query = """
        SELECT team_id
        FROM teams
        WHERE team_name = %s;
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(query, (team_name,))
            row = cursor.fetchone()

        if row is None:
            return None

        return row[0]

    finally:
        connection.close()


def get_current_player_team_assignment(
    baseball_player_id: int,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BaseballPlayerTeamAssignment | None:
    """
    Return the current team assignment for a player.
    """

    query = """
        SELECT
            baseball_player_team_assignment_id,
            baseball_player_id,
            team_id,
            roster_status_code,
            roster_status_description,
            jersey_number,
            position_code,
            position_name,
            valid_from,
            valid_through,
            is_current,
            last_synced_at,
            created_at,
            updated_at
        FROM baseball_player_team_assignments
        WHERE baseball_player_id = %s
          AND is_current = TRUE;
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(query, (baseball_player_id,))
            row = cursor.fetchone()

        if row is None:
            return None

        return _row_to_player_team_assignment(row)

    finally:
        connection.close()


def create_player_team_assignment(
    assignment: BaseballPlayerTeamAssignment,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BaseballPlayerTeamAssignment:
    """
    Create and return a player-team assignment.
    """

    query = """
        INSERT INTO baseball_player_team_assignments (
            baseball_player_id,
            team_id,
            roster_status_code,
            roster_status_description,
            jersey_number,
            position_code,
            position_name,
            valid_from,
            valid_through,
            is_current,
            last_synced_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            COALESCE(%s, CURRENT_DATE),
            %s,
            %s,
            COALESCE(%s, CURRENT_TIMESTAMP)
        )
        RETURNING
            baseball_player_team_assignment_id,
            baseball_player_id,
            team_id,
            roster_status_code,
            roster_status_description,
            jersey_number,
            position_code,
            position_name,
            valid_from,
            valid_through,
            is_current,
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
                    assignment.baseball_player_id,
                    assignment.team_id,
                    assignment.roster_status_code,
                    assignment.roster_status_description,
                    assignment.jersey_number,
                    assignment.position_code,
                    assignment.position_name,
                    assignment.valid_from,
                    assignment.valid_through,
                    assignment.is_current,
                    assignment.last_synced_at,
                ),
            )
            row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "Player-team assignment insert returned no row."
            )

        connection.commit()

        return _row_to_player_team_assignment(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def update_current_player_team_assignment(
    assignment: BaseballPlayerTeamAssignment,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BaseballPlayerTeamAssignment:
    """
    Update the mutable details of a current player-team assignment.
    """

    if assignment.baseball_player_team_assignment_id is None:
        raise ValueError(
            "baseball_player_team_assignment_id is required "
            "when updating an assignment."
        )

    query = """
        UPDATE baseball_player_team_assignments
        SET
            roster_status_code = %s,
            roster_status_description = %s,
            jersey_number = %s,
            position_code = %s,
            position_name = %s,
            last_synced_at = COALESCE(%s, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE baseball_player_team_assignment_id = %s
          AND is_current = TRUE
        RETURNING
            baseball_player_team_assignment_id,
            baseball_player_id,
            team_id,
            roster_status_code,
            roster_status_description,
            jersey_number,
            position_code,
            position_name,
            valid_from,
            valid_through,
            is_current,
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
                    assignment.roster_status_code,
                    assignment.roster_status_description,
                    assignment.jersey_number,
                    assignment.position_code,
                    assignment.position_name,
                    assignment.last_synced_at,
                    assignment.baseball_player_team_assignment_id,
                ),
            )
            row = cursor.fetchone()

        if row is None:
            raise LookupError(
                "Current player-team assignment does not exist: "
                f"{assignment.baseball_player_team_assignment_id}"
            )

        connection.commit()

        return _row_to_player_team_assignment(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def close_current_player_team_assignment(
    baseball_player_id: int,
    valid_through: date,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> BaseballPlayerTeamAssignment | None:
    """
    Close and return a player's current team assignment.
    """

    query = """
        UPDATE baseball_player_team_assignments
        SET
            valid_through = %s,
            is_current = FALSE,
            updated_at = CURRENT_TIMESTAMP
        WHERE baseball_player_id = %s
          AND is_current = TRUE
        RETURNING
            baseball_player_team_assignment_id,
            baseball_player_id,
            team_id,
            roster_status_code,
            roster_status_description,
            jersey_number,
            position_code,
            position_name,
            valid_from,
            valid_through,
            is_current,
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
                    valid_through,
                    baseball_player_id,
                ),
            )
            row = cursor.fetchone()

        connection.commit()

        if row is None:
            return None

        return _row_to_player_team_assignment(row)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()