from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any

from psycopg2.extras import Json

from sportsmodel.database.nfl_game_repository import (
    persist_nfl_game,
    record_nfl_game_observation,
)
from sportsmodel.database.nfl_team_repository import resolve_nfl_team_by_source
from sportsmodel.nfl.models import NflSeasonType
from sportsmodel.nfl.nflverse_parser import (
    REVIEWED_TIMESTAMP_OVERRIDES,
    SOURCE_NAME,
    parse_nflverse_game_records,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class NflIngestionResult:
    nfl_ingestion_run_id: int
    rows_received: int
    rows_processed: int
    rows_inserted: int
    rows_updated: int
    rows_quarantined: int


def ingest_nflverse_games(
    cursor: Any,
    *,
    rows: Iterable[Mapping[str, Any]],
    team_identities: Mapping[str, str],
    source_asset: str,
    source_sha256: str,
    retrieved_at: datetime,
    season_from: int = 2018,
    season_to: int = 2025,
    include_preseason: bool = False,
) -> NflIngestionResult:
    """Thin nflverse adapter over provider-neutral canonical persistence.

    Data retrieval is intentionally outside this function. Every call records a
    new run and retains one observation per accepted input row for that run.
    """
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")
    if not _SHA256.fullmatch(source_sha256):
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    if season_from > season_to:
        raise ValueError("season_from cannot exceed season_to")

    materialized = tuple(rows)
    selected = tuple(
        row for row in materialized
        if season_from <= _row_season(row) <= season_to
        and (include_preseason or row.get("game_type") != "PRE")
    )
    run_id = _start_run(
        cursor,
        source_asset=source_asset,
        source_sha256=source_sha256,
        retrieved_at=retrieved_at,
        rows_received=len(materialized),
    )
    inserted = updated = 0
    try:
        for row in selected:
            record = parse_nflverse_game_records(
                (row,), team_identities=team_identities
            )[0]
            home = resolve_nfl_team_by_source(
                cursor,
                source_name=record.source_name,
                external_team_id=record.home_external_team_id,
            )
            away = resolve_nfl_team_by_source(
                cursor,
                source_name=record.source_name,
                external_team_id=record.away_external_team_id,
            )
            game_id, was_inserted = persist_nfl_game(
                cursor,
                record=record,
                home_team_id=home.team_id,
                away_team_id=away.team_id,
            )
            inserted += int(was_inserted)
            updated += int(not was_inserted)
            raw_json = _canonical_json(row)
            override = REVIEWED_TIMESTAMP_OVERRIDES.get(
                (record.source_name, record.external_game_id)
            )
            record_nfl_game_observation(
                cursor,
                nfl_ingestion_run_id=run_id,
                game_id=game_id,
                source_name=record.source_name,
                external_game_id=record.external_game_id,
                provider_home_external_team_id=record.home_external_team_id,
                provider_away_external_team_id=record.away_external_team_id,
                provider_gameday=str(row.get("gameday", "")),
                provider_gametime=str(row.get("gametime", "")),
                provider_game_type=str(row.get("game_type", "")),
                provider_week=str(row.get("week", "")),
                raw_payload=Json(dict(row), dumps=_canonical_json),
                raw_row_sha256=sha256(raw_json.encode("utf-8")).hexdigest(),
                observed_at=retrieved_at,
                anomaly_state="overridden" if override else "none",
                anomaly_reason=override.reason if override else None,
                override_provenance=override.provenance if override else None,
            )
    except Exception as error:
        _finish_run(
            cursor,
            run_id=run_id,
            status="failed",
            processed=inserted + updated,
            inserted=inserted,
            updated=updated,
            error_message=str(error),
        )
        raise

    _finish_run(
        cursor,
        run_id=run_id,
        status="completed",
        processed=len(selected),
        inserted=inserted,
        updated=updated,
        error_message=None,
    )
    return NflIngestionResult(
        nfl_ingestion_run_id=run_id,
        rows_received=len(materialized),
        rows_processed=len(selected),
        rows_inserted=inserted,
        rows_updated=updated,
        rows_quarantined=0,
    )


def _start_run(
    cursor: Any, *, source_asset: str, source_sha256: str,
    retrieved_at: datetime, rows_received: int
) -> int:
    cursor.execute(
        """
        INSERT INTO nfl_ingestion_runs (
            source_name, source_asset, retrieved_at, source_sha256, rows_received
        ) VALUES (%s, %s, %s, %s, %s)
        RETURNING nfl_ingestion_run_id;
        """,
        (SOURCE_NAME, source_asset, retrieved_at, source_sha256, rows_received),
    )
    return cursor.fetchone()[0]


def _finish_run(
    cursor: Any, *, run_id: int, status: str, processed: int,
    inserted: int, updated: int, error_message: str | None
) -> None:
    cursor.execute(
        """
        UPDATE nfl_ingestion_runs SET
            completed_at = CURRENT_TIMESTAMP, status = %s,
            rows_processed = %s, rows_inserted = %s, rows_updated = %s,
            error_message = %s
        WHERE nfl_ingestion_run_id = %s;
        """,
        (status, processed, inserted, updated, error_message, run_id),
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _row_season(row: Mapping[str, Any]) -> int:
    try:
        return int(row.get("season"))
    except (TypeError, ValueError) as error:
        raise ValueError("season must be an integer") from error
