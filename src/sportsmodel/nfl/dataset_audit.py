from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from statistics import mean, median
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.database.nfl_game_repository import list_nfl_games_by_season_range
from sportsmodel.database.nfl_team_game_statistics_repository import (
    NflTeamHistoryRepository,
    list_all_nfl_completed_history,
)
from sportsmodel.nfl.features import HistoricalNflTeamGame, NFLFeatureDataProvider
from sportsmodel.nfl.models import NflGame, NflGameStatus
from sportsmodel.nfl.moneyline_dataset import (
    NFLMoneylineDatasetBuildResult,
    NFLMoneylineTrainingDatasetBuilder,
)


@dataclass(frozen=True)
class HistoryAuditTrace:
    target_game_id: int
    target_kickoff: datetime
    target_season: int
    team_id: int
    requested_cutoff: datetime
    requested_season: int | None
    requested_limit: int | None
    source_games: tuple[HistoricalNflTeamGame, ...]

    @property
    def source_game_ids(self) -> tuple[int, ...]:
        return tuple(item.game.game_id for item in self.source_games)

    @property
    def source_kickoffs(self) -> tuple[datetime, ...]:
        return tuple(item.game.scheduled_start_time for item in self.source_games)

    @property
    def source_seasons(self) -> tuple[int, ...]:
        return tuple(item.game.season for item in self.source_games)


class SnapshotNflTeamHistoryRepository(NflTeamHistoryRepository):
    """Indexed immutable production snapshot with auditable PIT reads."""

    def __init__(self, history: Iterable[HistoricalNflTeamGame]) -> None:
        grouped: dict[int, list[HistoricalNflTeamGame]] = defaultdict(list)
        for item in history:
            grouped[item.team_statistics.team_id].append(item)
        self._by_team = {
            team_id: tuple(sorted(
                games,
                key=lambda item: (
                    item.game.scheduled_start_time,
                    item.game.game_id,
                ),
                reverse=True,
            ))
            for team_id, games in grouped.items()
        }
        self.traces: list[HistoryAuditTrace] = []

    def for_target(self, target_game: NflGame) -> TargetNflTeamHistoryRepository:
        return TargetNflTeamHistoryRepository(self, target_game)

    def get_completed_games_before(
        self, *, team_id: int, cutoff_time: datetime,
        season: int | None = None, limit: int | None = None,
    ) -> tuple[HistoricalNflTeamGame, ...]:
        games = tuple(
            item for item in self._by_team.get(team_id, ())
            if item.game.scheduled_start_time < cutoff_time
            and (season is None or item.game.season == season)
        )
        return games if limit is None else games[:limit]


class TargetNflTeamHistoryRepository(NflTeamHistoryRepository):
    def __init__(
        self, snapshot: SnapshotNflTeamHistoryRepository, target_game: NflGame,
    ) -> None:
        self._snapshot = snapshot
        self._target_game = target_game

    def get_completed_games_before(
        self, *, team_id: int, cutoff_time: datetime,
        season: int | None = None, limit: int | None = None,
    ) -> tuple[HistoricalNflTeamGame, ...]:
        games = self._snapshot.get_completed_games_before(
            team_id=team_id,
            cutoff_time=cutoff_time,
            season=season,
            limit=limit,
        )
        self._snapshot.traces.append(HistoryAuditTrace(
            target_game_id=self._target_game.game_id,
            target_kickoff=self._target_game.scheduled_start_time,
            target_season=self._target_game.season,
            team_id=team_id,
            requested_cutoff=cutoff_time,
            requested_season=season,
            requested_limit=limit,
            source_games=games,
        ))
        return games


@dataclass(frozen=True)
class NFLHistoricalDatasetAuditOutcome:
    canonical_games: tuple[NflGame, ...]
    dataset: NFLMoneylineDatasetBuildResult
    report: dict[str, Any]
    fingerprint: str


def build_and_audit_production_dataset(
    *, season_from: int = 2018, season_to: int = 2025,
    connection_factory=get_connection,
) -> NFLHistoricalDatasetAuditOutcome:
    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            games = list_nfl_games_by_season_range(
                cursor, season_from=season_from, season_to=season_to,
            )
            history = list_all_nfl_completed_history(
                cursor, season_from=season_from, season_to=season_to,
            )
    finally:
        connection.close()

    snapshot = SnapshotNflTeamHistoryRepository(history)
    builder = NFLMoneylineTrainingDatasetBuilder(
        provider_factory=lambda game: NFLFeatureDataProvider(
            game, repository=snapshot.for_target(game)
        )
    )
    dataset = builder.build(games)
    report = audit_generated_dataset(
        games, dataset, snapshot.traces, canonical_history=history,
    )
    return NFLHistoricalDatasetAuditOutcome(
        canonical_games=games,
        dataset=dataset,
        report=report,
        fingerprint=dataset_fingerprint(dataset.rows),
    )


def audit_generated_dataset(
    games: Iterable[NflGame],
    dataset: NFLMoneylineDatasetBuildResult,
    traces: Iterable[HistoryAuditTrace],
    *,
    canonical_history: Iterable[HistoricalNflTeamGame] = (),
) -> dict[str, Any]:
    ordered_games = tuple(sorted(
        games,
        key=lambda game: (game.scheduled_start_time, game.game_id),
    ))
    rows = dataset.rows
    game_by_id = {game.game_id: game for game in ordered_games}
    findings: list[dict[str, str]] = []

    history = tuple(canonical_history)
    trace_items = tuple(traces)
    _audit_population_and_rows(dataset, ordered_games, game_by_id, findings)
    expected_history = _audit_history_traces(
        trace_items, history, game_by_id, findings,
    )
    _audit_feature_replay(rows, trace_items, expected_history, game_by_id, findings)
    _audit_feature_symmetry(rows, findings)

    return {
        "population": _population_summary(ordered_games),
        "dataset_rows": len(rows),
        "excluded_ties": dataset.ties_skipped,
        "excluded_nonfinal": dataset.nonfinal_games_skipped,
        "integrity_findings": findings,
        "integrity_passed": not findings,
        "coverage": _coverage_summary(rows),
        "numeric_features": _numeric_summaries(rows),
        "seasons": _season_summaries(rows, game_by_id),
        "class_balance": _class_balance(rows, game_by_id),
        "feature_schema_versions": sorted({
            str(row["feature_schema_version"]) for row in rows
        }),
    }


def dataset_fingerprint(rows: Iterable[dict[str, object]]) -> str:
    payload = json.dumps(
        [_canonical_row(row) for row in rows],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _audit_population_and_rows(dataset, games, game_by_id, findings) -> None:
    rows = dataset.rows
    row_ids = [row.get("target_game_id") for row in rows]
    _finding_if(len(row_ids) != len(set(row_ids)), findings,
                "duplicate_target_game_id", "dataset target game IDs are not unique")
    expected_ids = {
        game.game_id for game in games
        if game.status is NflGameStatus.FINAL
        and game.home_score != game.away_score
    }
    _finding_if(set(row_ids) != expected_ids, findings,
                "target_population_mismatch", "dataset target IDs differ from eligible finals")
    expected_ties = sum(
        game.status is NflGameStatus.FINAL
        and game.home_score == game.away_score
        for game in games
    )
    expected_nonfinal = sum(
        game.status is not NflGameStatus.FINAL for game in games
    )
    _finding_if(dataset.games_received != len(games), findings,
                "games_received_mismatch",
                "dataset games_received differs from canonical population")
    _finding_if(dataset.ties_skipped != expected_ties, findings,
                "ties_skipped_mismatch",
                "dataset ties_skipped differs from canonical final ties")
    _finding_if(dataset.nonfinal_games_skipped != expected_nonfinal, findings,
                "nonfinal_skipped_mismatch",
                "dataset nonfinal_games_skipped differs from canonical non-finals")
    serialized = [json.dumps(_canonical_row(row), sort_keys=True) for row in rows]
    _finding_if(len(serialized) != len(set(serialized)), findings,
                "duplicate_dataset_row", "dataset contains duplicate rows")
    expected_order = sorted(
        row_ids,
        key=lambda game_id: (
            game_by_id[game_id].scheduled_start_time, game_id,
        ),
    ) if all(game_id in game_by_id for game_id in row_ids) else []
    _finding_if(row_ids != expected_order, findings,
                "nondeterministic_target_order", "target rows are not in kickoff/game ID order")

    forbidden = {"home_score", "away_score", "status", "overtime"}
    for index, row in enumerate(rows):
        game_id = row.get("target_game_id")
        game = game_by_id.get(game_id)
        if game is None:
            findings.append(_finding("missing_target_game", f"row {index} target is unknown"))
            continue
        _finding_if(row.get("feature_cutoff") != game.scheduled_start_time,
                    findings, "invalid_feature_cutoff", f"game {game_id} cutoff differs from kickoff")
        _finding_if(row.get("target_kickoff") != game.scheduled_start_time,
                    findings, "invalid_target_kickoff", f"game {game_id} target kickoff differs")
        _finding_if(row.get("home_team_id") != game.home_team_id
                    or row.get("away_team_id") != game.away_team_id,
                    findings, "target_participant_mismatch", f"game {game_id} participants differ")
        _finding_if(game.home_team_id == game.away_team_id, findings,
                    "identical_target_teams", f"game {game_id} has identical teams")
        _finding_if(game.status is not NflGameStatus.FINAL, findings,
                    "nonfinal_target", f"game {game_id} is not final")
        _finding_if(game.home_score == game.away_score, findings,
                    "tied_target", f"game {game_id} is tied")
        _finding_if(not isinstance(row.get("home_win"), bool), findings,
                    "invalid_home_win", f"game {game_id} home_win is not boolean")
        _finding_if(
            isinstance(row.get("home_win"), bool)
            and row["home_win"] != (game.home_score > game.away_score),
            findings, "incorrect_home_win", f"game {game_id} home_win disagrees with result",
        )
        _finding_if(bool(forbidden.intersection(row)), findings,
                    "target_result_feature", f"game {game_id} contains target result fields")
        for side in ("home", "away"):
            prior = row.get(f"{side}_prior_games_used")
            rolling_3 = row.get(f"{side}_rolling_3_games_used")
            rolling_5 = row.get(f"{side}_rolling_5_games_used")
            valid_counts = all(isinstance(value, int) and value >= 0
                               for value in (prior, rolling_3, rolling_5))
            _finding_if(not valid_counts, findings, "invalid_game_count",
                        f"game {game_id} {side} history count is invalid")
            if valid_counts:
                _finding_if(rolling_3 > 3 or rolling_5 > 5, findings,
                            "rolling_window_exceeded", f"game {game_id} {side} rolling count exceeds window")
                _finding_if(rolling_3 > prior or rolling_5 > prior, findings,
                            "rolling_exceeds_prior", f"game {game_id} {side} rolling count exceeds prior")
                _finding_if(
                    rolling_3 != min(prior, 3) or rolling_5 != min(prior, 5),
                    findings, "rolling_count_mismatch",
                    f"game {game_id} {side} rolling count is not up-to-window",
                )
            win_percentage = row.get(f"{side}_win_percentage")
            _finding_if(win_percentage is not None and not 0 <= win_percentage <= 1,
                        findings, "invalid_win_percentage", f"game {game_id} {side} win percentage invalid")
        _audit_row_math(row, game_id, findings)
        for name, value in row.items():
            if isinstance(value, float) and not math.isfinite(value):
                findings.append(_finding("nonfinite_feature", f"game {game_id} {name} is nonfinite"))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                _audit_broad_sanity(name, value, game_id, findings)


def _audit_row_math(row, game_id, findings) -> None:
    for side in ("home", "away"):
        _equal_or_none(
            row, f"{side}_average_point_differential",
            row.get(f"{side}_average_points_for"),
            row.get(f"{side}_average_points_against"),
            game_id, findings,
        )
        turnovers = row.get(f"{side}_average_turnovers")
        takeaways = row.get(f"{side}_average_takeaways")
        differential = row.get(f"{side}_average_turnover_differential")
        expected = None if turnovers is None or takeaways is None else takeaways - turnovers
        if not _close(differential, expected):
            findings.append(_finding(
                "turnover_differential_mismatch",
                f"game {game_id} {side} turnover differential is inconsistent",
            ))


def _audit_broad_sanity(name, value, game_id, findings) -> None:
    bounds = None
    if "points_for" in name or "points_against" in name:
        bounds = (0, 100)
    elif "point_differential" in name:
        bounds = (-100, 100)
    elif "passing_yards" in name or "rushing_yards" in name:
        bounds = (-100, 700)
    elif name.endswith(("average_turnovers", "average_takeaways")):
        bounds = (0, 15)
    elif "turnover_differential" in name:
        bounds = (-15, 15)
    elif name.endswith("prior_games_used"):
        bounds = (0, 25)
    if bounds is not None and not bounds[0] <= value <= bounds[1]:
        findings.append(_finding(
            "broad_sanity_bound",
            f"game {game_id} {name}={value} outside {bounds}",
        ))


def _equal_or_none(row, name, left, right, game_id, findings) -> None:
    expected = None if left is None or right is None else left - right
    if not _close(row.get(name), expected):
        findings.append(_finding(
            "point_differential_mismatch",
            f"game {game_id} {name} is inconsistent",
        ))


def _audit_history_traces(
    traces, canonical_history, game_by_id, findings,
) -> dict[tuple[int, int], tuple[HistoricalNflTeamGame, ...]]:
    history_keys = [
        (item.team_statistics.team_id, item.game.game_id)
        for item in canonical_history
    ]
    duplicate_history_keys = {
        key for key, count in Counter(history_keys).items() if count > 1
    }
    for team_id, game_id in sorted(duplicate_history_keys):
        findings.append(_finding(
            "duplicate_canonical_history",
            f"team {team_id} game {game_id} occurs more than once in bulk history",
        ))

    eligible_targets = {
        game_id: game for game_id, game in game_by_id.items()
        if game.status is NflGameStatus.FINAL and game.home_score != game.away_score
    }
    expected_by_request: dict[
        tuple[int, int], tuple[HistoricalNflTeamGame, ...]
    ] = {}
    for target in eligible_targets.values():
        for team_id in (target.home_team_id, target.away_team_id):
            expected_by_request[(target.game_id, team_id)] = tuple(sorted(
                (
                    item for item in canonical_history
                    if item.team_statistics.team_id == team_id
                    and item.game.status is NflGameStatus.FINAL
                    and item.game.season == target.season
                    and item.game.scheduled_start_time < target.scheduled_start_time
                ),
                key=lambda item: (
                    item.game.scheduled_start_time,
                    item.game.game_id,
                ),
                reverse=True,
            ))

    seen: Counter[tuple[int, int]] = Counter()
    for trace in traces:
        key = (trace.target_game_id, trace.team_id)
        seen[key] += 1
        target = game_by_id.get(trace.target_game_id)
        if target is None:
            findings.append(_finding("unknown_history_target", str(trace.target_game_id)))
            continue
        _finding_if(trace.target_kickoff != target.scheduled_start_time, findings,
                    "history_target_kickoff_mismatch",
                    f"game {target.game_id} trace target kickoff differs")
        _finding_if(trace.target_season != target.season, findings,
                    "history_target_season_mismatch",
                    f"game {target.game_id} trace target season differs")
        _finding_if(trace.requested_cutoff != target.scheduled_start_time, findings,
                    "history_cutoff_mismatch",
                    f"game {target.game_id} requested cutoff differs from kickoff")
        _finding_if(trace.requested_season != target.season, findings,
                    "history_season_scope", f"game {target.game_id} requested wrong season")
        _finding_if(trace.requested_limit is not None, findings,
                    "truncated_season_history", f"game {target.game_id} requested a history limit")
        _finding_if(trace.team_id not in {target.home_team_id, target.away_team_id},
                    findings, "history_team_mismatch", f"game {target.game_id} queried nonparticipant")
        _finding_if(target.game_id in trace.source_game_ids, findings,
                    "target_in_history", f"game {target.game_id} sees itself")
        _finding_if(any(kickoff >= target.scheduled_start_time for kickoff in trace.source_kickoffs),
                    findings, "future_history", f"game {target.game_id} sees a future source")
        _finding_if(any(season != target.season for season in trace.source_seasons),
                    findings, "cross_season_history", f"game {target.game_id} sees another season")
        _finding_if(any(
            item.team_statistics.team_id != trace.team_id
            for item in trace.source_games
        ), findings, "history_source_team_mismatch",
            f"game {target.game_id} returned history for another team")
        ordering = tuple(sorted(
            zip(trace.source_kickoffs, trace.source_game_ids), reverse=True
        ))
        _finding_if(ordering != tuple(zip(trace.source_kickoffs, trace.source_game_ids)),
                    findings, "history_order", f"game {target.game_id} history is not newest first")

        expected = expected_by_request.get(key, ())
        expected_ids = tuple(item.game.game_id for item in expected)
        _finding_if(trace.source_game_ids != expected_ids, findings,
                    "history_completeness_mismatch",
                    f"game {target.game_id} team {trace.team_id} history IDs differ from bulk snapshot")
        _finding_if(trace.source_games != expected, findings,
                    "history_source_row_mismatch",
                    f"game {target.game_id} team {trace.team_id} history rows differ from bulk snapshot")

    for target in eligible_targets.values():
        for team_id in (target.home_team_id, target.away_team_id):
            count = seen[(target.game_id, team_id)]
            _finding_if(count != 1, findings, "history_trace_count",
                        f"game {target.game_id} team {team_id} has {count} traces instead of 1")
    return expected_by_request


def _audit_feature_replay(
    rows, traces, expected_by_request, game_by_id, findings,
) -> None:
    traces_by_request: dict[tuple[int, int], HistoryAuditTrace] = {}
    for trace in traces:
        traces_by_request.setdefault((trace.target_game_id, trace.team_id), trace)

    for row in rows:
        target_id = row.get("target_game_id")
        target = game_by_id.get(target_id)
        if target is None:
            continue
        for side, team_id in (
            ("home", target.home_team_id),
            ("away", target.away_team_id),
        ):
            key = (target.game_id, team_id)
            history = expected_by_request.get(key, ())
            trace = traces_by_request.get(key)
            expected_count = len(history)
            _compare_replayed_value(
                row, f"{side}_prior_games_used", expected_count,
                "prior_game_count_replay", target.game_id, findings,
            )
            if trace is not None:
                _finding_if(len(trace.source_games) != expected_count, findings,
                            "trace_history_count_mismatch",
                            f"game {target.game_id} {side} trace count differs from complete history")

            season_values = _recompute_season_features(history)
            for name, expected in season_values.items():
                code = (
                    "opponent_feature_replay"
                    if name in {
                        "average_passing_yards_allowed",
                        "average_rushing_yards_allowed",
                        "average_takeaways",
                        "average_turnover_differential",
                    }
                    else "season_feature_replay"
                )
                _compare_replayed_value(
                    row, f"{side}_{name}", expected, code,
                    target.game_id, findings,
                )

            for window in (3, 5):
                rolling = history[:window]
                _compare_replayed_value(
                    row, f"{side}_rolling_{window}_games_used", len(rolling),
                    "rolling_game_count_replay", target.game_id, findings,
                )
                for name, expected in _recompute_rolling_features(rolling).items():
                    code = (
                        "opponent_feature_replay"
                        if name == "average_turnover_differential"
                        else "rolling_feature_replay"
                    )
                    _compare_replayed_value(
                        row, f"{side}_rolling_{window}_{name}", expected,
                        code, target.game_id, findings,
                    )


def _recompute_season_features(
    history: tuple[HistoricalNflTeamGame, ...],
) -> dict[str, float | None]:
    count = len(history)
    wins = sum(item.points_for > item.points_against for item in history)
    ties = sum(item.points_for == item.points_against for item in history)
    turnovers = [
        item.team_statistics.passing_interceptions
        + item.team_statistics.fumbles_lost
        for item in history
    ]
    takeaways = [
        item.opponent_statistics.passing_interceptions
        + item.opponent_statistics.fumbles_lost
        for item in history
    ]
    return {
        "win_percentage": (wins + 0.5 * ties) / count if count else None,
        "average_points_for": _audit_average([item.points_for for item in history]),
        "average_points_against": _audit_average([
            item.points_against for item in history
        ]),
        "average_point_differential": _audit_average([
            item.points_for - item.points_against for item in history
        ]),
        "average_passing_yards": _audit_average([
            item.team_statistics.passing_yards for item in history
        ]),
        "average_passing_yards_allowed": _audit_average([
            item.opponent_statistics.passing_yards for item in history
        ]),
        "average_rushing_yards": _audit_average([
            item.team_statistics.rushing_yards for item in history
        ]),
        "average_rushing_yards_allowed": _audit_average([
            item.opponent_statistics.rushing_yards for item in history
        ]),
        "average_turnovers": _audit_average(turnovers),
        "average_takeaways": _audit_average(takeaways),
        "average_turnover_differential": _audit_average([
            takeaway - turnover
            for takeaway, turnover in zip(takeaways, turnovers, strict=True)
        ]),
    }


def _recompute_rolling_features(
    history: tuple[HistoricalNflTeamGame, ...],
) -> dict[str, float | None]:
    return {
        "average_points_for": _audit_average([item.points_for for item in history]),
        "average_points_against": _audit_average([
            item.points_against for item in history
        ]),
        "average_point_differential": _audit_average([
            item.points_for - item.points_against for item in history
        ]),
        "average_turnover_differential": _audit_average([
            (
                item.opponent_statistics.passing_interceptions
                + item.opponent_statistics.fumbles_lost
            ) - (
                item.team_statistics.passing_interceptions
                + item.team_statistics.fumbles_lost
            )
            for item in history
        ]),
    }


def _audit_average(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _compare_replayed_value(
    row, name, expected, code, game_id, findings,
) -> None:
    if not _close(row.get(name), expected):
        findings.append(_finding(
            code,
            f"game {game_id} {name}={row.get(name)!r}; expected {expected!r}",
        ))


def _audit_feature_symmetry(rows, findings) -> None:
    if not rows:
        return
    home = {
        name.removeprefix("home_") for name in rows[0]
        if name.startswith("home_") and name != "home_win"
    }
    away = {name.removeprefix("away_") for name in rows[0] if name.startswith("away_")}
    _finding_if(home != away, findings, "feature_asymmetry",
                "home and away feature column definitions differ")


def _population_summary(games) -> dict[str, Any]:
    finals = [game for game in games if game.status is NflGameStatus.FINAL]
    ties = [game for game in finals if game.home_score == game.away_score]
    by_season: dict[str, dict[str, int]] = {}
    by_type: dict[str, dict[str, int]] = {}
    for game in games:
        season = by_season.setdefault(str(game.season), {
            "canonical": 0, "final": 0, "ties": 0, "eligible": 0,
        })
        season["canonical"] += 1
        season["final"] += int(game.status is NflGameStatus.FINAL)
        season["ties"] += int(game.status is NflGameStatus.FINAL and game.home_score == game.away_score)
        season["eligible"] += int(game.status is NflGameStatus.FINAL and game.home_score != game.away_score)
        season_type = by_type.setdefault(game.season_type.value, {
            "canonical": 0, "final": 0, "ties": 0, "eligible": 0,
        })
        season_type["canonical"] += 1
        season_type["final"] += int(game.status is NflGameStatus.FINAL)
        season_type["ties"] += int(
            game.status is NflGameStatus.FINAL
            and game.home_score == game.away_score
        )
        season_type["eligible"] += int(
            game.status is NflGameStatus.FINAL
            and game.home_score != game.away_score
        )
    return {
        "canonical_games": len(games),
        "final_games": len(finals),
        "tied_final_games": len(ties),
        "nonfinal_games": len(games) - len(finals),
        "eligible_targets": len(finals) - len(ties),
        "by_season": by_season,
        "by_season_type": dict(sorted(by_type.items())),
        "earliest_kickoff": min(game.scheduled_start_time for game in games).isoformat(),
        "latest_kickoff": max(game.scheduled_start_time for game in games).isoformat(),
    }


def _coverage_summary(rows) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for side in ("home", "away"):
        prior = [row[f"{side}_prior_games_used"] for row in rows]
        rolling_3 = [row[f"{side}_rolling_3_games_used"] for row in rows]
        rolling_5 = [row[f"{side}_rolling_5_games_used"] for row in rows]
        summary[side] = {
            "zero_history": sum(value == 0 for value in prior),
            "fewer_than_3": sum(value < 3 for value in prior),
            "fewer_than_5": sum(value < 5 for value in prior),
            "average_prior_games": mean(prior),
            "average_rolling_3_games": mean(rolling_3),
            "average_rolling_5_games": mean(rolling_5),
        }
    summary["either_team"] = {
        "zero_history_rows": sum(
            row["home_prior_games_used"] == 0
            or row["away_prior_games_used"] == 0 for row in rows
        ),
        "fewer_than_3_rows": sum(
            row["home_prior_games_used"] < 3
            or row["away_prior_games_used"] < 3 for row in rows
        ),
        "fewer_than_5_rows": sum(
            row["home_prior_games_used"] < 5
            or row["away_prior_games_used"] < 5 for row in rows
        ),
    }
    return summary


def _numeric_summaries(rows) -> dict[str, dict[str, float | int | None]]:
    excluded = {
        "target_game_id", "home_team_id", "away_team_id", "home_win",
    }
    names = [
        name for name in rows[0]
        if name not in excluded
        and any(isinstance(row.get(name), (int, float))
                and not isinstance(row.get(name), bool) for row in rows)
    ] if rows else []
    result = {}
    for name in names:
        values = [row[name] for row in rows if row.get(name) is not None]
        result[name] = {
            "count": len(values),
            "null_count": len(rows) - len(values),
            "null_percent": 100 * (len(rows) - len(values)) / len(rows),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "mean": mean(values) if values else None,
            "median": median(values) if values else None,
        }
    return result


def _season_summaries(rows, game_by_id) -> dict[str, dict[str, Any]]:
    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[game_by_id[row["target_game_id"]].season].append(row)
    result = {}
    for season, season_rows in sorted(grouped.items()):
        home_wins = sum(row["home_win"] is True for row in season_rows)
        aggregate_feature_values = [
            row["home_average_points_for"] for row in season_rows
        ] + [row["away_average_points_for"] for row in season_rows]
        aggregate_nulls = sum(value is None for value in aggregate_feature_values)
        result[str(season)] = {
            "target_rows": len(season_rows),
            "home_wins": home_wins,
            "home_losses": len(season_rows) - home_wins,
            "home_win_rate": home_wins / len(season_rows),
            "average_home_prior_games": mean(row["home_prior_games_used"] for row in season_rows),
            "average_away_prior_games": mean(row["away_prior_games_used"] for row in season_rows),
            "zero_history_targets": sum(
                row["home_prior_games_used"] == 0
                or row["away_prior_games_used"] == 0 for row in season_rows
            ),
            "average_home_rolling_3": mean(row["home_rolling_3_games_used"] for row in season_rows),
            "average_away_rolling_3": mean(row["away_rolling_3_games_used"] for row in season_rows),
            "average_home_rolling_5": mean(row["home_rolling_5_games_used"] for row in season_rows),
            "average_away_rolling_5": mean(row["away_rolling_5_games_used"] for row in season_rows),
            "aggregate_feature_null_percent": (
                100 * aggregate_nulls / len(aggregate_feature_values)
            ),
        }
    return result


def _class_balance(rows, game_by_id) -> dict[str, Any]:
    home_wins = sum(row["home_win"] is True for row in rows)
    return {
        "home_wins": home_wins,
        "home_losses": len(rows) - home_wins,
        "home_win_rate": home_wins / len(rows),
        "by_season": {
            season: values["home_win_rate"]
            for season, values in _season_summaries(rows, game_by_id).items()
        },
    }


def _canonical_row(row: dict[str, object]) -> dict[str, object]:
    canonical: dict[str, object] = {}
    for name, value in row.items():
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    f"dataset fingerprint datetime {name!r} must be timezone-aware"
                )
            value = value.astimezone(timezone.utc).isoformat()
        canonical[name] = value
    return canonical


def _close(left, right) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _finding(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _finding_if(condition, findings, code, detail) -> None:
    if condition:
        findings.append(_finding(code, detail))
