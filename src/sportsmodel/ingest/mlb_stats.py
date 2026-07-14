from sportsmodel.ingest.game_matching import (
    get_or_create_canonical_game,
)
from datetime import date, datetime, timedelta, timezone

import requests

from sportsmodel.database.connection import get_connection


SOURCE_NAME = "mlb_stats"
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"


def daterange(start_date, end_date):
    """Yield every calendar date from start_date through end_date."""

    current_date = start_date

    while current_date <= end_date:
        yield current_date
        current_date += timedelta(days=1)


def get_team_id(cursor, team_name):
    """Return a team ID, creating the team when necessary."""

    cursor.execute(
        """
        INSERT INTO teams (team_name)
        VALUES (%s)
        ON CONFLICT (team_name) DO NOTHING;
        """,
        (team_name,),
    )

    cursor.execute(
        """
        SELECT team_id
        FROM teams
        WHERE team_name = %s;
        """,
        (team_name,),
    )

    return cursor.fetchone()[0]


def parse_game_datetime(game):
    """Convert MLB's gameDate value into a timezone-aware datetime."""

    game_date_value = game.get("gameDate")

    if not game_date_value:
        return None

    return datetime.fromisoformat(
        game_date_value.replace("Z", "+00:00")
    ).astimezone(timezone.utc)

    """
    Return the canonical game_id for an MLB Stats API game.

    The game_sources table is checked first. If the MLB game has not been
    mapped yet, an existing canonical game with the same timestamp and teams
    is reused when available. Otherwise, a new canonical game is created.
    """

    cursor.execute(
        """
        SELECT game_id
        FROM game_sources
        WHERE source_name = %s
          AND external_game_id = %s;
        """,
        (SOURCE_NAME, str(external_game_id)),
    )

    existing_source = cursor.fetchone()

    if existing_source:
        return existing_source[0]

    cursor.execute(
        """
        SELECT game_id
        FROM games
        WHERE game_date = %s
          AND home_team_id = %s
          AND away_team_id = %s
        LIMIT 1;
        """,
        (
            game_datetime,
            home_team_id,
            away_team_id,
        ),
    )

    existing_game = cursor.fetchone()

    if existing_game:
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
        ON CONFLICT (source_name, external_game_id) DO NOTHING;
        """,
        (
            game_id,
            SOURCE_NAME,
            str(external_game_id),
        ),
    )

    return game_id


def save_historical_result(
    cursor,
    game_id,
    mlb_game_id,
    game_date,
    home_team,
    away_team,
    home_score,
    away_score,
):
    """Insert or update one finalized MLB game result."""

    home_win = home_score > away_score

    cursor.execute(
        """
        INSERT INTO historical_games (
            game_id,
            mlb_game_id,
            game_date,
            home_team,
            away_team,
            home_score,
            away_score,
            home_win
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (mlb_game_id)
        DO UPDATE SET
            game_id = EXCLUDED.game_id,
            game_date = EXCLUDED.game_date,
            home_team = EXCLUDED.home_team,
            away_team = EXCLUDED.away_team,
            home_score = EXCLUDED.home_score,
            away_score = EXCLUDED.away_score,
            home_win = EXCLUDED.home_win;
        """,
        (
            game_id,
            mlb_game_id,
            game_date,
            home_team,
            away_team,
            home_score,
            away_score,
            home_win,
        ),
    )


def fetch_historical_results(
    start_date=date(2026, 6, 1),
    end_date=None,
):
    """Fetch finalized MLB results and connect them to canonical games."""

    if end_date is None:
        end_date = date.today() - timedelta(days=1)

    connection = get_connection()

    games_processed = 0
    games_skipped = 0

    try:
        with connection:
            with connection.cursor() as cursor:
                for schedule_date in daterange(start_date, end_date):
                    response = requests.get(
                        MLB_SCHEDULE_URL,
                        params={
                            "sportId": 1,
                            "date": schedule_date.isoformat(),
                        },
                        timeout=30,
                    )

                    response.raise_for_status()
                    data = response.json()

                    for date_block in data.get("dates", []):
                        for game in date_block.get("games", []):
                            status = game.get(
                                "status",
                                {},
                            ).get("detailedState")

                            if status != "Final":
                                games_skipped += 1
                                continue

                            mlb_game_id = game.get("gamePk")
                            game_datetime = parse_game_datetime(game)

                            home_team = game["teams"]["home"]["team"]["name"]
                            away_team = game["teams"]["away"]["team"]["name"]
                            home_score = game["teams"]["home"].get("score")
                            away_score = game["teams"]["away"].get("score")

                            if (
                                mlb_game_id is None
                                or game_datetime is None
                                or home_score is None
                                or away_score is None
                            ):
                                games_skipped += 1
                                continue

                            home_team_id = get_team_id(
                                cursor,
                                home_team,
                            )
                            away_team_id = get_team_id(
                                cursor,
                                away_team,
                            )

                            game_id = get_or_create_canonical_game(
                                cursor,
                                source_name=SOURCE_NAME,
                                external_game_id=str(mlb_game_id),
                                game_datetime=game_datetime,
                                home_team_id=home_team_id,
                                away_team_id=away_team_id,
                            )

                            save_historical_result(
                                cursor=cursor,
                                game_id=game_id,
                                mlb_game_id=mlb_game_id,
                                game_date=schedule_date,
                                home_team=home_team,
                                away_team=away_team,
                                home_score=home_score,
                                away_score=away_score,
                            )

                            games_processed += 1

    finally:
        connection.close()

    print(f"Historical games processed: {games_processed}")
    print(f"Games skipped: {games_skipped}")