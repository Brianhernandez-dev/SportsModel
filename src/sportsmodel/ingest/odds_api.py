from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import os
from zoneinfo import ZoneInfo

import requests

from sportsmodel.database.connection import get_connection

from sportsmodel.ingest.game_matching import (
    get_or_create_canonical_game,
)
from sportsmodel.ingest.team_identity import normalize_team_name


SPORT = "baseball_mlb"
REGIONS = "us"
MARKETS = "h2h"
ODDS_FORMAT = "american"
SOURCE_NAME = "odds_api"
SLATE_TIME_ZONE = ZoneInfo("America/Los_Angeles")

LIVE_SNAPSHOT_ROLES = frozenset(
    {
        "manual",
        "opening",
        "evening",
        "late_night",
        "morning",
        "entry",
        "afternoon",
        "near_close",
    }
)

SCHEDULED_SNAPSHOT_ROLES = frozenset(
    {
        "opening",
        "evening",
        "late_night",
        "morning",
        "entry",
        "afternoon",
        "near_close",
    }
)


class DuplicateOddsSnapshotError(RuntimeError):
    """Raised when an active scheduled snapshot already exists."""


@dataclass(frozen=True)
class OddsIngestionResult:
    odds_ingestion_run_id: int
    target_date: date | None
    snapshot_role: str
    status_code: int
    remaining_requests: int | None
    used_requests: int | None
    games_returned: int
    games_processed: int
    selections_inserted: int
    selections_skipped: int


def build_target_date_window(
    target_date: date,
) -> tuple[datetime, datetime]:
    """
    Return the target Pacific calendar day as a UTC half-open window.
    """

    local_start = datetime.combine(
        target_date,
        time.min,
        tzinfo=SLATE_TIME_ZONE,
    )
    local_end = datetime.combine(
        target_date + timedelta(days=1),
        time.min,
        tzinfo=SLATE_TIME_ZONE,
    )

    return (
        local_start.astimezone(timezone.utc),
        local_end.astimezone(timezone.utc),
    )


def _format_api_timestamp(
    value: datetime,
) -> str:
    """
    Format a timezone-aware timestamp for The Odds API.
    """

    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _is_in_target_date_window(
    commence_time: datetime,
    target_window: tuple[datetime, datetime] | None,
) -> bool:
    """
    Return whether an event belongs to the requested Pacific slate.
    """

    if target_window is None:
        return True

    window_start, window_end = target_window

    return window_start <= commence_time < window_end


def _current_snapshot_time() -> datetime:
    """
    Return the UTC capture time for an odds snapshot.
    """

    return datetime.now(timezone.utc)


def _is_pregame_event(
    commence_time: datetime,
    snapshot_time: datetime,
) -> bool:
    """
    Return whether the event has not started at capture time.
    """

    return commence_time > snapshot_time


def _should_process_event(
    commence_time: datetime,
    target_window: tuple[datetime, datetime] | None,
    snapshot_time: datetime,
) -> bool:
    """
    Require both the requested slate date and pregame status.
    """

    return (
        _is_in_target_date_window(
            commence_time,
            target_window,
        )
        and _is_pregame_event(
            commence_time,
            snapshot_time,
        )
    )


def _validate_snapshot_context(
    *,
    target_date: date | None,
    snapshot_role: str,
) -> str:
    normalized_role = snapshot_role.strip().lower()

    if normalized_role not in LIVE_SNAPSHOT_ROLES:
        supported_roles = ", ".join(
            sorted(LIVE_SNAPSHOT_ROLES)
        )
        raise ValueError(
            "Unsupported odds snapshot role: "
            f"{snapshot_role!r}. "
            f"Supported roles: {supported_roles}."
        )

    if (
        normalized_role in SCHEDULED_SNAPSHOT_ROLES
        and target_date is None
    ):
        raise ValueError(
            "Scheduled odds snapshots require a target date."
        )

    return normalized_role


def _parse_quota_header(
    value: str | None,
) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def parse_commence_time(value: str) -> datetime:
    """
    Convert an Odds API commence time to a timezone-aware UTC datetime.
    """

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).astimezone(timezone.utc)

def create_ingestion_run(
    connection,
    *,
    target_date: date | None,
    snapshot_role: str,
):
    """Create and commit a new odds-ingestion audit record."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO odds_ingestion_runs (
                sport,
                source_name,
                target_date,
                snapshot_role,
                status
            )
            VALUES (%s, %s, %s, %s, 'running')
            ON CONFLICT DO NOTHING
            RETURNING odds_ingestion_run_id;
            """,
            (
                SPORT,
                SOURCE_NAME,
                target_date,
                snapshot_role,
            ),
        )

        returned_row = cursor.fetchone()

        if returned_row is None:
            raise DuplicateOddsSnapshotError(
                "An active odds snapshot already exists for "
                f"{target_date} with role {snapshot_role!r}."
            )

        ingestion_run_id = returned_row[0]

    # Commit this separately so the run remains available if ingestion fails.
    connection.commit()

    return ingestion_run_id


def mark_ingestion_run_completed(
    cursor,
    ingestion_run_id,
    status_code,
    remaining_requests,
    used_requests,
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
            status_code = %s,
            remaining_requests = %s,
            used_requests = %s,
            games_returned = %s,
            games_processed = %s,
            selections_inserted = %s,
            selections_skipped = %s,
            error_message = NULL
        WHERE odds_ingestion_run_id = %s;
        """,
        (
            status_code,
            remaining_requests,
            used_requests,
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
    status_code,
    remaining_requests,
    used_requests,
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
                status_code = %s,
                remaining_requests = %s,
                used_requests = %s,
                games_returned = %s,
                games_processed = %s,
                selections_inserted = %s,
                selections_skipped = %s,
                error_message = %s
            WHERE odds_ingestion_run_id = %s;
            """,
            (
                status_code,
                remaining_requests,
                used_requests,
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

    canonical_team_name = normalize_team_name(team_name)

    cursor.execute(
        """
        INSERT INTO teams (team_name)
        VALUES (%s)
        ON CONFLICT (team_name) DO NOTHING;
        """,
        (canonical_team_name,),
    )

    cursor.execute(
        """
        SELECT team_id
        FROM teams
        WHERE team_name = %s;
        """,
        (canonical_team_name,),
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


def fetch_live_odds(
    *,
    target_date: date | None = None,
    snapshot_role: str = "manual",
) -> OddsIngestionResult:
    """Fetch current MLB Moneyline odds."""

    normalized_snapshot_role = _validate_snapshot_context(
        target_date=target_date,
        snapshot_role=snapshot_role,
    )

    target_window = (
        build_target_date_window(target_date)
        if target_date is not None
        else None
    )

    api_key = os.getenv("ODDS_API_KEY")

    if not api_key:
        raise RuntimeError("ODDS_API_KEY is missing from the environment.")

    connection = get_connection()
    ingestion_run_id = None

    games_returned = 0
    games_processed = 0
    selections_inserted = 0
    selections_skipped = 0

    status_code: int | None = None
    remaining_requests = None
    used_requests = None

    try:
        ingestion_run_id = create_ingestion_run(
            connection,
            target_date=target_date,
            snapshot_role=normalized_snapshot_role,
        )

        print(f"Ingestion run ID: {ingestion_run_id}")

        url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"

        params = {
            "apiKey": api_key,
            "regions": REGIONS,
            "markets": MARKETS,
            "oddsFormat": ODDS_FORMAT,
        }

        if target_window is not None:
            window_start, window_end = target_window

            params["commenceTimeFrom"] = (
                _format_api_timestamp(window_start)
            )
            params["commenceTimeTo"] = (
                _format_api_timestamp(
                    window_end - timedelta(seconds=1)
                )
            )

        response = requests.get(
            url,
            params=params,
            timeout=30,
        )

        status_code = response.status_code
        remaining_requests = _parse_quota_header(
            response.headers.get(
                "x-requests-remaining"
            )
        )
        used_requests = _parse_quota_header(
            response.headers.get(
                "x-requests-used"
            )
        )

        print("Status Code:", status_code)
        print(
            "Remaining Requests:",
            remaining_requests,
        )
        print(
            "Used Requests:",
            used_requests,
        )

        if status_code != 200:
            raise RuntimeError(
                f"Odds API request failed with status "
                f"{status_code}: {response.text}"
            )

        games = response.json()
        games_returned = len(games)
        snapshot_time = _current_snapshot_time()

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

                commence_datetime = parse_commence_time(
                    commence_time
                )

                if not _should_process_event(
                    commence_datetime,
                    target_window,
                    snapshot_time,
                ):
                    continue

                home_team_id = get_team_id(cursor, home_team)
                away_team_id = get_team_id(cursor, away_team)

                game_id = get_or_create_canonical_game(
                    cursor,
                    source_name=SOURCE_NAME,
                    external_game_id=external_game_id,
                    game_datetime=commence_datetime,
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

                        if market_type != "h2h":
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
                status_code=status_code,
                remaining_requests=remaining_requests,
                used_requests=used_requests,
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
                status_code=status_code,
                remaining_requests=remaining_requests,
                used_requests=used_requests,
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

    if status_code is None:
        raise RuntimeError(
            "Completed odds ingestion has no HTTP status code."
        )

    return OddsIngestionResult(
        odds_ingestion_run_id=ingestion_run_id,
        target_date=target_date,
        snapshot_role=normalized_snapshot_role,
        status_code=status_code,
        remaining_requests=remaining_requests,
        used_requests=used_requests,
        games_returned=games_returned,
        games_processed=games_processed,
        selections_inserted=selections_inserted,
        selections_skipped=selections_skipped,
    )
