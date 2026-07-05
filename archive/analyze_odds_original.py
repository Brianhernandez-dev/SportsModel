import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": os.getenv("POSTGRES_PORT"),
    "dbname": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}

def american_to_implied_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

cur.execute("""
    SELECT snapshot_id, home_price, away_price
    FROM odds_snapshots
    WHERE snapshot_id NOT IN (
        SELECT snapshot_id FROM odds_analysis
    )
    AND home_price IS NOT NULL
    AND away_price IS NOT NULL;
""")

rows = cur.fetchall()
print(f"Snapshots to analyze: {len(rows)}")

for snapshot_id, home_price, away_price in rows:
    implied_home = american_to_implied_prob(home_price)
    implied_away = american_to_implied_prob(away_price)

    total_implied = implied_home + implied_away

    no_vig_home = implied_home / total_implied
    no_vig_away = implied_away / total_implied

    cur.execute("""
        INSERT INTO odds_analysis (
            snapshot_id,
            implied_home_probability,
            implied_away_probability,
            no_vig_home_probability,
            no_vig_away_probability
        )
        VALUES (%s, %s, %s, %s, %s);
    """, (
        snapshot_id,
        implied_home,
        implied_away,
        no_vig_home,
        no_vig_away
    ))

conn.commit()
cur.close()
conn.close()

print("Odds analysis completed.")