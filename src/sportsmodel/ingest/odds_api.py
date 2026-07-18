from datetime import datetime, timezone
import os

import requests

from sportsmodel.database.connection import get_connection

from sportsmodel.ingest.game_matching import (
    get_or_create_canonical_game,
)


SPORT = "baseball_mlb"
REGIONS = "us"
MARKETS = "h2h,spreads,totals"
ODDS_FORMAT = "american"
SOURCE_NAME = "odds_api"

def parse_commence_time(value: str) -> datetime:
    """
    Convert an Odds API commence time to a timezone-aware UTC datetime.
    """

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).astimezone(timezone.utc)

def create_ingestion_run(connection):
    """Create and commit a new odds-ingestion audit record."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO odds_ingestion_runs (
                sport,
                source_name,
                status
            )
            VALUES (%s, %s, 'running')
            RETURNING odds_ingestion_run_id;
            """,
            (
                SPORT,
                SOURCE_NAME,
            ),
        )

        ingestion_run_id = cursor.fetchone()[0]

    # Commit this separately so the run remains available if ingestion fails.
    connection.commit()

    return ingestion_run_id


def mark_ingestion_run_completed(
    cursor,
    ingestion_run_id,
    games_returned,
    games_processed,
    selections_inserted,
    selections_skipped,
):
    """Mark an ingestion run as successfully completed."""

    cursor.execute(
        """
        UPDATE odds_ingestion_runs
        SET completed_at = CURRENT_TIMESTAMP,
            status = 'completed',
            games_returned = %s,
            games_processed = %s,
            selections_inserted = %s,
            selections_skipped = %s,
            error_message = NULL
        WHERE odds_ingestion_run_id = %s;
        """,
        (
            games_returned,
            games_processed,
            selections_inserted,
            selections_skipped,
            ingestion_run_id,
        ),
    )


def mark_ingestion_run_failed(
    connection,
    ingestion_run_id,
    games_returned,
    games_processed,
    selections_inserted,
    selections_skipped,
    error_message,
):
    """Record a failed ingestion run after rolling back data changes."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE odds_ingestion_runs
            SET completed_at = CURRENT_TIMESTAMP,
                status = 'failed',
                games_returned = %s,
                games_processed = %s,
                selections_inserted = %s,
                selections_skipped = %s,
                error_message = %s
            WHERE odds_ingestion_run_id = %s;
            """,
            (
                games_returned,
                games_processed,
                selections_inserted,
                selections_skipped,
                error_message,
                ingestion_run_id,
            ),
        )

    connection.commit()


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


    """Return the canonical game ID for an Odds API event."""

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
          AND away_team_id = %s
        LIMIT 1;
        """,
        (
            commence_time,
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
                commence_time,
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
            external_game_id,
        ),
    )

    return game_id


def save_market_selection(
    cursor,
    ingestion_run_id,
    game_id,
    sportsbook_id,
    market_type,
    selection_name,
    line_value,
    price,
    snapshot_time,
):
    """Store one sportsbook market selection snapshot."""

    cursor.execute(
        """
        INSERT INTO odds_market_snapshots (
            odds_ingestion_run_id,
            game_id,
            sportsbook_id,
            market_type,
            selection_name,
            line_value,
            price,
            snapshot_time,
            source_name
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        """,
        (
            ingestion_run_id,
            game_id,
            sportsbook_id,
            market_type,
            selection_name,
            line_value,
            price,
            snapshot_time,
            SOURCE_NAME,
        ),
    )


def fetch_live_odds():
    """Fetch current MLB moneyline, spread, and total odds."""

    api_key = os.getenv("ODDS_API_KEY")

    if not api_key:
        raise RuntimeError("ODDS_API_KEY is missing from the environment.")

    connection = get_connection()
    ingestion_run_id = None

    games_returned = 0
    games_processed = 0
    selections_inserted = 0
    selections_skipped = 0

    try:
        ingestion_run_id = create_ingestion_run(connection)

        print(f"Ingestion run ID: {ingestion_run_id}")

        url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"

        params = {
            "apiKey": api_key,
            "regions": REGIONS,
            "markets": MARKETS,
            "oddsFormat": ODDS_FORMAT,
        }

        response = requests.get(
            url,
            params=params,
            timeout=30,
        )

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
            raise RuntimeError(
                f"Odds API request failed with status "
                f"{response.status_code}: {response.text}"
            )

        games = response.json()
        games_returned = len(games)
        snapshot_time = datetime.now(timezone.utc)

        print(f"Games returned: {games_returned}")

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

                games_processed += 1

                for bookmaker in game.get("bookmakers", []):
                    sportsbook_name = bookmaker.get("title")

                    if not sportsbook_name:
                        continue

                    sportsbook_id = get_sportsbook_id(
                        cursor,
                        sportsbook_name,
                    )

                    for market in bookmaker.get("markets", []):
                        market_type = market.get("key")

                        if market_type not in {
                            "h2h",
                            "spreads",
                            "totals",
                        }:
                            continue

                        for outcome in market.get("outcomes", []):
                            selection_name = outcome.get("name")
                            price = outcome.get("price")
                            line_value = outcome.get("point")

                            if not selection_name or price is None:
                                selections_skipped += 1
                                continue

                            save_market_selection(
                                cursor=cursor,
                                ingestion_run_id=ingestion_run_id,
                                game_id=game_id,
                                sportsbook_id=sportsbook_id,
                                market_type=market_type,
                                selection_name=selection_name,
                                line_value=line_value,
                                price=price,
                                snapshot_time=snapshot_time,
                            )

                            selections_inserted += 1

            mark_ingestion_run_completed(
                cursor=cursor,
                ingestion_run_id=ingestion_run_id,
                games_returned=games_returned,
                games_processed=games_processed,
                selections_inserted=selections_inserted,
                selections_skipped=selections_skipped,
            )

        connection.commit()

    except Exception as error:
        connection.rollback()

        if ingestion_run_id is not None:
            mark_ingestion_run_failed(
                connection=connection,
                ingestion_run_id=ingestion_run_id,
                games_returned=games_returned,
                games_processed=games_processed,
                selections_inserted=selections_inserted,
                selections_skipped=selections_skipped,
                error_message=str(error),
            )

        raise

    finally:
        connection.close()

    print(f"Games processed: {games_processed}")
    print(f"Market selections inserted: {selections_inserted}")
    print(f"Selections skipped: {selections_skipped}")