from __future__ import annotations

from typing import Any

from sportsmodel.nfl.models import (
    NflGame,
    NflGameSourceRecord,
    NflGameStatus,
    NflSeasonType,
)


def load_nfl_game_by_id(cursor: Any, *, game_id: int) -> NflGame | None:
    cursor.execute(_SELECT_CANONICAL_GAME + " WHERE nfl.game_id = %s;", (game_id,))
    row = cursor.fetchone()
    return None if row is None else _canonical_game_from_row(row)


def resolve_nfl_game_by_source(
    cursor: Any, *, source_name: str, external_game_id: str
) -> NflGameSourceRecord | None:
    cursor.execute(
        _SELECT_SOURCE_GAME
        + " WHERE src.source_name = %s AND src.external_game_id = %s;",
        (source_name, external_game_id),
    )
    row = cursor.fetchone()
    return None if row is None else _game_from_row(row)


def list_nfl_games_by_season(
    cursor: Any, *, season: int
) -> tuple[NflGame, ...]:
    cursor.execute(
        _SELECT_CANONICAL_GAME
        + " WHERE nfl.season = %s ORDER BY nfl.scheduled_start_time, nfl.game_id;",
        (season,),
    )
    return tuple(_canonical_game_from_row(row) for row in cursor.fetchall())


def list_nfl_games_by_season_range(
    cursor: Any, *, season_from: int, season_to: int,
) -> tuple[NflGame, ...]:
    if season_from > season_to:
        raise ValueError("season_from cannot exceed season_to")
    cursor.execute(
        _SELECT_CANONICAL_GAME
        + " WHERE nfl.season BETWEEN %s AND %s "
        "ORDER BY nfl.scheduled_start_time, nfl.game_id;",
        (season_from, season_to),
    )
    return tuple(_canonical_game_from_row(row) for row in cursor.fetchall())


def persist_nfl_game(
    cursor: Any,
    *,
    record: NflGameSourceRecord,
    home_team_id: int,
    away_team_id: int,
) -> tuple[int, bool]:
    """Upsert by immutable provider identity; return (game_id, inserted)."""
    cursor.execute(
        """
        SELECT src.game_id, game.home_team_id, game.away_team_id
        FROM game_sources src
        JOIN games game ON game.game_id = src.game_id
        WHERE src.source_name = %s AND src.external_game_id = %s
        FOR UPDATE;
        """,
        (record.source_name, record.external_game_id),
    )
    existing = cursor.fetchone()
    inserted = existing is None
    if existing is None:
        cursor.execute(
            """
            INSERT INTO games (game_date, home_team_id, away_team_id)
            VALUES (%s, %s, %s) RETURNING game_id;
            """,
            (record.scheduled_start_time, home_team_id, away_team_id),
        )
        game_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO game_sources (game_id, source_name, external_game_id)
            VALUES (%s, %s, %s);
            """,
            (game_id, record.source_name, record.external_game_id),
        )
    else:
        game_id, existing_home, existing_away = existing
        if (existing_home, existing_away) != (home_team_id, away_team_id):
            raise ValueError(
                "Provider game identity is already mapped to a conflicting matchup: "
                f"{record.source_name}/{record.external_game_id}."
            )
        cursor.execute(
            "UPDATE games SET game_date = %s WHERE game_id = %s;",
            (record.scheduled_start_time, game_id),
        )
    cursor.execute(
        """
        INSERT INTO nfl_games (
            game_id, season, season_type, week, week_label,
            scheduled_start_time, neutral_site, status,
            home_score, away_score, overtime
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (game_id) DO UPDATE SET
            season = EXCLUDED.season,
            season_type = EXCLUDED.season_type,
            week = EXCLUDED.week,
            week_label = EXCLUDED.week_label,
            scheduled_start_time = EXCLUDED.scheduled_start_time,
            neutral_site = EXCLUDED.neutral_site,
            status = EXCLUDED.status,
            home_score = EXCLUDED.home_score,
            away_score = EXCLUDED.away_score,
            overtime = EXCLUDED.overtime,
            updated_at = CURRENT_TIMESTAMP;
        """,
        (
            game_id, record.season, record.season_type.value, record.week,
            record.week_label, record.scheduled_start_time, record.neutral_site,
            record.status.value, record.home_score, record.away_score, record.overtime,
        ),
    )
    return game_id, inserted


def record_nfl_game_observation(cursor: Any, **values: Any) -> int:
    cursor.execute(
        """
        INSERT INTO nfl_game_source_observations (
            nfl_ingestion_run_id, game_id, source_name, external_game_id,
            provider_home_external_team_id, provider_away_external_team_id,
            provider_gameday, provider_gametime, provider_game_type, provider_week,
            raw_payload, raw_row_sha256, observed_at, provider_updated_at,
            anomaly_state, anomaly_reason, override_provenance
        ) VALUES (
            %(nfl_ingestion_run_id)s, %(game_id)s, %(source_name)s,
            %(external_game_id)s, %(provider_home_external_team_id)s,
            %(provider_away_external_team_id)s, %(provider_gameday)s,
            %(provider_gametime)s, %(provider_game_type)s, %(provider_week)s,
            %(raw_payload)s, %(raw_row_sha256)s, %(observed_at)s, NULL,
            %(anomaly_state)s, %(anomaly_reason)s, %(override_provenance)s
        )
        ON CONFLICT (nfl_ingestion_run_id, source_name, external_game_id,
                     raw_row_sha256)
        DO UPDATE SET observed_at = EXCLUDED.observed_at
        RETURNING nfl_game_source_observation_id;
        """,
        values,
    )
    return cursor.fetchone()[0]


def list_nfl_game_anomaly_evidence(
    cursor: Any, *, source_name: str, external_game_id: str
) -> tuple[dict[str, Any], ...]:
    """Return retained override/quarantine evidence for one provider event."""
    cursor.execute(
        """
        SELECT nfl_game_source_observation_id, nfl_ingestion_run_id, game_id,
               raw_payload, raw_row_sha256, observed_at, anomaly_state,
               anomaly_reason, override_provenance
        FROM nfl_game_source_observations
        WHERE source_name = %s AND external_game_id = %s
          AND anomaly_state <> 'none'
        ORDER BY nfl_game_source_observation_id;
        """,
        (source_name, external_game_id),
    )
    names = (
        "nfl_game_source_observation_id", "nfl_ingestion_run_id", "game_id",
        "raw_payload", "raw_row_sha256", "observed_at", "anomaly_state",
        "anomaly_reason", "override_provenance",
    )
    return tuple(dict(zip(names, row, strict=True)) for row in cursor.fetchall())


_SELECT_CANONICAL_GAME = """
SELECT nfl.game_id, nfl.season, nfl.season_type, nfl.week, nfl.week_label,
       nfl.scheduled_start_time, game.home_team_id, game.away_team_id,
       nfl.status, nfl.home_score, nfl.away_score, nfl.overtime, nfl.neutral_site
FROM nfl_games nfl
JOIN games game ON game.game_id = nfl.game_id
"""


_SELECT_SOURCE_GAME = """
SELECT src.source_name, src.external_game_id, nfl.season, nfl.season_type,
       nfl.week, nfl.week_label, nfl.scheduled_start_time,
       home_source.external_team_id, away_source.external_team_id,
       nfl.status, nfl.home_score, nfl.away_score, nfl.overtime, nfl.neutral_site
FROM nfl_games nfl
JOIN games game ON game.game_id = nfl.game_id
JOIN game_sources src ON src.game_id = nfl.game_id
JOIN nfl_team_sources home_source ON home_source.team_id = game.home_team_id
    AND home_source.source_name = src.source_name
JOIN nfl_team_sources away_source ON away_source.team_id = game.away_team_id
    AND away_source.source_name = src.source_name
"""


def _canonical_game_from_row(row: tuple[Any, ...]) -> NflGame:
    return NflGame(
        game_id=row[0], season=row[1], season_type=NflSeasonType(row[2]),
        week=row[3], week_label=row[4], scheduled_start_time=row[5],
        home_team_id=row[6], away_team_id=row[7],
        status=NflGameStatus(row[8]), home_score=row[9], away_score=row[10],
        overtime=row[11], neutral_site=row[12],
    )


def _game_from_row(row: tuple[Any, ...]) -> NflGameSourceRecord:
    return NflGameSourceRecord(
        source_name=row[0], external_game_id=row[1], season=row[2],
        season_type=NflSeasonType(row[3]), week=row[4], week_label=row[5],
        scheduled_start_time=row[6], home_external_team_id=row[7],
        away_external_team_id=row[8], status=NflGameStatus(row[9]),
        home_score=row[10], away_score=row[11], overtime=row[12],
        neutral_site=row[13],
    )
