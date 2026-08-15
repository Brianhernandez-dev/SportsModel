from __future__ import annotations

from typing import Any

from sportsmodel.nfl.models import NflTeamGameStatistics, NflTeamGameStatisticsSourceRecord


class NflStatisticsGameNotFoundError(ValueError):
    pass


class NflStatisticsGameAmbiguousError(ValueError):
    pass


def resolve_statistics_game(
    cursor: Any, *, record: NflTeamGameStatisticsSourceRecord,
    team_id: int, opponent_team_id: int,
) -> int:
    cursor.execute(
        """
        SELECT nfl.game_id
        FROM nfl_games nfl
        JOIN games game ON game.game_id = nfl.game_id
        WHERE nfl.season = %s AND nfl.season_type = %s AND nfl.week = %s
          AND ((game.home_team_id = %s AND game.away_team_id = %s)
            OR (game.home_team_id = %s AND game.away_team_id = %s))
        ORDER BY nfl.game_id;
        """,
        (record.season, record.season_type.value, record.week,
         team_id, opponent_team_id, opponent_team_id, team_id),
    )
    matches = cursor.fetchall()
    if not matches:
        raise NflStatisticsGameNotFoundError(
            "No canonical NFL game matches statistics row "
            f"{record.external_game_id} for season/week/participants"
        )
    if len(matches) != 1:
        raise NflStatisticsGameAmbiguousError(
            "Multiple canonical NFL games match statistics row "
            f"{record.external_game_id} for season/week/participants"
        )
    game_id = matches[0][0]
    cursor.execute(
        """SELECT game_id FROM game_sources
           WHERE source_name = %s AND external_game_id = %s;""",
        (record.source_name, record.external_game_id),
    )
    provider_match = cursor.fetchone()
    if provider_match is None:
        raise NflStatisticsGameNotFoundError(
            "No canonical nflverse game identity exists for statistics row "
            f"{record.external_game_id}"
        )
    if provider_match[0] != game_id:
        raise ValueError("Provider game identity conflicts with resolved canonical game")
    return game_id


def upsert_nfl_team_game_statistics(
    cursor: Any, *, game_id: int, team_id: int,
    record: NflTeamGameStatisticsSourceRecord,
) -> tuple[int, bool]:
    cursor.execute(
        "SELECT nfl_team_game_statistics_id FROM nfl_team_game_statistics "
        "WHERE game_id = %s AND team_id = %s;", (game_id, team_id)
    )
    inserted = cursor.fetchone() is None
    cursor.execute(
        """
        INSERT INTO nfl_team_game_statistics (
            game_id, team_id, completions, pass_attempts, passing_yards,
            passing_touchdowns, passing_interceptions, sacks_suffered, carries,
            rushing_yards, rushing_touchdowns, fumbles_lost, penalties, penalty_yards
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (game_id, team_id) DO UPDATE SET
            completions = EXCLUDED.completions,
            pass_attempts = EXCLUDED.pass_attempts,
            passing_yards = EXCLUDED.passing_yards,
            passing_touchdowns = EXCLUDED.passing_touchdowns,
            passing_interceptions = EXCLUDED.passing_interceptions,
            sacks_suffered = EXCLUDED.sacks_suffered,
            carries = EXCLUDED.carries,
            rushing_yards = EXCLUDED.rushing_yards,
            rushing_touchdowns = EXCLUDED.rushing_touchdowns,
            fumbles_lost = EXCLUDED.fumbles_lost,
            penalties = EXCLUDED.penalties,
            penalty_yards = EXCLUDED.penalty_yards,
            updated_at = CURRENT_TIMESTAMP
        RETURNING nfl_team_game_statistics_id;
        """,
        (game_id, team_id, record.completions, record.pass_attempts,
         record.passing_yards, record.passing_touchdowns,
         record.passing_interceptions, record.sacks_suffered, record.carries,
         record.rushing_yards, record.rushing_touchdowns, record.fumbles_lost,
         record.penalties, record.penalty_yards),
    )
    return cursor.fetchone()[0], inserted


def record_nfl_team_game_statistics_observation(cursor: Any, **values: Any) -> int:
    cursor.execute(
        """
        INSERT INTO nfl_team_game_statistics_source_observations (
            nfl_ingestion_run_id, nfl_team_game_statistics_id, game_id, team_id,
            source_name, external_game_id, provider_team_external_id,
            provider_opponent_external_id, raw_payload, raw_row_sha256, observed_at
        ) VALUES (
            %(nfl_ingestion_run_id)s, %(nfl_team_game_statistics_id)s,
            %(game_id)s, %(team_id)s, %(source_name)s, %(external_game_id)s,
            %(provider_team_external_id)s, %(provider_opponent_external_id)s,
            %(raw_payload)s, %(raw_row_sha256)s, %(observed_at)s)
        ON CONFLICT (nfl_ingestion_run_id, source_name, external_game_id,
                     provider_team_external_id, raw_row_sha256)
        DO UPDATE SET observed_at = EXCLUDED.observed_at
        RETURNING nfl_team_game_statistics_source_observation_id;
        """, values,
    )
    return cursor.fetchone()[0]


_SELECT = """
SELECT stats.game_id, stats.team_id, stats.completions, stats.pass_attempts,
       stats.passing_yards, stats.passing_touchdowns,
       stats.passing_interceptions, stats.sacks_suffered, stats.carries,
       stats.rushing_yards, stats.rushing_touchdowns, stats.fumbles_lost,
       stats.penalties, stats.penalty_yards
FROM nfl_team_game_statistics stats
"""


def load_nfl_team_game_statistics(cursor: Any, *, game_id: int, team_id: int):
    cursor.execute(_SELECT + " WHERE stats.game_id = %s AND stats.team_id = %s;",
                   (game_id, team_id))
    row = cursor.fetchone()
    return None if row is None else NflTeamGameStatistics(*row)


def list_nfl_team_game_statistics_for_game(cursor: Any, *, game_id: int):
    cursor.execute(_SELECT + " WHERE stats.game_id = %s ORDER BY stats.team_id;",
                   (game_id,))
    return tuple(NflTeamGameStatistics(*row) for row in cursor.fetchall())


def list_nfl_team_game_statistics_for_team_season(
    cursor: Any, *, team_id: int, season: int,
):
    cursor.execute(
        _SELECT + " JOIN nfl_games nfl ON nfl.game_id = stats.game_id "
        "WHERE stats.team_id = %s AND nfl.season = %s "
        "ORDER BY nfl.scheduled_start_time, stats.game_id;", (team_id, season)
    )
    return tuple(NflTeamGameStatistics(*row) for row in cursor.fetchall())
