import os
import requests
import psycopg2
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": os.getenv("POSTGRES_PORT"),
    "dbname": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}

SPORT = "baseball_mlb"
REGIONS = "us"
MARKETS = "h2h,totals"
ODDS_FORMAT = "american"

url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"

params = {
    "apiKey": API_KEY,
    "regions": REGIONS,
    "markets": MARKETS,
    "oddsFormat": ODDS_FORMAT,
}

response = requests.get(url, params=params, timeout=30)

print("Status Code:", response.status_code)
print("Remaining Requests:", response.headers.get("x-requests-remaining"))
print("Used Requests:", response.headers.get("x-requests-used"))

if response.status_code != 200:
    print(response.text)
    raise SystemExit("API request failed.")

games = response.json()
print(f"Games returned: {len(games)}")

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

snapshot_time = datetime.now(timezone.utc)

for game in games:
    commence_time = game.get("commence_time")
    home_team = game.get("home_team")
    away_team = game.get("away_team")

    cur.execute(
        """
        INSERT INTO teams (team_name)
        VALUES (%s)
        ON CONFLICT (team_name) DO NOTHING;
        """,
        (home_team,),
    )

    cur.execute(
        """
        INSERT INTO teams (team_name)
        VALUES (%s)
        ON CONFLICT (team_name) DO NOTHING;
        """,
        (away_team,),
    )

    cur.execute("SELECT team_id FROM teams WHERE team_name = %s;", (home_team,))
    home_team_id = cur.fetchone()[0]

    cur.execute("SELECT team_id FROM teams WHERE team_name = %s;", (away_team,))
    away_team_id = cur.fetchone()[0]

cur.execute(
    """
    INSERT INTO games (game_date, home_team_id, away_team_id)
    VALUES (%s, %s, %s)
    ON CONFLICT (game_date, home_team_id, away_team_id)
    DO NOTHING
    RETURNING game_id;
    """,
    (commence_time, home_team_id, away_team_id),
)

result = cur.fetchone()

if result:
    game_id = result[0]
else:
    cur.execute(
        """
        SELECT game_id
        FROM games
        WHERE game_date = %s
          AND home_team_id = %s
          AND away_team_id = %s;
        """,
        (commence_time, home_team_id, away_team_id),
    )
    game_id = cur.fetchone()[0]

    for bookmaker in game.get("bookmakers", []):
        book_name = bookmaker.get("title")

        cur.execute(
            """
            INSERT INTO sportsbooks (name)
            VALUES (%s)
            ON CONFLICT (name) DO NOTHING;
            """,
            (book_name,),
        )

        cur.execute("SELECT sportsbook_id FROM sportsbooks WHERE name = %s;", (book_name,))
        sportsbook_id = cur.fetchone()[0]

        for market in bookmaker.get("markets", []):
            market_type = market.get("key")

            if market_type == "h2h":
                home_price = None
                away_price = None

                for outcome in market.get("outcomes", []):
                    if outcome.get("name") == home_team:
                        home_price = outcome.get("price")
                    elif outcome.get("name") == away_team:
                        away_price = outcome.get("price")

                cur.execute(
                    """
                    INSERT INTO odds_snapshots
                    (game_id, sportsbook_id, market_type, home_price, away_price, snapshot_time)
                    VALUES (%s, %s, %s, %s, %s, %s);
                    """,
                    (game_id, sportsbook_id, market_type, home_price, away_price, snapshot_time),
                )

conn.commit()
cur.close()
conn.close()

print("MLB odds inserted successfully.")