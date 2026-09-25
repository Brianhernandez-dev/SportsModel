from datetime import datetime, timedelta


DEFAULT_GAME_TIME_TOLERANCE = timedelta(minutes=15)
MLB_AUTHORITATIVE_SOURCE = "mlb_stats"
MLB_ODDS_SOURCE = "odds_api"


class CanonicalGameIdentityConflictError(ValueError):
    """Raised when source and canonical game identity evidence conflicts."""


def get_or_create_authoritative_source_game(
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
    Resolve a game whose persisted source identity is authoritative.

    A unique existing source mapping is returned after exact participant and
    orientation validation. Nearby identities from unrelated sources do not
    veto that authoritative mapping. When no mapping exists, the ordinary
    strict canonical matching and creation contract remains in force.
    """

    external_game_id = str(external_game_id)

    cursor.execute(
        """
        SELECT
            source.game_id,
            game.home_team_id,
            game.away_team_id
        FROM game_sources AS source
        JOIN games AS game
          ON game.game_id = source.game_id
        WHERE source.source_name = %s
          AND source.external_game_id = %s
        ORDER BY source.game_source_id
        LIMIT 2;
        """,
        (
            source_name,
            external_game_id,
        ),
    )

    existing_sources = cursor.fetchall()

    if len(existing_sources) > 1:
        raise CanonicalGameIdentityConflictError(
            "Multiple canonical games share the authoritative source "
            "identity: "
            f"{source_name}/{external_game_id}."
        )

    if existing_sources:
        (
            mapped_game_id,
            mapped_home_team_id,
            mapped_away_team_id,
        ) = existing_sources[0]

        if (
            mapped_home_team_id != home_team_id
            or mapped_away_team_id != away_team_id
        ):
            raise CanonicalGameIdentityConflictError(
                "Existing authoritative source mapping conflicts with the "
                "incoming home/away identity: "
                f"{source_name}/{external_game_id}."
            )

        return mapped_game_id

    return get_or_create_canonical_game(
        cursor,
        source_name=source_name,
        external_game_id=external_game_id,
        game_datetime=game_datetime,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        tolerance=tolerance,
    )


def _load_candidate_count(
    cursor,
    *,
    query: str,
    parameters: tuple,
) -> tuple[int, int | None]:
    cursor.execute(query, parameters)
    row = cursor.fetchone()

    if row is None or len(row) != 2:
        raise RuntimeError(
            "Canonical game candidate query returned an invalid result."
        )

    return row[0], row[1]


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

    1. Existing source mapping, unless it conflicts with another nearby
       canonical identity.
    2. For a new MLB Odds event, one unambiguous same-orientation,
       MLB-authoritative game within the configured time window. Retained
       Odds event IDs do not exclude this candidate.
    3. One unambiguous same-orientation game within the configured time
       window, excluding games already mapped by this source.
    4. One unambiguous same-orientation, same-Pacific-date game carrying
       retained source identity. This permits schedule drift beyond the time
       tolerance without collapsing a doubleheader.
    5. Create a new canonical game.

    The team orientation must match exactly. Reversed home and away teams
    are not treated as the same game.

    Candidate counts fail closed when more than one game qualifies. Excluding
    an existing mapping from the same source prevents distinct doubleheader
    events from sharing one canonical game ID. A unique game mapped by another
    source remains eligible for cross-source matching.
    """

    external_game_id = str(external_game_id)

    cursor.execute(
        """
        SELECT
            source.game_id,
            game.game_date,
            game.home_team_id,
            game.away_team_id
        FROM game_sources AS source
        JOIN games AS game
          ON game.game_id = source.game_id
        WHERE source.source_name = %s
          AND source.external_game_id = %s;
        """,
        (
            source_name,
            external_game_id,
        ),
    )

    existing_source = cursor.fetchone()

    if existing_source is not None:
        (
            mapped_game_id,
            _mapped_game_datetime,
            mapped_home_team_id,
            mapped_away_team_id,
        ) = existing_source

        if (
            mapped_home_team_id != home_team_id
            or mapped_away_team_id != away_team_id
        ):
            raise CanonicalGameIdentityConflictError(
                "Existing source mapping conflicts with the incoming "
                "home/away identity: "
                f"{source_name}/{external_game_id}."
            )

        conflict_count, conflicting_game_id = _load_candidate_count(
            cursor,
            query="""
                SELECT COUNT(*), MIN(candidate.game_id)
                FROM games AS candidate
                WHERE candidate.game_id <> %s
                  AND candidate.home_team_id = %s
                  AND candidate.away_team_id = %s
                  AND candidate.game_date BETWEEN %s AND %s;
            """,
            parameters=(
                mapped_game_id,
                home_team_id,
                away_team_id,
                game_datetime - tolerance,
                game_datetime + tolerance,
            ),
        )

        if conflict_count:
            raise CanonicalGameIdentityConflictError(
                "Existing source mapping conflicts with nearby canonical "
                "game identity: "
                f"{source_name}/{external_game_id} maps to "
                f"{mapped_game_id}, candidate={conflicting_game_id}, "
                f"candidate_count={conflict_count}."
            )

        return mapped_game_id

    window_start = game_datetime - tolerance
    window_end = game_datetime + tolerance

    candidate_count = 0
    game_id = None

    if source_name == MLB_ODDS_SOURCE:
        candidate_count, game_id = _load_candidate_count(
            cursor,
            query="""
                SELECT COUNT(*), MIN(candidate.game_id)
                FROM games AS candidate
                WHERE candidate.home_team_id = %s
                  AND candidate.away_team_id = %s
                  AND candidate.game_date BETWEEN %s AND %s
                  AND EXISTS (
                      SELECT 1
                      FROM game_sources AS authoritative_source
                      WHERE
                          authoritative_source.game_id = candidate.game_id
                          AND authoritative_source.source_name = %s
                  );
            """,
            parameters=(
                home_team_id,
                away_team_id,
                window_start,
                window_end,
                MLB_AUTHORITATIVE_SOURCE,
            ),
        )

        if candidate_count > 1:
            raise CanonicalGameIdentityConflictError(
                "Multiple nearby MLB-authoritative games match the incoming "
                "Odds event; identity is ambiguous: "
                f"{source_name}/{external_game_id}."
            )

    if candidate_count == 0:
        candidate_count, game_id = _load_candidate_count(
            cursor,
            query="""
                SELECT COUNT(*), MIN(candidate.game_id)
                FROM games AS candidate
                WHERE candidate.home_team_id = %s
                  AND candidate.away_team_id = %s
                  AND candidate.game_date BETWEEN %s AND %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM game_sources AS existing_mapping
                      WHERE
                          existing_mapping.game_id = candidate.game_id
                          AND existing_mapping.source_name = %s
                  );
            """,
            parameters=(
                home_team_id,
                away_team_id,
                window_start,
                window_end,
                source_name,
            ),
        )

    if candidate_count > 1:
        raise CanonicalGameIdentityConflictError(
            "Multiple nearby canonical games match the incoming source "
            "event; identity is ambiguous: "
            f"{source_name}/{external_game_id}."
        )

    if candidate_count == 0:
        candidate_count, game_id = _load_candidate_count(
            cursor,
            query="""
                SELECT COUNT(*), MIN(candidate.game_id)
                FROM games AS candidate
                WHERE candidate.home_team_id = %s
                  AND candidate.away_team_id = %s
                  AND (
                      candidate.game_date AT TIME ZONE 'America/Los_Angeles'
                  )::date = (
                      %s AT TIME ZONE 'America/Los_Angeles'
                  )::date
                  AND EXISTS (
                      SELECT 1
                      FROM game_sources AS retained_source
                      WHERE retained_source.game_id = candidate.game_id
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM game_sources AS existing_mapping
                      WHERE
                          existing_mapping.game_id = candidate.game_id
                          AND existing_mapping.source_name = %s
                  );
            """,
            parameters=(
                home_team_id,
                away_team_id,
                game_datetime,
                source_name,
            ),
        )

        if candidate_count > 1:
            raise CanonicalGameIdentityConflictError(
                "Multiple same-date canonical games match the incoming "
                "source event; doubleheader or schedule identity is "
                "ambiguous: "
                f"{source_name}/{external_game_id}."
            )

    if candidate_count == 0:
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

    if game_id is None:
        raise RuntimeError(
            "Canonical game matching selected no game identity."
        )

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
