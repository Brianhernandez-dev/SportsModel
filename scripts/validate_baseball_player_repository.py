from datetime import datetime, timezone

from sportsmodel.database.connection import get_connection
from sportsmodel.database.player_repository import (
    add_baseball_player_source,
    create_baseball_player,
    get_baseball_player_by_id,
    get_baseball_player_by_source,
)
from sportsmodel.models.baseball_player import BaseballPlayer
from sportsmodel.models.baseball_player_source import BaseballPlayerSource


TEST_SOURCE_NAME = "repository_validation"
TEST_EXTERNAL_PLAYER_ID = "test-player-001"


def delete_validation_player() -> None:
    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM baseball_players
                WHERE baseball_player_id IN (
                    SELECT baseball_player_id
                    FROM baseball_player_sources
                    WHERE source_name = %s
                      AND external_player_id = %s
                );
                """,
                (
                    TEST_SOURCE_NAME,
                    TEST_EXTERNAL_PLAYER_ID,
                ),
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def main() -> None:
    delete_validation_player()

    synced_at = datetime.now(timezone.utc)

    created_player = create_baseball_player(
        BaseballPlayer(
            baseball_player_id=None,
            full_name="Repository Validation Player",
            bats="R",
            throws="R",
            primary_position="Pitcher",
            is_active=True,
            last_synced_at=synced_at,
        )
    )

    if created_player.baseball_player_id is None:
        raise RuntimeError("Created player did not receive an ID.")

    created_source = add_baseball_player_source(
        BaseballPlayerSource(
            baseball_player_source_id=None,
            baseball_player_id=created_player.baseball_player_id,
            source_name=TEST_SOURCE_NAME,
            external_player_id=TEST_EXTERNAL_PLAYER_ID,
        )
    )

    player_by_id = get_baseball_player_by_id(
        created_player.baseball_player_id
    )

    player_by_source = get_baseball_player_by_source(
        TEST_SOURCE_NAME,
        TEST_EXTERNAL_PLAYER_ID,
    )

    print(f"Created player ID: {created_player.baseball_player_id}")
    print(
        "Created source ID: "
        f"{created_source.baseball_player_source_id}"
    )
    print(
        "Lookup by ID: "
        f"{player_by_id.full_name if player_by_id else None}"
    )
    print(
        "Lookup by source: "
        f"{player_by_source.full_name if player_by_source else None}"
    )

    if player_by_id != created_player:
        raise RuntimeError("Lookup by canonical ID did not match.")

    if player_by_source != created_player:
        raise RuntimeError("Lookup by source did not match.")

    delete_validation_player()

    print("Validation player removed.")
    print("Baseball player repository validation passed.")


if __name__ == "__main__":
    main()