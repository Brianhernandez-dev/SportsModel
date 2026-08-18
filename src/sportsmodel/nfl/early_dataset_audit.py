from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.database.nfl_game_repository import list_nfl_games_by_season_range
from sportsmodel.database.nfl_team_game_statistics_repository import (
    list_all_nfl_completed_history,
)
from sportsmodel.nfl.dataset_audit import (
    HistoryAuditTrace,
    SnapshotNflTeamHistoryRepository,
)
from sportsmodel.nfl.early_features import (
    NFL_EARLY_MONEYLINE_FEATURE_NAMES,
    NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION,
    NFLMoneylineRoute,
)
from sportsmodel.nfl.early_moneyline_dataset import (
    NFL_EARLY_DEVELOPMENT_SEASON_FROM,
    NFL_EARLY_DEVELOPMENT_SEASON_TO,
    NFLEarlyMoneylineDatasetBuildResult,
    NFLEarlyMoneylineTrainingDatasetBuilder,
)
from sportsmodel.nfl.features import HistoricalNflTeamGame, NFLFeatureDataProvider
from sportsmodel.nfl.models import NflGame, NflGameStatus, NflSeasonType


@dataclass(frozen=True)
class NFLEarlyHistoricalDatasetAuditOutcome:
    canonical_games: tuple[NflGame, ...]
    dataset: NFLEarlyMoneylineDatasetBuildResult
    report: dict[str, Any]
    fingerprint: str


@dataclass(frozen=True)
class _ExpectedChannel:
    games: tuple[HistoricalNflTeamGame, ...]
    games_played: int
    win_percentage: float | None
    average_points_for: float | None
    average_points_against: float | None
    average_point_differential: float | None
    average_turnover_differential: float | None

    @property
    def source_game_ids(self) -> tuple[int, ...]:
        return tuple(item.game.game_id for item in self.games)

    @property
    def source_kickoffs(self) -> tuple[datetime, ...]:
        return tuple(item.game.scheduled_start_time for item in self.games)


def build_and_audit_production_early_dataset(
    *,
    season_from: int = NFL_EARLY_DEVELOPMENT_SEASON_FROM,
    season_to: int = NFL_EARLY_DEVELOPMENT_SEASON_TO,
    connection_factory=get_connection,
) -> NFLEarlyHistoricalDatasetAuditOutcome:
    _validate_development_range(season_from, season_to)
    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            games = list_nfl_games_by_season_range(
                cursor,
                season_from=season_from,
                season_to=season_to,
            )
            history = list_all_nfl_completed_history(
                cursor,
                season_from=season_from - 1,
                season_to=season_to,
            )
    finally:
        connection.close()

    snapshot = SnapshotNflTeamHistoryRepository(history)
    builder = NFLEarlyMoneylineTrainingDatasetBuilder(
        season_from=season_from,
        season_to=season_to,
        provider_factory=lambda game: NFLFeatureDataProvider(
            game,
            repository=snapshot.for_target(game),
        ),
    )
    dataset = builder.build(games)
    report = audit_generated_early_dataset(
        games,
        dataset,
        snapshot.traces,
        canonical_history=history,
        season_from=season_from,
        season_to=season_to,
    )
    return NFLEarlyHistoricalDatasetAuditOutcome(
        canonical_games=games,
        dataset=dataset,
        report=report,
        fingerprint=early_dataset_fingerprint(dataset.rows),
    )


def audit_generated_early_dataset(
    games: Iterable[NflGame],
    dataset: NFLEarlyMoneylineDatasetBuildResult,
    traces: Iterable[HistoryAuditTrace],
    *,
    canonical_history: Iterable[HistoricalNflTeamGame],
    season_from: int = NFL_EARLY_DEVELOPMENT_SEASON_FROM,
    season_to: int = NFL_EARLY_DEVELOPMENT_SEASON_TO,
) -> dict[str, Any]:
    _validate_development_range(season_from, season_to)
    ordered_games = tuple(sorted(
        games,
        key=lambda game: (game.scheduled_start_time, game.game_id),
    ))
    history = tuple(canonical_history)
    trace_items = tuple(traces)
    findings: list[dict[str, str]] = []
    game_by_id = {game.game_id: game for game in ordered_games}

    _audit_canonical_inputs(
        ordered_games,
        history,
        season_from,
        season_to,
        findings,
    )
    expected = _expected_channels(ordered_games, history)
    expected_early_ids = _audit_target_population(
        ordered_games,
        dataset,
        expected,
        findings,
    )
    _audit_traces(
        ordered_games,
        trace_items,
        history,
        findings,
    )
    _audit_rows(
        dataset.rows,
        expected_early_ids,
        game_by_id,
        expected,
        findings,
    )

    return {
        "development_seasons": {
            "from": season_from,
            "to": season_to,
        },
        "canonical_target_counts_by_season": _canonical_counts(ordered_games),
        "early_route_counts_by_season": _count_by(
            dataset.rows,
            "target_season",
        ),
        "dataset_rows": len(dataset.rows),
        "excluded_ties": dataset.ties_skipped,
        "excluded_nonfinal": dataset.nonfinal_games_skipped,
        "excluded_mature_route": dataset.mature_route_games_skipped,
        "minimum_current_prior_game_counts": _count_by(
            dataset.rows,
            "minimum_current_prior_games",
        ),
        "prior_season_source_coverage_by_target_season": (
            _prior_coverage_by_season(dataset.rows)
        ),
        "prior_season_games_used_distribution": _team_count_distribution(
            dataset.rows,
            "prior_season_games_played",
        ),
        "current_season_history_distribution": _team_count_distribution(
            dataset.rows,
            "current_season_prior_games",
        ),
        "numeric_feature_null_rates": _feature_null_rates(dataset.rows),
        "feature_schema_versions": sorted({
            str(row["feature_schema_version"])
            for row in dataset.rows
        }),
        "integrity_findings": findings,
        "integrity_passed": not findings,
    }


def early_dataset_fingerprint(rows: Iterable[dict[str, object]]) -> str:
    payload = json.dumps(
        [_canonical_value(row) for row in rows],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _validate_development_range(season_from: int, season_to: int) -> None:
    if season_from < NFL_EARLY_DEVELOPMENT_SEASON_FROM:
        raise ValueError("early audit cannot query seasons before 2019")
    if season_to > NFL_EARLY_DEVELOPMENT_SEASON_TO:
        raise ValueError("early audit cannot query or inspect seasons after 2024")
    if season_from > season_to:
        raise ValueError("season_from cannot exceed season_to")


def _audit_canonical_inputs(
    games,
    history,
    season_from,
    season_to,
    findings,
) -> None:
    for game in games:
        _finding_if(
            not season_from <= game.season <= season_to,
            findings,
            "target_season_outside_guard",
            f"target game {game.game_id} has season {game.season}",
        )
    history_keys = [
        (item.team_statistics.team_id, item.game.game_id)
        for item in history
    ]
    for key, count in Counter(history_keys).items():
        _finding_if(
            count != 1,
            findings,
            "duplicate_canonical_history",
            f"team/game {key} appears {count} times",
        )
    for item in history:
        game = item.game
        team_id = item.team_statistics.team_id
        expected_opponent = (
            game.away_team_id
            if team_id == game.home_team_id
            else game.home_team_id
        )
        _finding_if(
            game.status is not NflGameStatus.FINAL,
            findings,
            "nonfinal_canonical_history",
            f"history game {game.game_id} is not final",
        )
        _finding_if(
            team_id not in {game.home_team_id, game.away_team_id},
            findings,
            "history_nonparticipant",
            f"history team {team_id} is not in game {game.game_id}",
        )
        _finding_if(
            item.opponent_statistics.team_id != expected_opponent,
            findings,
            "history_opponent_mismatch",
            f"history opponent is wrong for team {team_id} game {game.game_id}",
        )


def _expected_channels(games, history):
    expected: dict[tuple[int, int, str], _ExpectedChannel] = {}
    for target in games:
        if (
            target.status is not NflGameStatus.FINAL
            or target.home_score == target.away_score
        ):
            continue
        for team_id in (target.home_team_id, target.away_team_id):
            current = _eligible_history(
                history,
                team_id=team_id,
                season=target.season,
                cutoff=target.scheduled_start_time,
            )
            prior_complete = _eligible_history(
                history,
                team_id=team_id,
                season=target.season - 1,
                cutoff=target.scheduled_start_time,
            )
            prior_regular = tuple(
                item
                for item in prior_complete
                if item.game.season_type is NflSeasonType.REGULAR
            )
            expected[(target.game_id, team_id, "current")] = _aggregate(
                current
            )
            expected[(target.game_id, team_id, "prior")] = _aggregate(
                prior_regular
            )
    return expected


def _eligible_history(history, *, team_id, season, cutoff):
    return tuple(sorted(
        (
            item
            for item in history
            if item.team_statistics.team_id == team_id
            and item.game.status is NflGameStatus.FINAL
            and item.game.season == season
            and item.game.scheduled_start_time < cutoff
        ),
        key=lambda item: (
            item.game.scheduled_start_time,
            item.game.game_id,
        ),
        reverse=True,
    ))


def _audit_target_population(games, dataset, expected, findings):
    final_non_ties = tuple(
        game
        for game in games
        if game.status is NflGameStatus.FINAL
        and game.home_score != game.away_score
    )
    early_ids: set[int] = set()
    mature_count = 0
    for game in final_non_ties:
        home_count = expected[
            (game.game_id, game.home_team_id, "current")
        ].games_played
        away_count = expected[
            (game.game_id, game.away_team_id, "current")
        ].games_played
        is_early = home_count < 3 or away_count < 3
        if is_early:
            early_ids.add(game.game_id)
        else:
            mature_count += 1

    row_ids = [row.get("target_game_id") for row in dataset.rows]
    _finding_if(
        len(row_ids) != len(set(row_ids)),
        findings,
        "duplicate_target_game_id",
        "early dataset contains duplicate target IDs",
    )
    _finding_if(
        set(row_ids) != early_ids,
        findings,
        "early_target_population_mismatch",
        "dataset IDs differ from independently derived early-route targets",
    )
    expected_ties = sum(
        game.status is NflGameStatus.FINAL
        and game.home_score == game.away_score
        for game in games
    )
    expected_nonfinal = sum(
        game.status is not NflGameStatus.FINAL
        for game in games
    )
    _finding_if(
        dataset.games_received != len(games),
        findings,
        "games_received_mismatch",
        "builder count differs from canonical input count",
    )
    _finding_if(
        dataset.ties_skipped != expected_ties,
        findings,
        "ties_skipped_mismatch",
        "builder tie count differs from canonical final ties",
    )
    _finding_if(
        dataset.nonfinal_games_skipped != expected_nonfinal,
        findings,
        "nonfinal_skipped_mismatch",
        "builder nonfinal count differs from canonical inputs",
    )
    _finding_if(
        dataset.mature_route_games_skipped != mature_count,
        findings,
        "mature_route_count_mismatch",
        "builder mature-route count differs from independent routing",
    )
    return early_ids


def _audit_traces(games, traces, history, findings):
    targets = {
        game.game_id: game
        for game in games
        if game.status is NflGameStatus.FINAL
        and game.home_score != game.away_score
    }
    expected_keys = {
        (target.game_id, team_id, season)
        for target in targets.values()
        for team_id in (target.home_team_id, target.away_team_id)
        for season in (target.season - 1, target.season)
    }
    seen: Counter[tuple[int, int, int | None]] = Counter()
    for trace in traces:
        key = (
            trace.target_game_id,
            trace.team_id,
            trace.requested_season,
        )
        seen[key] += 1
        target = targets.get(trace.target_game_id)
        if target is None:
            findings.append(_finding(
                "unknown_trace_target",
                f"trace target {trace.target_game_id} is not eligible",
            ))
            continue
        _finding_if(
            trace.team_id not in {target.home_team_id, target.away_team_id},
            findings,
            "trace_nonparticipant",
            f"trace team {trace.team_id} is not in target {target.game_id}",
        )
        _finding_if(
            trace.requested_cutoff != target.scheduled_start_time,
            findings,
            "trace_cutoff_mismatch",
            f"trace cutoff differs for target {target.game_id}",
        )
        _finding_if(
            trace.requested_limit is not None,
            findings,
            "truncated_history_request",
            f"trace requested a limit for target {target.game_id}",
        )
        _finding_if(
            trace.requested_season
            not in {target.season - 1, target.season},
            findings,
            "trace_season_mismatch",
            f"trace requested wrong season for target {target.game_id}",
        )
        if trace.requested_season is None:
            continue
        expected_games = _eligible_history(
            history,
            team_id=trace.team_id,
            season=trace.requested_season,
            cutoff=target.scheduled_start_time,
        )
        _finding_if(
            trace.source_game_ids
            != tuple(item.game.game_id for item in expected_games),
            findings,
            "trace_source_set_mismatch",
            f"trace source set/order differs for target {target.game_id} "
            f"team {trace.team_id} season {trace.requested_season}",
        )
        for item in trace.source_games:
            _finding_if(
                item.game.scheduled_start_time
                >= target.scheduled_start_time,
                findings,
                "trace_pit_violation",
                f"source {item.game.game_id} is not before target {target.game_id}",
            )
            _finding_if(
                item.game.game_id == target.game_id,
                findings,
                "target_self_inclusion",
                f"target {target.game_id} appears in its history",
            )
    _finding_if(
        set(seen) != expected_keys,
        findings,
        "trace_request_set_mismatch",
        "history trace request keys differ from expected two-channel reads",
    )
    for key, count in seen.items():
        _finding_if(
            count != 1,
            findings,
            "duplicate_trace_request",
            f"history request {key} occurred {count} times",
        )


def _audit_rows(rows, expected_ids, game_by_id, expected, findings):
    row_ids = [row.get("target_game_id") for row in rows]
    expected_order = sorted(
        expected_ids,
        key=lambda game_id: (
            game_by_id[game_id].scheduled_start_time,
            game_id,
        ),
    )
    _finding_if(
        row_ids != expected_order,
        findings,
        "nondeterministic_target_order",
        "early rows are not ordered by kickoff then game ID",
    )
    for row in rows:
        game_id = row.get("target_game_id")
        target = game_by_id.get(game_id)
        if target is None:
            findings.append(_finding(
                "unknown_dataset_target",
                f"row target {game_id} is unknown",
            ))
            continue
        _audit_row_metadata(row, target, findings)
        for side, team_id in (
            ("home", target.home_team_id),
            ("away", target.away_team_id),
        ):
            prior = expected[(target.game_id, team_id, "prior")]
            current = expected[(target.game_id, team_id, "current")]
            _audit_side_channel(row, side, prior, current, target, findings)
        _audit_symmetric_features(row, target, expected, findings)
        for name, value in row.items():
            if isinstance(value, float) and not math.isfinite(value):
                findings.append(_finding(
                    "nonfinite_value",
                    f"target {target.game_id} field {name} is nonfinite",
                ))


def _audit_row_metadata(row, target, findings):
    expected_values = {
        "target_kickoff": target.scheduled_start_time,
        "target_season": target.season,
        "target_season_type": target.season_type.value,
        "home_team_id": target.home_team_id,
        "away_team_id": target.away_team_id,
        "feature_cutoff": target.scheduled_start_time,
        "feature_schema_version": NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION,
        "target_tie": False,
        "route": NFLMoneylineRoute.EARLY.value,
        "neutral_site": target.neutral_site,
        "home_win": target.home_score > target.away_score,
        "feature_names": NFL_EARLY_MONEYLINE_FEATURE_NAMES,
    }
    for name, expected_value in expected_values.items():
        _finding_if(
            row.get(name) != expected_value,
            findings,
            "row_metadata_mismatch",
            f"target {target.game_id} field {name} is incorrect",
        )
    _finding_if(
        not isinstance(row.get("home_win"), bool),
        findings,
        "invalid_home_win_type",
        f"target {target.game_id} home_win is not boolean",
    )
    _finding_if(
        target.status is not NflGameStatus.FINAL,
        findings,
        "nonfinal_dataset_target",
        f"target {target.game_id} is not final",
    )
    _finding_if(
        target.home_score == target.away_score,
        findings,
        "tied_dataset_target",
        f"target {target.game_id} is tied",
    )


def _audit_side_channel(row, side, prior, current, target, findings):
    expected_values = {
        f"{side}_prior_season_available": prior.games_played > 0,
        f"{side}_prior_season_games_played": prior.games_played,
        f"{side}_prior_season_win_percentage": prior.win_percentage,
        f"{side}_prior_season_average_point_differential": (
            prior.average_point_differential
        ),
        f"{side}_prior_season_average_turnover_differential": (
            prior.average_turnover_differential
        ),
        f"{side}_prior_season_source_game_ids": prior.source_game_ids,
        f"{side}_prior_season_source_kickoffs": prior.source_kickoffs,
        f"{side}_current_season_prior_games": current.games_played,
        f"{side}_current_season_win_percentage": current.win_percentage,
        f"{side}_current_season_average_points_for": (
            current.average_points_for
        ),
        f"{side}_current_season_average_points_against": (
            current.average_points_against
        ),
        f"{side}_current_season_average_point_differential": (
            current.average_point_differential
        ),
        f"{side}_current_season_average_turnover_differential": (
            current.average_turnover_differential
        ),
        f"{side}_current_season_source_game_ids": current.source_game_ids,
        f"{side}_current_season_source_kickoffs": current.source_kickoffs,
    }
    for name, expected_value in expected_values.items():
        _finding_if(
            not _equal(row.get(name), expected_value),
            findings,
            "channel_replay_mismatch",
            f"target {target.game_id} field {name} differs from replay",
        )
    if prior.games_played == 0:
        findings.append(_finding(
            "missing_prior_season_history",
            f"target {target.game_id} {side} has no prior regular history",
        ))
    if current.games_played == 0:
        for suffix in (
            "win_percentage",
            "average_points_for",
            "average_points_against",
            "average_point_differential",
            "average_turnover_differential",
        ):
            _finding_if(
                row.get(f"{side}_current_season_{suffix}") is not None,
                findings,
                "zero_history_missingness_violation",
                f"target {target.game_id} {side} {suffix} must be None",
            )


def _audit_symmetric_features(row, target, expected, findings):
    home_prior = expected[(target.game_id, target.home_team_id, "prior")]
    away_prior = expected[(target.game_id, target.away_team_id, "prior")]
    home_current = expected[(target.game_id, target.home_team_id, "current")]
    away_current = expected[(target.game_id, target.away_team_id, "current")]
    expected_values: dict[str, float | int | None] = {
        "prior_season_games_played_difference": (
            home_prior.games_played - away_prior.games_played
        ),
        "prior_season_win_percentage_difference": _difference(
            home_prior.win_percentage,
            away_prior.win_percentage,
        ),
        "prior_season_average_point_differential_difference": _difference(
            home_prior.average_point_differential,
            away_prior.average_point_differential,
        ),
        "prior_season_average_turnover_differential_difference": _difference(
            home_prior.average_turnover_differential,
            away_prior.average_turnover_differential,
        ),
        "current_season_prior_games_played_difference": (
            home_current.games_played - away_current.games_played
        ),
        "current_season_win_percentage_difference": _difference(
            home_current.win_percentage,
            away_current.win_percentage,
        ),
        "current_season_average_points_for_difference": _difference(
            home_current.average_points_for,
            away_current.average_points_for,
        ),
        "current_season_average_points_against_difference": _difference(
            home_current.average_points_against,
            away_current.average_points_against,
        ),
        "current_season_average_turnover_differential_difference": _difference(
            home_current.average_turnover_differential,
            away_current.average_turnover_differential,
        ),
        "minimum_current_season_prior_games": min(
            home_current.games_played,
            away_current.games_played,
        ),
        "neutral_site": int(target.neutral_site),
    }
    for name, expected_value in expected_values.items():
        _finding_if(
            not _equal(row.get(name), expected_value),
            findings,
            "symmetric_feature_mismatch",
            f"target {target.game_id} feature {name} differs from replay",
        )
    expected_vector = tuple(
        expected_values[name]
        for name in NFL_EARLY_MONEYLINE_FEATURE_NAMES
    )
    _finding_if(
        not _equal(row.get("feature_values"), expected_vector),
        findings,
        "ordered_feature_vector_mismatch",
        f"target {target.game_id} ordered vector differs from named features",
    )
    _finding_if(
        row.get("minimum_current_prior_games")
        != expected_values["minimum_current_season_prior_games"],
        findings,
        "minimum_history_count_mismatch",
        f"target {target.game_id} minimum count is incorrect",
    )


def _aggregate(games) -> _ExpectedChannel:
    games = tuple(games)
    count = len(games)
    points = [_points(item) for item in games]
    wins = sum(points_for > points_against for points_for, points_against in points)
    ties = sum(points_for == points_against for points_for, points_against in points)
    return _ExpectedChannel(
        games=games,
        games_played=count,
        win_percentage=(wins + 0.5 * ties) / count if count else None,
        average_points_for=_average([value[0] for value in points]),
        average_points_against=_average([value[1] for value in points]),
        average_point_differential=_average([
            points_for - points_against
            for points_for, points_against in points
        ]),
        average_turnover_differential=_average([
            _takeaways(item) - _turnovers(item)
            for item in games
        ]),
    )


def _points(item: HistoricalNflTeamGame) -> tuple[int, int]:
    game = item.game
    is_home = item.team_statistics.team_id == game.home_team_id
    points_for = game.home_score if is_home else game.away_score
    points_against = game.away_score if is_home else game.home_score
    assert points_for is not None and points_against is not None
    return points_for, points_against


def _turnovers(item: HistoricalNflTeamGame) -> int:
    stats = item.team_statistics
    return stats.passing_interceptions + stats.fumbles_lost


def _takeaways(item: HistoricalNflTeamGame) -> int:
    stats = item.opponent_statistics
    return stats.passing_interceptions + stats.fumbles_lost


def _average(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _difference(left, right):
    if left is None or right is None:
        return None
    return left - right


def _canonical_counts(games) -> dict[int, dict[str, int]]:
    seasons = sorted({game.season for game in games})
    return {
        season: {
            "canonical_games": sum(game.season == season for game in games),
            "final_games": sum(
                game.season == season
                and game.status is NflGameStatus.FINAL
                for game in games
            ),
            "final_non_tied_targets": sum(
                game.season == season
                and game.status is NflGameStatus.FINAL
                and game.home_score != game.away_score
                for game in games
            ),
        }
        for season in seasons
    }


def _count_by(rows, field) -> dict[int, int]:
    counts = Counter(int(row[field]) for row in rows)
    return dict(sorted(counts.items()))


def _prior_coverage_by_season(rows) -> dict[int, dict[str, int]]:
    seasons = sorted({int(row["target_season"]) for row in rows})
    return {
        season: {
            "targets": len(season_rows),
            "both_teams_available": sum(
                row["home_prior_season_available"] is True
                and row["away_prior_season_available"] is True
                for row in season_rows
            ),
            "team_channels_available": sum(
                row[f"{side}_prior_season_available"] is True
                for row in season_rows
                for side in ("home", "away")
            ),
            "team_channels_total": 2 * len(season_rows),
        }
        for season in seasons
        if (season_rows := tuple(
            row for row in rows if int(row["target_season"]) == season
        ))
    }


def _team_count_distribution(rows, suffix) -> dict[int, int]:
    counts = Counter(
        int(row[f"{side}_{suffix}"])
        for row in rows
        for side in ("home", "away")
    )
    return dict(sorted(counts.items()))


def _feature_null_rates(rows) -> dict[str, dict[str, float | int]]:
    total = len(rows)
    return {
        name: {
            "null_count": (null_count := sum(row[name] is None for row in rows)),
            "total": total,
            "null_rate": null_count / total if total else 0.0,
        }
        for name in NFL_EARLY_MONEYLINE_FEATURE_NAMES
    }


def _canonical_value(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fingerprint datetimes must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("fingerprint values must be finite")
    return value


def _equal(left, right) -> bool:
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if left is None or right is None:
        return left is right
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
    return left == right


def _finding(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _finding_if(condition, findings, code, detail) -> None:
    if condition:
        findings.append(_finding(code, detail))
