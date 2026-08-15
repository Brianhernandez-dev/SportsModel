"""Pure planning and validation for the approved nflverse historical backfill."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from typing import Any

from sportsmodel.nfl.coverage_audit import select_rows
from sportsmodel.nfl.models import NflGameStatus, NflSeasonType
from sportsmodel.nfl.nflverse_parser import (
    REVIEWED_TIMESTAMP_OVERRIDES,
    SOURCE_NAME,
    parse_nflverse_game_records,
    parse_nflverse_team_game_statistics_records,
)


CANCELLED_BUF_CIN_GAME_ID = "2022_17_BUF_CIN"
_STAT_SEASON_TYPES = frozenset({"REG", "POST"})


@dataclass(frozen=True)
class BackfillIssue:
    """A blocking reason that prevents a historical plan from being valid."""

    category: str
    external_game_id: str | None
    detail: str


@dataclass(frozen=True)
class HistoricalBackfillPlan:
    season_from: int
    season_to: int
    selected_schedule_rows: tuple[Mapping[str, Any], ...]
    accepted_schedule_rows: tuple[Mapping[str, Any], ...]
    quarantined_schedule_rows: tuple[Mapping[str, Any], ...]
    selected_team_statistics_rows: tuple[Mapping[str, Any], ...]
    accepted_team_statistics_rows: tuple[Mapping[str, Any], ...]
    issues: tuple[BackfillIssue, ...]
    reviewed_override_game_ids: tuple[str, ...]
    cancelled_buf_cin_absent: bool

    @property
    def is_valid(self) -> bool:
        return not self.issues


def build_nflverse_historical_backfill_plan(
    schedule_rows: Iterable[Mapping[str, Any]],
    team_statistics_rows: Iterable[Mapping[str, Any]],
    *,
    team_identities: Mapping[str, str],
    season_from: int = 2018,
    season_to: int = 2025,
) -> HistoricalBackfillPlan:
    """Build a deterministic, provider-data-only historical backfill plan."""

    if season_from > season_to:
        raise ValueError("season_from cannot be greater than season_to")

    raw_schedule = tuple(dict(row) for row in schedule_rows)
    raw_stats = tuple(dict(row) for row in team_statistics_rows)
    selected_schedule = tuple(
        sorted(
            (
                selected
                for row in raw_schedule
                for selected in select_rows([row], season_from, season_to)
            ),
            key=_schedule_key,
        )
    )
    selected_stats = tuple(
        sorted(
            (
                dict(row)
                for row in raw_stats
                if _in_stat_scope(row, season_from, season_to)
            ),
            key=_statistics_key,
        )
    )

    issues = [
        BackfillIssue(
            "cancelled_game_present",
            CANCELLED_BUF_CIN_GAME_ID,
            f"Cancelled 2022 BUF-CIN must be absent from provider {source} input",
        )
        for source, rows in (
            ("schedule", raw_schedule),
            ("statistics", raw_stats),
        )
        for row in rows
        if _external_game_id(row) == CANCELLED_BUF_CIN_GAME_ID
    ]
    accepted_schedule: list[Mapping[str, Any]] = []
    quarantined_schedule: list[Mapping[str, Any]] = []
    parsed_games = []
    reviewed_ids: set[str] = set()

    for row in selected_schedule:
        game_id = _external_game_id(row)
        if game_id == CANCELLED_BUF_CIN_GAME_ID:
            quarantined_schedule.append(row)
            continue
        try:
            game = parse_nflverse_game_records(
                [row], team_identities=team_identities
            )[0]
        except (TypeError, ValueError) as error:
            quarantined_schedule.append(row)
            category = (
                "reviewed_override_evidence_mismatch"
                if (SOURCE_NAME, game_id) in REVIEWED_TIMESTAMP_OVERRIDES
                and "override does not match provider evidence" in str(error)
                else "schedule_parser_rejection"
            )
            issues.append(BackfillIssue(category, game_id, str(error)))
        else:
            accepted_schedule.append(row)
            parsed_games.append(game)
            if (SOURCE_NAME, game.external_game_id) in REVIEWED_TIMESTAMP_OVERRIDES:
                reviewed_ids.add(game.external_game_id)

    accepted_stats: list[Mapping[str, Any]] = []
    parsed_stats = []
    for row in selected_stats:
        game_id = _external_game_id(row)
        if game_id == CANCELLED_BUF_CIN_GAME_ID:
            continue
        try:
            record = parse_nflverse_team_game_statistics_records(
                [row], team_identities=team_identities
            )[0]
        except (TypeError, ValueError) as error:
            issues.append(BackfillIssue(
                "team_statistics_parser_rejection", game_id, str(error)
            ))
        else:
            accepted_stats.append(row)
            parsed_stats.append(record)

    schedule_id_counts = Counter(
        game.external_game_id for game in parsed_games
    )
    for game_id, count in sorted(schedule_id_counts.items()):
        if count > 1:
            issues.append(BackfillIssue(
                "duplicate_schedule_game_id",
                game_id,
                f"Provider game_id has {count} accepted schedule rows",
            ))

    _reconcile(parsed_games, parsed_stats, issues)

    cancelled_absent = not any(
        _external_game_id(row) == CANCELLED_BUF_CIN_GAME_ID
        for row in (*raw_schedule, *raw_stats)
    )
    return HistoricalBackfillPlan(
        season_from=season_from,
        season_to=season_to,
        selected_schedule_rows=selected_schedule,
        accepted_schedule_rows=tuple(accepted_schedule),
        quarantined_schedule_rows=tuple(quarantined_schedule),
        selected_team_statistics_rows=selected_stats,
        accepted_team_statistics_rows=tuple(accepted_stats),
        issues=tuple(sorted(issues, key=_issue_key)),
        reviewed_override_game_ids=tuple(sorted(reviewed_ids)),
        cancelled_buf_cin_absent=cancelled_absent,
    )


def _reconcile(games: list[Any], stats: list[Any], issues: list[BackfillIssue]) -> None:
    games_by_id = {game.external_game_id: game for game in games}
    stats_by_id: dict[str, list[Any]] = defaultdict(list)
    for record in stats:
        stats_by_id[record.external_game_id].append(record)

    for game_id in sorted(stats_by_id.keys() - games_by_id.keys()):
        for record in stats_by_id[game_id]:
            issues.append(BackfillIssue(
                "orphan_team_statistics", game_id,
                f"Statistics team {record.team_external_id} references an unknown game_id",
            ))

    for game_id, game in sorted(games_by_id.items()):
        game_stats = stats_by_id.get(game_id, [])
        if game.status is NflGameStatus.UNPLAYED:
            for record in game_stats:
                issues.append(BackfillIssue(
                    "statistics_for_unplayed_game", game_id,
                    f"Statistics team {record.team_external_id} references an unplayed game",
                ))
            continue

        count = len(game_stats)
        if count == 0:
            issues.append(BackfillIssue(
                "zero_team_statistics_rows", game_id,
                "Final game has zero accepted team-statistics rows",
            ))
        elif count == 1:
            issues.append(BackfillIssue(
                "one_team_statistics_row", game_id,
                "Final game has one accepted team-statistics row; expected two",
            ))
        elif count > 2:
            issues.append(BackfillIssue(
                "more_than_two_team_statistics_rows", game_id,
                f"Final game has {count} accepted team-statistics rows; expected two",
            ))

        team_counts = Counter(record.team_external_id for record in game_stats)
        for team_id, duplicate_count in sorted(team_counts.items()):
            if duplicate_count > 1:
                issues.append(BackfillIssue(
                    "duplicate_team_statistics_row", game_id,
                    f"Team {team_id} has {duplicate_count} accepted rows",
                ))

        participants = {game.home_external_team_id, game.away_external_team_id}
        observed_teams = {record.team_external_id for record in game_stats}
        if count == 2 and observed_teams != participants:
            issues.append(BackfillIssue(
                "team_participant_mismatch", game_id,
                "The two statistics teams do not equal the schedule participants",
            ))
        for record in sorted(game_stats, key=lambda item: (item.team_external_id, item.opponent_external_id)):
            if record.team_external_id not in participants:
                issues.append(BackfillIssue(
                    "team_participant_mismatch", game_id,
                    f"Statistics team {record.team_external_id} is not a schedule participant",
                ))
            expected_opponents = participants - {record.team_external_id}
            if len(expected_opponents) != 1 or record.opponent_external_id not in expected_opponents:
                issues.append(BackfillIssue(
                    "opponent_mismatch", game_id,
                    f"Team {record.team_external_id} has opponent {record.opponent_external_id}",
                ))
            if record.season != game.season:
                issues.append(BackfillIssue(
                    "season_mismatch", game_id,
                    f"Statistics season {record.season} does not match schedule season {game.season}",
                ))
            if record.week != game.week:
                issues.append(BackfillIssue(
                    "week_mismatch", game_id,
                    f"Statistics week {record.week} does not match schedule week {game.week}",
                ))
            if record.season_type is not game.season_type:
                issues.append(BackfillIssue(
                    "season_type_mismatch", game_id,
                    f"Statistics season type {record.season_type.value} does not match schedule season type {game.season_type.value}",
                ))


def _in_stat_scope(row: Mapping[str, Any], season_from: int, season_to: int) -> bool:
    try:
        season = int(row.get("season"))
    except (TypeError, ValueError):
        return False
    return season_from <= season <= season_to and row.get("season_type") in _STAT_SEASON_TYPES


def _external_game_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("game_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _schedule_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (int(row["season"]), str(row.get("game_id") or ""), _stable_row(row))


def _statistics_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["season"]), _sortable_integer(row.get("week")),
        str(row.get("game_id") or ""), str(row.get("team") or ""),
        _stable_row(row),
    )


def _sortable_integer(value: Any) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _stable_row(row: Mapping[str, Any]) -> str:
    return json.dumps(dict(row), sort_keys=True, default=str, separators=(",", ":"))


def _issue_key(issue: BackfillIssue) -> tuple[str, str, str]:
    return (issue.category, issue.external_game_id or "", issue.detail)
