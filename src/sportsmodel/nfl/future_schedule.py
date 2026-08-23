"""Fail-closed planning for one season of future nflverse schedule data."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sportsmodel.nfl.game_persistence import ingest_nflverse_games
from sportsmodel.nfl.models import NflGameSourceRecord, NflGameStatus
from sportsmodel.nfl.nflverse_parser import (
    SOURCE_NAME,
    build_nflverse_team_identity_index,
    parse_nflverse_game_records,
    parse_nflverse_team_records,
)


REGULAR_GAME_TYPE = "REG"


@dataclass(frozen=True)
class FutureScheduleIssue:
    category: str
    external_game_id: str | None
    detail: str


@dataclass(frozen=True)
class FutureScheduleCandidate:
    source_row: Mapping[str, Any]
    record: NflGameSourceRecord
    disposition: str
    canonical_game_id: int | None


@dataclass(frozen=True)
class FutureSchedulePlan:
    season: int
    source_rows_discovered: int
    source_game_type_counts: tuple[tuple[str, int], ...]
    excluded_non_regular_rows: int
    candidates: tuple[FutureScheduleCandidate, ...]
    issues: tuple[FutureScheduleIssue, ...]
    team_identities: Mapping[str, str]

    @property
    def ready(self) -> bool:
        return not self.issues and bool(self.candidates)

    def count(self, disposition: str) -> int:
        return sum(
            candidate.disposition == disposition
            for candidate in self.candidates
        )

    @property
    def earliest_kickoff(self) -> datetime | None:
        return min(
            (candidate.record.scheduled_start_time for candidate in self.candidates),
            default=None,
        )

    @property
    def latest_kickoff(self) -> datetime | None:
        return max(
            (candidate.record.scheduled_start_time for candidate in self.candidates),
            default=None,
        )


@dataclass(frozen=True)
class FutureSchedulePersistenceResult:
    nfl_ingestion_run_id: int | None
    rows_processed: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int


def build_future_schedule_plan(
    cursor: Any,
    *,
    schedule_rows: Iterable[Mapping[str, Any]],
    team_rows: Iterable[Mapping[str, Any]],
    season: int,
) -> FutureSchedulePlan:
    """Compare one regular-season source snapshot with canonical state."""

    if season < 2026:
        raise ValueError("future schedule ingestion requires season 2026 or later")
    raw_rows = tuple(
        dict(row)
        for row in schedule_rows
        if _integer_or_none(row.get("season")) == season
    )
    type_counts = Counter(str(row.get("game_type", "")).strip() for row in raw_rows)
    eligible_rows = tuple(
        row for row in raw_rows if row.get("game_type") == REGULAR_GAME_TYPE
    )
    issues: list[FutureScheduleIssue] = []

    try:
        team_identities = build_nflverse_team_identity_index(
            parse_nflverse_team_records(team_rows)
        )
    except (TypeError, ValueError) as error:
        return FutureSchedulePlan(
            season=season,
            source_rows_discovered=len(raw_rows),
            source_game_type_counts=tuple(sorted(type_counts.items())),
            excluded_non_regular_rows=len(raw_rows) - len(eligible_rows),
            candidates=(),
            issues=(FutureScheduleIssue("team_asset", None, str(error)),),
            team_identities={},
        )

    ids = [str(row.get("game_id", "")).strip() for row in eligible_rows]
    for external_id, count in sorted(Counter(ids).items()):
        if not external_id or count > 1:
            issues.append(FutureScheduleIssue(
                "duplicate_or_missing_source_id",
                external_id or None,
                f"regular-season source ID occurs {count} time(s)",
            ))

    parsed: list[tuple[Mapping[str, Any], NflGameSourceRecord]] = []
    for row in eligible_rows:
        external_id = str(row.get("game_id", "")).strip() or None
        if _has_result_value(row):
            issues.append(FutureScheduleIssue(
                "not_future_unplayed",
                external_id,
                "future schedule rows must not contain scores or overtime",
            ))
            continue
        try:
            record = parse_nflverse_game_records(
                (row,), team_identities=team_identities
            )[0]
        except (TypeError, ValueError) as error:
            issues.append(FutureScheduleIssue(
                _parser_issue_category(error), external_id, str(error)
            ))
            continue
        if record.status is not NflGameStatus.UNPLAYED:
            issues.append(FutureScheduleIssue(
                "not_future_unplayed", external_id, "parsed row is not unplayed"
            ))
            continue
        parsed.append((row, record))

    canonical_keys = Counter(_record_identity(record) for _, record in parsed)
    for key, count in canonical_keys.items():
        if count > 1:
            issues.append(FutureScheduleIssue(
                "duplicate_canonical_source_candidate",
                None,
                f"source contains {count} rows for canonical identity {key!r}",
            ))

    external_team_ids = sorted({
        value
        for _, record in parsed
        for value in (
            record.home_external_team_id,
            record.away_external_team_id,
        )
    })
    if external_team_ids:
        cursor.execute(
            """
            SELECT external_team_id
            FROM nfl_team_sources
            WHERE source_name = %s
              AND external_team_id = ANY(%s)
            """,
            (SOURCE_NAME, external_team_ids),
        )
        known_production_ids = {str(row[0]) for row in cursor.fetchall()}
    else:
        known_production_ids = set()
    for external_id in sorted(set(external_team_ids) - known_production_ids):
        issues.append(FutureScheduleIssue(
            "unknown_production_team", external_id,
            "source team identity is absent from production canonical mappings",
        ))

    source_existing = _load_existing_source_games(
        cursor,
        external_ids=tuple(record.external_game_id for _, record in parsed),
    )
    canonical_existing = _load_canonical_season_games(cursor, season=season)
    candidates: list[FutureScheduleCandidate] = []
    for row, record in parsed:
        existing = source_existing.get(record.external_game_id)
        if existing is not None:
            mismatch = _existing_source_mismatch(existing, record)
            if mismatch is not None:
                issues.append(FutureScheduleIssue(
                    "source_identity_conflict", record.external_game_id, mismatch
                ))
                continue
            disposition = (
                "existing" if _existing_is_exact(existing, record) else "update"
            )
            candidates.append(FutureScheduleCandidate(
                row, record, disposition, int(existing[0])
            ))
            continue

        canonical_matches = tuple(
            game for game in canonical_existing
            if _canonical_row_identity(game) == _record_identity(record)
        )
        if canonical_matches:
            issues.append(FutureScheduleIssue(
                "canonical_game_without_source_identity",
                record.external_game_id,
                "matching canonical game already exists without this nflverse ID: "
                + ",".join(str(game[0]) for game in canonical_matches),
            ))
            continue
        candidates.append(FutureScheduleCandidate(row, record, "new", None))

    return FutureSchedulePlan(
        season=season,
        source_rows_discovered=len(raw_rows),
        source_game_type_counts=tuple(sorted(type_counts.items())),
        excluded_non_regular_rows=len(raw_rows) - len(eligible_rows),
        candidates=tuple(sorted(
            candidates,
            key=lambda item: (
                item.record.scheduled_start_time,
                item.record.external_game_id,
            ),
        )),
        issues=tuple(sorted(
            issues,
            key=lambda item: (item.category, item.external_game_id or "", item.detail),
        )),
        team_identities=team_identities,
    )


def persist_future_schedule(
    connection: Any,
    *,
    plan: FutureSchedulePlan,
    source_asset: str,
    source_sha256: str,
    retrieved_at: datetime,
) -> FutureSchedulePersistenceResult:
    """Persist only new/changed rows through the existing nflverse service."""

    if not plan.ready:
        raise ValueError("future schedule dry-run is not ready for persistence")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    writes = tuple(
        candidate.source_row
        for candidate in plan.candidates
        if candidate.disposition in {"new", "update"}
    )
    skipped = plan.count("existing")
    if not writes:
        return FutureSchedulePersistenceResult(None, 0, 0, 0, skipped)
    result = ingest_nflverse_games(
        connection,
        rows=writes,
        team_identities=plan.team_identities,
        source_asset=source_asset,
        source_sha256=source_sha256,
        retrieved_at=retrieved_at,
        season_from=plan.season,
        season_to=plan.season,
        include_preseason=False,
    )
    if result.rows_processed != len(writes) or result.rows_quarantined:
        raise RuntimeError("future schedule persistence did not process cleanly")
    return FutureSchedulePersistenceResult(
        nfl_ingestion_run_id=result.nfl_ingestion_run_id,
        rows_processed=result.rows_processed,
        rows_inserted=result.rows_inserted,
        rows_updated=result.rows_updated,
        rows_skipped=skipped,
    )


def _load_existing_source_games(
    cursor: Any, *, external_ids: tuple[str, ...]
) -> dict[str, tuple[Any, ...]]:
    if not external_ids:
        return {}
    cursor.execute(
        """
        SELECT source.external_game_id, nfl.game_id, nfl.season,
               nfl.season_type, nfl.week, nfl.week_label,
               nfl.scheduled_start_time, home.external_team_id,
               away.external_team_id, nfl.status, nfl.neutral_site
        FROM game_sources AS source
        JOIN nfl_games AS nfl ON nfl.game_id = source.game_id
        JOIN games AS game ON game.game_id = nfl.game_id
        JOIN nfl_team_sources AS home
          ON home.team_id = game.home_team_id AND home.source_name = %s
        JOIN nfl_team_sources AS away
          ON away.team_id = game.away_team_id AND away.source_name = %s
        WHERE source.source_name = %s
          AND source.external_game_id = ANY(%s)
        """,
        (SOURCE_NAME, SOURCE_NAME, SOURCE_NAME, list(external_ids)),
    )
    return {str(row[0]): tuple(row[1:]) for row in cursor.fetchall()}


def _load_canonical_season_games(cursor: Any, *, season: int) -> tuple[tuple[Any, ...], ...]:
    cursor.execute(
        """
        SELECT nfl.game_id, nfl.season, nfl.season_type, nfl.week,
               home.external_team_id, away.external_team_id
        FROM nfl_games AS nfl
        JOIN games AS game ON game.game_id = nfl.game_id
        JOIN nfl_team_sources AS home
          ON home.team_id = game.home_team_id AND home.source_name = %s
        JOIN nfl_team_sources AS away
          ON away.team_id = game.away_team_id AND away.source_name = %s
        WHERE nfl.season = %s
        """,
        (SOURCE_NAME, SOURCE_NAME, season),
    )
    return tuple(tuple(row) for row in cursor.fetchall())


def _existing_source_mismatch(
    existing: tuple[Any, ...], record: NflGameSourceRecord
) -> str | None:
    immutable = existing[1:5] + existing[6:8]
    expected = (
        record.season,
        record.season_type.value,
        record.week,
        record.week_label,
        record.home_external_team_id,
        record.away_external_team_id,
    )
    if immutable != expected:
        return f"existing immutable identity {immutable!r} != source {expected!r}"
    if existing[8] == NflGameStatus.FINAL.value:
        return "future schedule import refuses to update a completed game"
    return None


def _existing_is_exact(
    existing: tuple[Any, ...], record: NflGameSourceRecord
) -> bool:
    return (
        existing[5] == record.scheduled_start_time
        and existing[8] == record.status.value
        and bool(existing[9]) == record.neutral_site
    )


def _record_identity(record: NflGameSourceRecord) -> tuple[Any, ...]:
    return (
        record.season,
        record.season_type.value,
        record.week,
        record.home_external_team_id,
        record.away_external_team_id,
    )


def _canonical_row_identity(row: tuple[Any, ...]) -> tuple[Any, ...]:
    return (row[1], row[2], row[3], row[4], row[5])


def _has_result_value(row: Mapping[str, Any]) -> bool:
    return any(
        value is not None and str(value).strip() != ""
        for value in (
            row.get("home_score"),
            row.get("away_score"),
            row.get("overtime"),
        )
    )


def _integer_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parser_issue_category(error: Exception) -> str:
    message = str(error).lower()
    if "unknown nflverse team" in message:
        return "unknown_team"
    if "gameday" in message or "gametime" in message:
        return "invalid_kickoff"
    if "home and away" in message:
        return "invalid_orientation"
    return "parser_rejection"


def utc_text(value: datetime | None) -> str:
    if value is None:
        return "NONE"
    return value.astimezone(timezone.utc).isoformat()
