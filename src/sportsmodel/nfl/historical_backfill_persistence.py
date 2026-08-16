"""Validated NFL historical persistence orchestration and integrity audit."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sportsmodel.nfl.game_persistence import (
    NflIngestionResult,
    ingest_nflverse_games,
)
from sportsmodel.nfl.historical_backfill_cli import (
    APPROVED_SEASON_RANGE,
    AssetProvenance,
    PreparedHistoricalBackfill,
)
from sportsmodel.nfl.team_statistics_persistence import (
    ingest_nflverse_team_game_statistics,
)


class HistoricalBackfillValidationError(ValueError):
    """Persistence was refused because the dry-run validation gate failed."""


@dataclass(frozen=True)
class AnnualTeamStatisticsResult:
    season: int
    source_asset: str
    source_sha256: str
    ingestion: NflIngestionResult


@dataclass(frozen=True)
class TeamStatisticsBackfillResult:
    annual_results: tuple[AnnualTeamStatisticsResult, ...]
    processed: int
    inserted: int
    updated: int


@dataclass(frozen=True)
class IntegrityCheck:
    name: str
    passed: bool
    actual: Any
    expected: Any
    detail: str = ""


@dataclass(frozen=True)
class HistoricalBackfillIntegrity:
    checks: tuple[IntegrityCheck, ...]
    failed_checks: tuple[str, ...]
    ready: bool


@dataclass(frozen=True)
class HistoricalBackfillPersistenceResult:
    schedule: NflIngestionResult
    team_statistics: TeamStatisticsBackfillResult
    integrity: HistoricalBackfillIntegrity


@dataclass(frozen=True)
class ValidatedBackfillProvenance:
    schedule: AssetProvenance
    teams: AssetProvenance
    annual_team_statistics: tuple[AssetProvenance, ...]
    retrieved_at: datetime


GameIngest = Callable[..., NflIngestionResult]
StatisticsIngest = Callable[..., NflIngestionResult]


def persist_validated_historical_backfill(
    connection: Any,
    *,
    prepared: PreparedHistoricalBackfill,
    game_ingest: GameIngest = ingest_nflverse_games,
    statistics_ingest: StatisticsIngest = ingest_nflverse_team_game_statistics,
    audit: Callable[..., HistoricalBackfillIntegrity] | None = None,
) -> HistoricalBackfillPersistenceResult:
    """Persist one already validated, immutable-in-memory asset snapshot."""

    validated_provenance = validate_prepared_for_persistence(prepared)
    retrieved_at = validated_provenance.retrieved_at
    schedule_asset = validated_provenance.schedule
    schedule_result = game_ingest(
        connection,
        rows=prepared.plan.accepted_schedule_rows,
        team_identities=prepared.team_identities,
        source_asset=schedule_asset.path,
        source_sha256=schedule_asset.sha256,
        retrieved_at=retrieved_at,
        season_from=prepared.plan.season_from,
        season_to=prepared.plan.season_to,
        include_preseason=False,
    )

    rows_by_season: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in prepared.plan.accepted_team_statistics_rows:
        rows_by_season[int(row["season"])].append(row)
    annual: list[AnnualTeamStatisticsResult] = []
    for asset in validated_provenance.annual_team_statistics:
        season = asset.season
        assert season is not None
        ingestion = statistics_ingest(
            connection,
            rows=tuple(rows_by_season.get(season, ())),
            team_identities=prepared.team_identities,
            source_asset=asset.path,
            source_sha256=asset.sha256,
            retrieved_at=retrieved_at,
        )
        annual.append(AnnualTeamStatisticsResult(
            season=season,
            source_asset=asset.path,
            source_sha256=asset.sha256,
            ingestion=ingestion,
        ))

    stats_result = TeamStatisticsBackfillResult(
        annual_results=tuple(annual),
        processed=sum(item.ingestion.rows_processed for item in annual),
        inserted=sum(item.ingestion.rows_inserted for item in annual),
        updated=sum(item.ingestion.rows_updated for item in annual),
    )
    run_ids = (schedule_result.nfl_ingestion_run_id,) + tuple(
        item.ingestion.nfl_ingestion_run_id for item in annual
    )
    audit_function = audit or audit_historical_backfill_integrity
    integrity = audit_function(
        connection,
        season_from=prepared.plan.season_from,
        season_to=prepared.plan.season_to,
        run_ids=run_ids,
        schedule_run_id=schedule_result.nfl_ingestion_run_id,
        expected_game_count=len(prepared.plan.accepted_schedule_rows),
        expected_statistics_count=len(
            prepared.plan.accepted_team_statistics_rows
        ),
        team_identities=prepared.team_identities,
    )
    return HistoricalBackfillPersistenceResult(
        schedule=schedule_result,
        team_statistics=stats_result,
        integrity=integrity,
    )


def audit_historical_backfill_integrity(
    connection: Any,
    *,
    season_from: int,
    season_to: int,
    run_ids: tuple[int, ...],
    schedule_run_id: int,
    expected_game_count: int,
    expected_statistics_count: int,
    team_identities: Mapping[str, str],
) -> HistoricalBackfillIntegrity:
    """Audit canonical state and only the ingestion runs from this execution."""

    checks: list[IntegrityCheck] = []
    scope = (season_from, season_to)
    with connection.cursor() as cursor:
        game_count = _scalar(cursor,
            "SELECT COUNT(*) FROM nfl_games WHERE season BETWEEN %s AND %s", scope)
        source_count = _scalar(cursor, """
            SELECT COUNT(*) FROM game_sources source
            JOIN nfl_games nfl ON nfl.game_id = source.game_id
            WHERE source.source_name = 'nflverse'
              AND nfl.season BETWEEN %s AND %s
        """, scope)
        stat_count = _scalar(cursor, """
            SELECT COUNT(*) FROM nfl_team_game_statistics stats
            JOIN nfl_games nfl ON nfl.game_id = stats.game_id
            WHERE nfl.season BETWEEN %s AND %s
        """, scope)
        profile_count = _scalar(cursor, "SELECT COUNT(*) FROM nfl_team_profiles")
        team_source_count = _scalar(cursor,
            "SELECT COUNT(*) FROM nfl_team_sources WHERE source_name = 'nflverse'")
        _add(checks, "historical_nfl_games_count", game_count, expected_game_count)
        _add(checks, "nflverse_game_identity_count", source_count, expected_game_count)
        _add(checks, "team_statistics_count", stat_count, expected_statistics_count)
        _add(checks, "nfl_team_profile_count", profile_count, 32)
        _add(checks, "nflverse_team_source_count", team_source_count, 32)

        cursor.execute("""
            WITH per_game AS (
                SELECT nfl.game_id, COUNT(stats.nfl_team_game_statistics_id) AS n
                FROM nfl_games nfl
                LEFT JOIN nfl_team_game_statistics stats ON stats.game_id = nfl.game_id
                WHERE nfl.season BETWEEN %s AND %s
                GROUP BY nfl.game_id
            )
            SELECT COUNT(*) FILTER (WHERE n = 0),
                   COUNT(*) FILTER (WHERE n = 1),
                   COUNT(*) FILTER (WHERE n > 2),
                   COUNT(*) FILTER (WHERE n = 2)
            FROM per_game
        """, scope)
        zero, one, over_two, exactly_two = cursor.fetchone()
        _add(checks, "games_with_zero_stats", zero, 0)
        _add(checks, "games_with_one_stat", one, 0)
        _add(checks, "games_with_more_than_two_stats", over_two, 0)
        _add(checks, "games_with_exactly_two_stats", exactly_two, expected_game_count)

        participant_mismatch = _scalar(cursor, """
            SELECT COUNT(*) FROM nfl_team_game_statistics stats
            JOIN nfl_games nfl ON nfl.game_id = stats.game_id
            JOIN games game ON game.game_id = nfl.game_id
            WHERE nfl.season BETWEEN %s AND %s
              AND stats.team_id NOT IN (game.home_team_id, game.away_team_id)
        """, scope)
        duplicate_stats = _scalar(cursor, """
            SELECT COUNT(*) FROM (
                SELECT stats.game_id, stats.team_id
                FROM nfl_team_game_statistics stats
                JOIN nfl_games nfl ON nfl.game_id = stats.game_id
                WHERE nfl.season BETWEEN %s AND %s
                GROUP BY stats.game_id, stats.team_id HAVING COUNT(*) > 1
            ) duplicates
        """, scope)
        duplicate_external = _scalar(cursor, """
            SELECT COUNT(*) FROM (
                SELECT source.external_game_id
                FROM game_sources source JOIN nfl_games nfl ON nfl.game_id = source.game_id
                WHERE source.source_name = 'nflverse'
                  AND nfl.season BETWEEN %s AND %s
                GROUP BY source.external_game_id HAVING COUNT(*) > 1
            ) duplicates
        """, scope)
        orphan_stats = _scalar(cursor, """
            SELECT COUNT(*) FROM nfl_team_game_statistics stats
            LEFT JOIN nfl_games nfl ON nfl.game_id = stats.game_id
            WHERE nfl.game_id IS NULL
        """)
        _add(checks, "stat_team_not_game_participant", participant_mismatch, 0)
        _add(checks, "duplicate_canonical_game_team_stats", duplicate_stats, 0)
        _add(checks, "duplicate_nflverse_external_game_ids", duplicate_external, 0)
        _add(checks, "orphan_stat_rows", orphan_stats, 0)

        if season_from <= 2022 <= season_to:
            cancelled = _external_game_count(cursor, "2022_17_BUF_CIN")
            _add(checks, "cancelled_2022_buf_cin_absent", cancelled, 0)
        if season_from <= 2018 <= season_to:
            for game_id in ("2018_07_TEN_LAC", "2018_08_PHI_JAX"):
                _add(checks, f"{game_id}_exists", _external_game_count(cursor, game_id), 1)
                _audit_wembley(cursor, checks, game_id, run_ids)

        cursor.execute("""
            SELECT status, rows_quarantined, nfl_ingestion_run_id
            FROM nfl_ingestion_runs
            WHERE nfl_ingestion_run_id = ANY(%s)
            ORDER BY nfl_ingestion_run_id
        """, (list(run_ids),))
        run_rows = cursor.fetchall()
        _add(checks, "execution_ingestion_run_count", len(run_rows), len(run_ids))
        _add(checks, "execution_completed_runs",
             sum(row[0] == "completed" for row in run_rows), len(run_ids))
        _add(checks, "execution_failed_runs",
             sum(row[0] == "failed" for row in run_rows), 0)
        schedule_quarantine = next(
            (row[1] for row in run_rows if row[2] == schedule_run_id), None
        )
        _add(checks, "schedule_quarantine_count", schedule_quarantine, 0)
        stat_failures = sum(
            row[0] != "completed" or row[1] != 0
            for row in run_rows if row[2] != schedule_run_id
        )
        _add(checks, "team_statistics_run_failures", stat_failures, 0)

        alias_pairs = (("OAK", "LV"), ("STL", "LAR"), ("SD", "LAC"))
        if (season_from, season_to) == APPROVED_SEASON_RANGE:
            aliases_ok = (
                all(
                    old in team_identities
                    and current in team_identities
                    and team_identities[old] == team_identities[current]
                    for old, current in alias_pairs
                )
                and "WAS" in team_identities
            )
        else:
            aliases_ok = all(
                team_identities.get(old) == team_identities.get(current)
                for old, current in alias_pairs if old in team_identities
            )
        _add(checks, "historical_aliases_resolve_to_franchises", aliases_ok, True)

    return build_integrity_result(checks)


def build_integrity_result(
    checks: list[IntegrityCheck] | tuple[IntegrityCheck, ...],
) -> HistoricalBackfillIntegrity:
    materialized = tuple(checks)
    failed = tuple(check.name for check in materialized if not check.passed)
    return HistoricalBackfillIntegrity(
        checks=materialized, failed_checks=failed, ready=not failed
    )


def _audit_wembley(
    cursor: Any, checks: list[IntegrityCheck], game_id: str,
    run_ids: tuple[int, ...],
) -> None:
    cursor.execute("""
        SELECT nfl.scheduled_start_time, observation.provider_gametime,
               observation.raw_payload->>'gametime', observation.anomaly_state
        FROM nfl_game_source_observations observation
        JOIN nfl_games nfl ON nfl.game_id = observation.game_id
        WHERE observation.external_game_id = %s
          AND observation.nfl_ingestion_run_id = ANY(%s)
        ORDER BY observation.nfl_game_source_observation_id DESC LIMIT 1
    """, (game_id, list(run_ids)))
    row = cursor.fetchone()
    observed = None if row is None else (
        row[0].astimezone(ZoneInfo("America/New_York")).strftime("%H:%M"),
        row[1], row[2], row[3],
    )
    _add(checks, f"{game_id}_wembley_override", observed,
         ("09:30", "21:30", "21:30", "overridden"))


def validate_prepared_for_persistence(
    prepared: PreparedHistoricalBackfill,
) -> ValidatedBackfillProvenance:
    """Apply the persistence gate without opening or using a connection."""
    report = prepared.report
    ready = report.get("backfill_ready") is True
    no_issues = report.get("reconciliation", {}).get("issue_count") == 0
    contract = report.get("approved_schedule_contract")
    if (prepared.plan.season_from, prepared.plan.season_to) == APPROVED_SEASON_RANGE:
        selected = len(prepared.plan.selected_schedule_rows)
        accepted = len(prepared.plan.accepted_schedule_rows)
        quarantined = len(prepared.plan.quarantined_schedule_rows)
        unique_ids = len({
            str(row.get("game_id"))
            for row in prepared.plan.selected_schedule_rows
            if row.get("game_id")
        })
        ready = ready and isinstance(contract, dict) and (
            contract.get("contract_satisfied") is True
        ) and (selected, accepted, quarantined, unique_ids) == (
            2227, 2227, 0, 2227
        )
    if not ready or not no_issues or not prepared.plan.is_valid:
        raise HistoricalBackfillValidationError(
            "Historical backfill validation gate is not ready; persistence refused"
        )
    schedule = _one_asset(prepared.provenance, "schedules", None)
    teams = _one_asset(prepared.provenance, "teams", None)
    annual = tuple(
        _one_asset(prepared.provenance, "team_statistics", season)
        for season in range(
            prepared.plan.season_from, prepared.plan.season_to + 1
        )
    )
    required_assets = (schedule, teams, *annual)
    timestamps = tuple(
        _aware_datetime(asset.retrieved_at) for asset in required_assets
    )
    if any(value != timestamps[0] for value in timestamps[1:]):
        raise HistoricalBackfillValidationError(
            "All required provenance assets must have the same retrieved_at"
        )
    return ValidatedBackfillProvenance(
        schedule=schedule,
        teams=teams,
        annual_team_statistics=annual,
        retrieved_at=timestamps[0],
    )


def _one_asset(
    provenance: tuple[AssetProvenance, ...], role: str, season: int | None
) -> AssetProvenance:
    matches = tuple(
        item for item in provenance
        if item.logical_role == role and item.season == season
    )
    if len(matches) != 1:
        raise HistoricalBackfillValidationError(
            f"Expected exactly one {role} provenance asset for season {season}"
        )
    return matches[0]


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise HistoricalBackfillValidationError(
            f"Invalid provenance retrieved_at: {value!r}"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HistoricalBackfillValidationError(
            "Validated retrieved_at is not timezone-aware"
        )
    return parsed


def _scalar(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    cursor.execute(sql, params)
    return cursor.fetchone()[0]


def _external_game_count(cursor: Any, external_game_id: str) -> int:
    return _scalar(cursor, """
        SELECT COUNT(*) FROM game_sources
        WHERE source_name = 'nflverse' AND external_game_id = %s
    """, (external_game_id,))


def _add(
    checks: list[IntegrityCheck], name: str, actual: Any, expected: Any
) -> None:
    checks.append(IntegrityCheck(
        name=name, passed=actual == expected, actual=actual, expected=expected
    ))
