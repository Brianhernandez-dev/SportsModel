from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any

from psycopg2.extras import Json

from sportsmodel.database.nfl_team_game_statistics_repository import (
    record_nfl_team_game_statistics_observation,
    resolve_statistics_game,
    upsert_nfl_team_game_statistics,
)
from sportsmodel.database.nfl_team_repository import resolve_nfl_team_by_source
from sportsmodel.nfl.game_persistence import NflIngestionResult, _finish_run, _start_run
from sportsmodel.nfl.nflverse_parser import (
    SOURCE_NAME, parse_nflverse_team_game_statistics_records,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def ingest_nflverse_team_game_statistics(
    connection: Any, *, rows: Iterable[Mapping[str, Any]],
    team_identities: Mapping[str, str], source_asset: str,
    source_sha256: str, retrieved_at: datetime,
) -> NflIngestionResult:
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")
    if not _SHA256.fullmatch(source_sha256):
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    materialized = tuple(rows)
    with connection.cursor() as cursor:
        run_id = _start_run(cursor, source_asset=source_asset,
                            source_sha256=source_sha256, retrieved_at=retrieved_at,
                            rows_received=len(materialized))
    connection.commit()
    inserted = updated = processed = 0
    try:
        with connection.cursor() as cursor:
            for row in materialized:
                processed += 1
                record = parse_nflverse_team_game_statistics_records(
                    (row,), team_identities=team_identities)[0]
                team = resolve_nfl_team_by_source(
                    cursor, source_name=record.source_name,
                    external_team_id=record.team_external_id)
                opponent = resolve_nfl_team_by_source(
                    cursor, source_name=record.source_name,
                    external_team_id=record.opponent_external_id)
                game_id = resolve_statistics_game(
                    cursor, record=record, team_id=team.team_id,
                    opponent_team_id=opponent.team_id)
                statistics_id, was_inserted = upsert_nfl_team_game_statistics(
                    cursor, game_id=game_id, team_id=team.team_id, record=record)
                inserted += int(was_inserted)
                updated += int(not was_inserted)
                raw_json = canonical_json(row)
                record_nfl_team_game_statistics_observation(
                    cursor, nfl_ingestion_run_id=run_id,
                    nfl_team_game_statistics_id=statistics_id, game_id=game_id,
                    team_id=team.team_id, source_name=SOURCE_NAME,
                    external_game_id=record.external_game_id,
                    provider_team_external_id=record.team_external_id,
                    provider_opponent_external_id=record.opponent_external_id,
                    raw_payload=Json(dict(row), dumps=canonical_json),
                    raw_row_sha256=sha256(raw_json.encode("utf-8")).hexdigest(),
                    observed_at=retrieved_at)
    except Exception as error:
        connection.rollback()
        try:
            with connection.cursor() as cursor:
                _finish_run(cursor, run_id=run_id, status="failed",
                            processed=processed, inserted=0, updated=0,
                            quarantined=0, error_message=str(error))
            connection.commit()
        except Exception as run_error:
            connection.rollback()
            error.add_note(f"Additionally failed to persist ingestion-run failure: {run_error}")
        raise
    with connection.cursor() as cursor:
        _finish_run(cursor, run_id=run_id, status="completed", processed=processed,
                    inserted=inserted, updated=updated, quarantined=0,
                    error_message=None)
    connection.commit()
    return NflIngestionResult(run_id, len(materialized), processed, inserted,
                              updated, 0)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
