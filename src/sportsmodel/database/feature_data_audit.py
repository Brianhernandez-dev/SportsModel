from collections.abc import Iterable

from sportsmodel.database.connection import get_connection
from sportsmodel.models.feature_data_audit import (
    FeatureDataAuditCheck,
    FeatureDataAuditReport,
)


TEAM_GAME_STAT_TABLES = (
    "team_game_statistics",
    "baseball_team_game_statistics",
)

PLAYER_BATTING_STAT_TABLES = (
    "player_game_batting_statistics",
    "baseball_player_game_batting_statistics",
)

PLAYER_PITCHING_STAT_TABLES = (
    "player_game_pitching_statistics",
    "baseball_player_game_pitching_statistics",
)

STARTING_PITCHER_TABLES = (
    "game_starting_pitchers",
    "baseball_game_starting_pitchers",
)


def audit_feature_data() -> FeatureDataAuditReport:
    """
    Inspect the live database for feature-engineering readiness.

    The audit uses schema discovery instead of assuming that all future
    feature tables already exist. Missing tables are reported as explicit
    gaps rather than causing the audit to fail.
    """

    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            table_names = _get_public_table_names(cursor)

            checks = (
                _audit_historical_games(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_game_timestamps(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_team_linkage(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_player_catalog(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_roster_history(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_team_batting_statistics(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_team_pitching_statistics(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_player_batting_statistics(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_player_pitching_statistics(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_starting_pitchers(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_bullpen_identification(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_doubleheader_metadata(
                    cursor=cursor,
                    table_names=table_names,
                ),
                _audit_market_snapshots(
                    cursor=cursor,
                    table_names=table_names,
                ),
            )

        return FeatureDataAuditReport(
            checks=checks,
        )

    finally:
        connection.close()


def _get_public_table_names(cursor) -> set[str]:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE';
        """
    )

    return {
        row[0]
        for row in cursor.fetchall()
    }


def _get_column_names(
    cursor,
    table_name: str,
) -> set[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s;
        """,
        (table_name,),
    )

    return {
        row[0]
        for row in cursor.fetchall()
    }


def _count_rows(
    cursor,
    table_name: str,
) -> int:
    if not table_name.replace("_", "").isalnum():
        raise ValueError(
            "Unsafe table name supplied to audit."
        )

    cursor.execute(
        f"SELECT COUNT(*) FROM {table_name};"
    )

    return cursor.fetchone()[0]


def _find_first_table(
    table_names: set[str],
    candidates: Iterable[str],
) -> str | None:
    return next(
        (
            candidate
            for candidate in candidates
            if candidate in table_names
        ),
        None,
    )


def _audit_historical_games(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    table_name = "historical_games"

    if table_name not in table_names:
        return FeatureDataAuditCheck(
            name="Historical game results",
            available=False,
            detail=(
                "The historical_games table does not exist."
            ),
        )

    row_count = _count_rows(
        cursor=cursor,
        table_name=table_name,
    )

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM historical_games
        WHERE home_score IS NOT NULL
          AND away_score IS NOT NULL;
        """
    )

    completed_count = cursor.fetchone()[0]

    return FeatureDataAuditCheck(
        name="Historical game results",
        available=completed_count > 0,
        row_count=row_count,
        detail=(
            f"{completed_count} of {row_count} historical games "
            "contain final home and away scores."
        ),
    )


def _audit_game_timestamps(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    if "games" not in table_names:
        return FeatureDataAuditCheck(
            name="Canonical game timestamps",
            available=False,
            detail="The games table does not exist.",
        )

    columns = _get_column_names(
        cursor=cursor,
        table_name="games",
    )

    if "game_date" not in columns:
        return FeatureDataAuditCheck(
            name="Canonical game timestamps",
            available=False,
            detail=(
                "The games table does not contain game_date."
            ),
        )

    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_games,
            COUNT(game_date) AS timestamped_games
        FROM games;
        """
    )

    total_games, timestamped_games = cursor.fetchone()

    cursor.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'games'
          AND column_name = 'game_date';
        """
    )

    data_type = cursor.fetchone()[0]

    timezone_aware = (
        data_type == "timestamp with time zone"
    )

    available = (
        total_games > 0
        and timestamped_games == total_games
        and timezone_aware
    )

    return FeatureDataAuditCheck(
        name="Canonical game timestamps",
        available=available,
        row_count=total_games,
        detail=(
            f"{timestamped_games} of {total_games} games have "
            f"game_date values. Column type: {data_type}."
        ),
    )


def _audit_team_linkage(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    required_tables = {
        "games",
        "historical_games",
    }

    if not required_tables.issubset(table_names):
        return FeatureDataAuditCheck(
            name="Canonical team linkage",
            available=False,
            detail=(
                "The games and historical_games tables are both "
                "required."
            ),
        )

    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_historical_games,
            COUNT(hg.game_id) FILTER (
                WHERE g.game_id IS NOT NULL
            ) AS linked_games,
            COUNT(*) FILTER (
                WHERE g.home_team_id IS NULL
                   OR g.away_team_id IS NULL
            ) AS games_missing_team_ids
        FROM historical_games hg
        LEFT JOIN games g
            ON g.game_id = hg.game_id;
        """
    )

    (
        total_games,
        linked_games,
        missing_team_ids,
    ) = cursor.fetchone()

    available = (
        total_games > 0
        and linked_games == total_games
        and missing_team_ids == 0
    )

    return FeatureDataAuditCheck(
        name="Canonical team linkage",
        available=available,
        row_count=total_games,
        detail=(
            f"{linked_games} of {total_games} historical games "
            "are linked to canonical games; "
            f"{missing_team_ids} linked games are missing a "
            "home or away team ID."
        ),
    )


def _audit_player_catalog(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    table_name = "baseball_players"

    if table_name not in table_names:
        return FeatureDataAuditCheck(
            name="Canonical MLB players",
            available=False,
            detail=(
                "The baseball_players table does not exist."
            ),
        )

    row_count = _count_rows(
        cursor=cursor,
        table_name=table_name,
    )

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM baseball_players
        WHERE is_active = TRUE;
        """
    )

    active_count = cursor.fetchone()[0]

    return FeatureDataAuditCheck(
        name="Canonical MLB players",
        available=row_count > 0,
        row_count=row_count,
        detail=(
            f"{row_count} canonical players exist; "
            f"{active_count} are currently active."
        ),
    )


def _audit_roster_history(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    table_name = "baseball_player_team_assignments"

    if table_name not in table_names:
        return FeatureDataAuditCheck(
            name="Player team assignment history",
            available=False,
            detail=(
                "The baseball_player_team_assignments table "
                "does not exist."
            ),
        )

    row_count = _count_rows(
        cursor=cursor,
        table_name=table_name,
    )

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM baseball_player_team_assignments
        WHERE is_current = TRUE;
        """
    )

    current_count = cursor.fetchone()[0]

    return FeatureDataAuditCheck(
        name="Player team assignment history",
        available=row_count > 0,
        row_count=row_count,
        detail=(
            f"{row_count} total assignment records exist; "
            f"{current_count} are current."
        ),
    )


def _audit_team_batting_statistics(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    table_name = _find_first_table(
        table_names=table_names,
        candidates=TEAM_GAME_STAT_TABLES,
    )

    if table_name is None:
        return FeatureDataAuditCheck(
            name="Team game batting statistics",
            available=False,
            detail=(
                "No supported team game statistics table exists. "
                "Required batting inputs include at-bats, hits, "
                "runs, home runs, walks, and strikeouts."
            ),
        )

    row_count = _count_rows(cursor, table_name)

    columns = _get_column_names(
        cursor=cursor,
        table_name=table_name,
    )

    required_columns = {
        "game_id",
        "team_id",
        "runs",
        "hits",
        "home_runs",
        "walks",
        "strikeouts",
        "at_bats",
    }

    missing_columns = required_columns - columns

    return FeatureDataAuditCheck(
        name="Team game batting statistics",
        available=(
            row_count > 0
            and not missing_columns
        ),
        row_count=row_count,
        detail=(
            f"Table {table_name} contains {row_count} rows. "
            f"Missing required columns: "
            f"{sorted(missing_columns)}."
        ),
    )


def _audit_team_pitching_statistics(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    table_name = _find_first_table(
        table_names=table_names,
        candidates=TEAM_GAME_STAT_TABLES,
    )

    if table_name is None:
        return FeatureDataAuditCheck(
            name="Team game pitching statistics",
            available=False,
            detail=(
                "No supported team game statistics table exists. "
                "Required pitching inputs include innings, runs, "
                "earned runs, hits, walks, strikeouts, and home "
                "runs allowed."
            ),
        )

    row_count = _count_rows(cursor, table_name)

    columns = _get_column_names(
        cursor=cursor,
        table_name=table_name,
    )

    required_columns = {
        "game_id",
        "team_id",
        "pitching_outs",
        "runs_allowed",
        "earned_runs_allowed",
        "hits_allowed",
        "walks_allowed",
        "strikeouts_recorded",
        "home_runs_allowed",
    }

    missing_columns = required_columns - columns

    return FeatureDataAuditCheck(
        name="Team game pitching statistics",
        available=(
            row_count > 0
            and not missing_columns
        ),
        row_count=row_count,
        detail=(
            f"Table {table_name} contains {row_count} rows. "
            f"Missing required columns: "
            f"{sorted(missing_columns)}."
        ),
    )


def _audit_player_batting_statistics(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    table_name = _find_first_table(
        table_names=table_names,
        candidates=PLAYER_BATTING_STAT_TABLES,
    )

    if table_name is None:
        return FeatureDataAuditCheck(
            name="Player game batting statistics",
            available=False,
            detail=(
                "No supported player game batting statistics "
                "table exists."
            ),
        )

    row_count = _count_rows(cursor, table_name)

    return FeatureDataAuditCheck(
        name="Player game batting statistics",
        available=row_count > 0,
        row_count=row_count,
        detail=(
            f"Table {table_name} contains {row_count} rows."
        ),
    )


def _audit_player_pitching_statistics(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    table_name = _find_first_table(
        table_names=table_names,
        candidates=PLAYER_PITCHING_STAT_TABLES,
    )

    if table_name is None:
        return FeatureDataAuditCheck(
            name="Player game pitching statistics",
            available=False,
            detail=(
                "No supported player game pitching statistics "
                "table exists."
            ),
        )

    row_count = _count_rows(cursor, table_name)

    columns = _get_column_names(
        cursor=cursor,
        table_name=table_name,
    )

    required_columns = {
        "game_id",
        "team_id",
        "baseball_player_id",
        "pitching_outs",
        "hits_allowed",
        "runs_allowed",
        "earned_runs_allowed",
        "walks_allowed",
        "strikeouts",
        "home_runs_allowed",
    }

    missing_columns = required_columns - columns

    return FeatureDataAuditCheck(
        name="Player game pitching statistics",
        available=(
            row_count > 0
            and not missing_columns
        ),
        row_count=row_count,
        detail=(
            f"Table {table_name} contains {row_count} rows. "
            f"Missing required columns: "
            f"{sorted(missing_columns)}."
        ),
    )


def _audit_starting_pitchers(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    starter_table = _find_first_table(
        table_names=table_names,
        candidates=STARTING_PITCHER_TABLES,
    )

    if starter_table is not None:
        row_count = _count_rows(cursor, starter_table)

        return FeatureDataAuditCheck(
            name="Historical starting pitchers",
            available=row_count > 0,
            row_count=row_count,
            detail=(
                f"Table {starter_table} contains "
                f"{row_count} rows."
            ),
        )

    pitching_table = _find_first_table(
        table_names=table_names,
        candidates=PLAYER_PITCHING_STAT_TABLES,
    )

    if pitching_table is not None:
        columns = _get_column_names(
            cursor=cursor,
            table_name=pitching_table,
        )

        if "is_starter" in columns:
            row_count = _count_rows(
                cursor,
                pitching_table,
            )

            return FeatureDataAuditCheck(
                name="Historical starting pitchers",
                available=row_count > 0,
                row_count=row_count,
                detail=(
                    f"Starter identity can be derived from "
                    f"{pitching_table}.is_starter."
                ),
            )

    return FeatureDataAuditCheck(
        name="Historical starting pitchers",
        available=False,
        detail=(
            "No starter assignment table or player pitching "
            "is_starter field exists."
        ),
    )


def _audit_bullpen_identification(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    pitching_table = _find_first_table(
        table_names=table_names,
        candidates=PLAYER_PITCHING_STAT_TABLES,
    )

    if pitching_table is None:
        return FeatureDataAuditCheck(
            name="Bullpen appearance identification",
            available=False,
            detail=(
                "Player game pitching statistics are required "
                "to distinguish starters from relievers."
            ),
        )

    columns = _get_column_names(
        cursor=cursor,
        table_name=pitching_table,
    )

    supported_flags = {
        "is_starter",
        "appearance_type",
        "role",
    }

    available_flags = supported_flags & columns

    return FeatureDataAuditCheck(
        name="Bullpen appearance identification",
        available=bool(available_flags),
        row_count=_count_rows(cursor, pitching_table),
        detail=(
            "Available role-identification columns: "
            f"{sorted(available_flags)}."
        ),
    )


def _audit_doubleheader_metadata(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    candidate_tables = (
        "games",
        "historical_games",
    )

    candidate_columns = {
        "doubleheader",
        "doubleheader_game",
        "game_number",
        "series_game_number",
    }

    discovered_columns: dict[str, list[str]] = {}

    for table_name in candidate_tables:
        if table_name not in table_names:
            continue

        columns = _get_column_names(
            cursor=cursor,
            table_name=table_name,
        )

        matches = sorted(
            candidate_columns & columns
        )

        if matches:
            discovered_columns[table_name] = matches

    return FeatureDataAuditCheck(
        name="Doubleheader metadata",
        available=bool(discovered_columns),
        detail=(
            "Discovered doubleheader-related columns: "
            f"{discovered_columns}."
        ),
    )


def _audit_market_snapshots(
    cursor,
    table_names: set[str],
) -> FeatureDataAuditCheck:
    table_name = "odds_market_snapshots"

    if table_name not in table_names:
        return FeatureDataAuditCheck(
            name="Pregame market snapshots",
            available=False,
            detail=(
                "The odds_market_snapshots table does not exist."
            ),
        )

    row_count = _count_rows(
        cursor=cursor,
        table_name=table_name,
    )

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM odds_market_snapshots oms
        JOIN games g
            ON g.game_id = oms.game_id
        WHERE oms.snapshot_time < g.game_date;
        """
    )

    pregame_count = cursor.fetchone()[0]

    return FeatureDataAuditCheck(
        name="Pregame market snapshots",
        available=pregame_count > 0,
        row_count=row_count,
        detail=(
            f"{pregame_count} of {row_count} snapshots occurred "
            "before their canonical game start time."
        ),
    )
