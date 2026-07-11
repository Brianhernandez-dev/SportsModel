from datetime import datetime, timezone
import os

import requests

from sportsmodel.database.connection import get_connection


SPORT = "baseball_mlb"
REGIONS = "us"
MARKETS = "h2h,totals"
ODDS_FORMAT = "american"
SOURCE_NAME = "odds_api"


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


def get_sportsbook_id(cursor, sportsbook_name):
    """Return a sportsbook ID, creating the sportsbook when necessary."""

    cursor.execute(
        """
        INSERT INTO sportsbooks (name)
        VALUES (%s)
        ON CONFLICT (name) DO NOTHING;
        """,
        (sportsbook_name,),
    )

    cursor.execute(
        """
        SELECT sportsbook_id
        FROM sportsbooks
        WHERE name = %s;
        """,
        (sportsbook_name,),
    )

    return cursor.fetchone()[0]


def get_or_create_game(
    cursor,
    external_game_id,
    commence_time,
    home_team_id,
    away_team_id,
):
    """
    Return the canonical game_id for an Odds API event.

    First check game_sources for an existing provider mapping. If no mapping
    exists, look for a matching canonical game before creating a new one.
    """

    cursor.execute(
        """
        SELECT game_id
        FROM game_sources
        WHERE source_name = %s
          AND external_game_id = %s;
        """,
        (SOURCE_NAME, external_game_id),
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
          AND away_team_id = %s;
        """,
        (commence_time, home_team_id, away_team_id),
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
            (commence_time, home_team_id, away_team_id),
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
        (game_id, SOURCE_NAME, external_game_id),
    )

    return game_id


def fetch_live_odds():
    """Fetch current MLB odds and store moneyline snapshots."""

    api_key = os.getenv("ODDS_API_KEY")

    if not api_key:
        raise RuntimeError("ODDS_API_KEY is missing from the environment.")

    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"

    params = {
        "apiKey": api_key,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
    }

    response = requests.get(url, params=params, timeout=30)

    print("Status Code:", response.status_code)
    print(
        "Remaining Requests:",
        response.headers.get("x-requests-remaining"),
    )
    print(
        "Used Requests:",
        response.headers.get("x-requests-used"),
    )

    if response.status_code != 200:
        print(response.text)
        raise RuntimeError("Odds API request failed.")

    games = response.json()
    snapshot_time = datetime.now(timezone.utc)
    snapshots_inserted = 0

    print(f"Games returned: {len(games)}")

    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                for game in games:
                    external_game_id = game.get("id")
                    commence_time = game.get("commence_time")
                    home_team = game.get("home_team")
                    away_team = game.get("away_team")

                    if not all(
                        [
                            external_game_id,
                            commence_time,
                            home_team,
                            away_team,
                        ]
                    ):
                        continue

                    home_team_id = get_team_id(cursor, home_team)
                    away_team_id = get_team_id(cursor, away_team)

                    game_id = get_or_create_game(
                        cursor=cursor,
                        external_game_id=external_game_id,
                        commence_time=commence_time,
                        home_team_id=home_team_id,
                        away_team_id=away_team_id,
                    )

                    for bookmaker in game.get("bookmakers", []):
                        sportsbook_name = bookmaker.get("title")

                        if not sportsbook_name:
                            continue

                        sportsbook_id = get_sportsbook_id(
                            cursor,
                            sportsbook_name,
                        )

                        for market in bookmaker.get("markets", []):
                            if market.get("key") != "h2h":
                                continue

                            home_price = None
                            away_price = None

                            for outcome in market.get("outcomes", []):
                                if outcome.get("name") == home_team:
                                    home_price = outcome.get("price")
                                elif outcome.get("name") == away_team:
                                    away_price = outcome.get("price")

                            if home_price is None or away_price is None:
                                continue

                            cursor.execute(
                                """
                                INSERT INTO odds_snapshots (
                                    game_id,
                                    sportsbook_id,
                                    market_type,
                                    home_price,
                                    away_price,
                                    snapshot_time
                                )
                                VALUES (%s, %s, %s, %s, %s, %s);
                                """,
                                (
                                    game_id,
                                    sportsbook_id,
                                    "h2h",
                                    home_price,
                                    away_price,
                                    snapshot_time,
                                ),
                            )

                            snapshots_inserted += 1

    finally:
        connection.close()

    print(f"Moneyline snapshots inserted: {snapshots_inserted}")