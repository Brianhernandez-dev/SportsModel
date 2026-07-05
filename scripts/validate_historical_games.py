import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.getenv("POSTGRES_DB", "sportsmodel")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")


def get_connection():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )


def main():
    conn = get_connection()
    cur = conn.cursor()

    print("\n=== Historical Games Validation ===\n")

    cur.execute("SELECT COUNT(*) FROM historical_games;")
    total_games = cur.fetchone()[0]
    print(f"Total historical games: {total_games}")

    cur.execute("""
        SELECT mlb_game_id, COUNT(*)
        FROM historical_games
        GROUP BY mlb_game_id
        HAVING COUNT(*) > 1;
    """)
    duplicates = cur.fetchall()

    print(f"\nDuplicate MLB game IDs found: {len(duplicates)}")

    if duplicates:
        for dup in duplicates[:20]:
            print(dup)

    cur.execute("""
        SELECT COUNT(*)
        FROM historical_games
        WHERE home_score IS NULL
           OR away_score IS NULL
           OR home_team IS NULL
           OR away_team IS NULL
           OR game_date IS NULL;
                """)
    bad_rows = cur.fetchone()[0]

    print(f"Rows with missing critical data: {bad_rows}")

    cur.close()
    conn.close()

    print("\nValidation complete.\n")


if __name__ == "__main__":
    main()