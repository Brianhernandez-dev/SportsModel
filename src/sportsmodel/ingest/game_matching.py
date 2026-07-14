from datetime import datetime, timedelta


DEFAULT_GAME_TIME_TOLERANCE = timedelta(minutes=15)


def get_or_create_canonical_game(
    cursor,
    *,
    source_name: str,
    external_game_id: str,
    game_datetime: datetime,
    home_team_id: int,
    away_team_id: int,
    tolerance: timedelta = DEFAULT_GAME_TIME_TOLERANCE,
) -> int:
    """
    Return the canonical game ID for an external event.

    Matching order:

    1. Existing source mapping.
    2. Same home team and away team within the configured time window.
    3. Create a new canonical game.

    The team orientation must match exactly. Reversed home and away teams
    are not treated as the same game.
    """

    external_game_id = str(external_game_id)

    cursor.execute(
        """
        SELECT game_id
        FROM game_sources
        WHERE source_name = %s
          AND external_game_id = %s;
        """,
        (
            source_name,
            external_game_id,
        ),
    )

    existing_source = cursor.fetchone()

    if existing_source is not None:
        return existing_source[0]

    window_start = game_datetime - tolerance
    window_end = game_datetime + tolerance

    cursor.execute(
        """
        SELECT game_id
        FROM games
        WHERE home_team_id = %s
          AND away_team_id = %s
          AND game_date BETWEEN %s AND %s
        ORDER BY
            ABS(
                EXTRACT(
                    EPOCH FROM (game_date - %s)
                )
            ),
            game_id
        LIMIT 1;
        """,
        (
            home_team_id,
            away_team_id,
            window_start,
            window_end,
            game_datetime,
        ),
    )

    existing_game = cursor.fetchone()

    if existing_game is not None:
        game_id = existing_game[0]
    else:
        cursor.execute(
            """
            INSERT INTO games (
                game_date,
                home_team_id,
                away_team_id
            )
            VALUES (%s, %s, %s)
            RETURNING game_id;
            """,
            (
                game_datetime,
                home_team_id,
                away_team_id,
            ),
        )

        game_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO game_sources (
            game_id,
            source_name,
            external_game_id
        )
        VALUES (%s, %s, %s)
        ON CONFLICT (
            source_name,
            external_game_id
        ) DO NOTHING;
        """,
        (
            game_id,
            source_name,
            external_game_id,
        ),
    )

    return game_id