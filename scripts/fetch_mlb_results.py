import os
import requests
import psycopg2
from dotenv import load_dotenv
from datetime import date, timedelta

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": os.getenv("POSTGRES_PORT"),
    "dbname": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}

START_DATE = date(2026, 6, 1)
END_DATE = date.today() - timedelta(days=1)

def daterange(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

inserted = 0

for day in daterange(START_DATE, END_DATE):
    url = "https://statsapi.mlb.com/api/v1/schedule"
    params = {
        "sportId": 1,
        "date": day.isoformat(),
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    for game_date_block in data.get("dates", []):
        for game in game_date_block.get("games", []):
            status = game.get("status", {}).get("detailedState")

            if status != "Final":
                continue

            home_team = game["teams"]["home"]["team"]["name"]
            away_team = game["teams"]["away"]["team"]["name"]
            home_score = game["teams"]["home"].get("score")
            away_score = game["teams"]["away"].get("score")

            if home_score is None or away_score is None:
                continue

            home_win = home_score > away_score

            cur.execute(
                """
                INSERT INTO historical_games (
                    game_date,
                    home_team,
                    away_team,
                    home_score,
                    away_score,
                    home_win
                )
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (
                    day,
                    home_team,
                    away_team,
                    home_score,
                    away_score,
                    home_win,
                ),
            )

            inserted += 1

conn.commit()
cur.close()
conn.close()

print(f"Inserted historical games: {inserted}")