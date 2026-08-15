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
    connection: Any,
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

    Data retrieval is intentionally outside this function. The run is committed
    before processing. Canonical writes and observations are one later atomic
    transaction; failure rolls them back before the run is durably failed.
    """
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")
    if not _SHA256.fullmatch(source_sha256):
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    if season_from > season_to:
        raise ValueError("season_from cannot exceed season_to")

    materialized = tuple(rows)
    with connection.cursor() as cursor:
        run_id = _start_run(
            cursor,
            source_asset=source_asset,
            source_sha256=source_sha256,
            retrieved_at=retrieved_at,
            rows_received=len(materialized),
        )
    connection.commit()

    inserted = updated = quarantined = processed = 0
    try:
        with connection.cursor() as cursor:
            for row in materialized:
                if not _row_is_selected(
                    row,
                    season_from=season_from,
                    season_to=season_to,
                    include_preseason=include_preseason,
                ):
                    continue
                processed += 1
                mismatch = _reviewed_override_mismatch(row)
                if mismatch is not None:
                    override, reason = mismatch
                    _record_observation(
                        cursor,
                        run_id=run_id,
                        game_id=None,
                        row=row,
                        team_identities=team_identities,
                        retrieved_at=retrieved_at,
                        anomaly_state="quarantined",
                        anomaly_reason=reason,
                        override_provenance=override.provenance,
                    )
                    quarantined += 1
                    continue

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
                override = REVIEWED_TIMESTAMP_OVERRIDES.get(
                    (record.source_name, record.external_game_id)
                )
                _record_observation(
                    cursor,
                    run_id=run_id,
                    game_id=game_id,
                    row=row,
                    team_identities=team_identities,
                    retrieved_at=retrieved_at,
                    anomaly_state="overridden" if override else "none",
                    anomaly_reason=override.reason if override else None,
                    override_provenance=override.provenance if override else None,
                )
    except Exception as error:
        connection.rollback()
        try:
            with connection.cursor() as cursor:
                _finish_run(
                    cursor,
                    run_id=run_id,
                    status="failed",
                    processed=processed,
                    inserted=0,
                    updated=0,
                    quarantined=0,
                    error_message=str(error),
                )
            connection.commit()
        except Exception as run_error:
            connection.rollback()
            error.add_note(
                f"Additionally failed to persist ingestion-run failure: {run_error}"
            )
        raise

    with connection.cursor() as cursor:
        _finish_run(
            cursor,
            run_id=run_id,
            status="completed",
            processed=processed,
            inserted=inserted,
            updated=updated,
            quarantined=quarantined,
            error_message=None,
        )
    connection.commit()
    return NflIngestionResult(
        nfl_ingestion_run_id=run_id,
        rows_received=len(materialized),
        rows_processed=processed,
        rows_inserted=inserted,
        rows_updated=updated,
        rows_quarantined=quarantined,
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
    inserted: int, updated: int, quarantined: int, error_message: str | None
) -> None:
    cursor.execute(
        """
        UPDATE nfl_ingestion_runs SET
            completed_at = CURRENT_TIMESTAMP, status = %s,
            rows_processed = %s, rows_inserted = %s, rows_updated = %s,
            rows_quarantined = %s, error_message = %s
        WHERE nfl_ingestion_run_id = %s;
        """,
        (
            status, processed, inserted, updated, quarantined,
            error_message, run_id,
        ),
    )


def _record_observation(
    cursor: Any, *, run_id: int, game_id: int | None,
    row: Mapping[str, Any], team_identities: Mapping[str, str],
    retrieved_at: datetime, anomaly_state: str,
    anomaly_reason: str | None, override_provenance: str | None,
) -> None:
    raw_json = _canonical_json(row)
    home_alias = str(row.get("home_team", "")).strip()
    away_alias = str(row.get("away_team", "")).strip()
    record_nfl_game_observation(
        cursor,
        nfl_ingestion_run_id=run_id,
        game_id=game_id,
        source_name=SOURCE_NAME,
        external_game_id=str(row.get("game_id", "")).strip(),
        provider_home_external_team_id=team_identities.get(home_alias),
        provider_away_external_team_id=team_identities.get(away_alias),
        provider_gameday=str(row.get("gameday", "")),
        provider_gametime=str(row.get("gametime", "")),
        provider_game_type=str(row.get("game_type", "")),
        provider_week=str(row.get("week", "")),
        raw_payload=Json(dict(row), dumps=_canonical_json),
        raw_row_sha256=sha256(raw_json.encode("utf-8")).hexdigest(),
        observed_at=retrieved_at,
        anomaly_state=anomaly_state,
        anomaly_reason=anomaly_reason,
        override_provenance=override_provenance,
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _row_is_selected(
    row: Mapping[str, Any], *, season_from: int, season_to: int,
    include_preseason: bool,
) -> bool:
    try:
        season = int(row.get("season"))
    except (TypeError, ValueError) as error:
        raise ValueError("season must be an integer") from error
    return (
        season_from <= season <= season_to
        and (include_preseason or row.get("game_type") != "PRE")
    )


def _reviewed_override_mismatch(row: Mapping[str, Any]):
    external_game_id = str(row.get("game_id", "")).strip()
    override = REVIEWED_TIMESTAMP_OVERRIDES.get((SOURCE_NAME, external_game_id))
    if override is None:
        return None
    received = (
        str(row.get("gameday", "")).strip(),
        str(row.get("gametime", "")).strip(),
    )
    expected = (override.provider_gameday, override.provider_gametime)
    if received == expected:
        return None
    reason = (
        "Reviewed timestamp override evidence mismatch; canonical persistence "
        f"was skipped. Expected {expected[0]} {expected[1]}, received "
        f"{received[0]} {received[1]}."
    )
    return override, reason
