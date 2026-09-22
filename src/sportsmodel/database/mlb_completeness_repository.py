"""Event-level MLB history completeness checks for official workflows."""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sportsmodel.database.connection import get_connection


ConnectionFactory = Callable[[], Any]

FEATURE_TEAM_GAME_LIMIT = 200
FEATURE_START_LIMIT = 50
MLB_SOURCE_NAME = "mlb_stats"


@dataclass(frozen=True)
class HistoricalResultRecord:
    game_id: int
    mlb_game_id: int
    home_score: int
    away_score: int


@dataclass(frozen=True)
class TeamStatisticsRecord:
    team_id: int
    is_home: bool
    runs: int
    pitching_outs: int
    runs_allowed: int
    earned_runs_allowed: int
    hits_allowed: int
    home_runs_allowed: int
    walks_allowed: int
    strikeouts_recorded: int
    created_at: datetime


@dataclass(frozen=True)
class PitchingStatisticsRecord:
    team_id: int
    appearance_order: int
    is_starter: bool
    pitching_outs: int
    hits_allowed: int
    runs_allowed: int
    earned_runs_allowed: int
    home_runs_allowed: int
    walks_allowed: int
    strikeouts: int
    created_at: datetime


@dataclass(frozen=True)
class MlbGameCompletenessSnapshot:
    game_pk: int
    mapping_game_ids: tuple[int, ...]
    home_team_id: int | None
    away_team_id: int | None
    canonical_mlb_game_pks: tuple[str, ...] = ()
    results: tuple[HistoricalResultRecord, ...] = ()
    team_statistics: tuple[TeamStatisticsRecord, ...] = ()
    pitching_statistics: tuple[PitchingStatisticsRecord, ...] = ()

    @property
    def game_id(self) -> int | None:
        if len(self.mapping_game_ids) != 1:
            return None
        return self.mapping_game_ids[0]


class MlbCompletenessError(RuntimeError):
    """Raised when authoritative MLB history is not event-complete."""


def validate_mlb_game_completeness(
    snapshots: Iterable[MlbGameCompletenessSnapshot],
    *,
    as_of: datetime | None = None,
) -> tuple[str, ...]:
    """Return deterministic event-level completeness findings."""

    _validate_as_of(as_of)
    materialized = tuple(snapshots)
    issues: list[str] = []

    mapped_game_ids = Counter(
        snapshot.game_id
        for snapshot in materialized
        if snapshot.game_id is not None
    )

    for snapshot in materialized:
        identity_issues = _identity_issues(snapshot)
        issues.extend(identity_issues)

        game_id = snapshot.game_id
        if identity_issues or game_id is None:
            continue

        if mapped_game_ids[game_id] != 1:
            issues.append(
                _issue(
                    snapshot.game_pk,
                    "canonical game is mapped by multiple requested MLB IDs",
                )
            )
            continue

        matching_results = tuple(
            result
            for result in snapshot.results
            if result.game_id == game_id
            and result.mlb_game_id == snapshot.game_pk
        )

        if (
            len(matching_results) != 1
            or len(snapshot.results) != 1
        ):
            issues.append(
                _issue(
                    snapshot.game_pk,
                    "historical result coverage is missing or conflicting",
                )
            )

        teams = _available_team_statistics(
            snapshot.team_statistics,
            as_of=as_of,
        )
        pitchers = _available_pitching_statistics(
            snapshot.pitching_statistics,
            as_of=as_of,
        )

        team_issues = _validate_team_statistics(
            snapshot=snapshot,
            rows=teams,
            result=(
                matching_results[0]
                if len(matching_results) == 1
                else None
            ),
        )
        issues.extend(team_issues)

        issues.extend(
            _validate_pitching_statistics(
                snapshot=snapshot,
                team_rows=teams,
                pitching_rows=pitchers,
            )
        )

    return tuple(issues)


def assert_mlb_games_complete(
    game_pks: Iterable[int],
    *,
    connection_factory: ConnectionFactory = get_connection,
    as_of: datetime | None = None,
) -> None:
    """Fail closed unless every requested MLB event is complete."""

    normalized = _normalize_game_pks(game_pks)
    if not normalized:
        return

    snapshots = _load_completeness_snapshots(
        normalized,
        connection_factory=connection_factory,
    )
    issues = validate_mlb_game_completeness(
        snapshots,
        as_of=as_of,
    )

    if issues:
        raise MlbCompletenessError(
            "MLB historical completeness check failed: "
            + "; ".join(issues)
            + "."
        )


def assert_mlb_feature_history_complete(
    *,
    target_game_pks: Iterable[int],
    starting_pitcher_ids: Iterable[int] = (),
    cutoff_time: datetime,
    connection_factory: ConnectionFactory = get_connection,
) -> None:
    """Require complete PIT-valid history used by official MLB features."""

    _validate_as_of(cutoff_time)
    normalized_targets = _normalize_game_pks(target_game_pks)
    normalized_starters = _normalize_positive_ids(
        starting_pitcher_ids,
        field_name="Starting pitcher IDs",
    )
    if not normalized_targets:
        return

    target_snapshots = _load_completeness_snapshots(
        normalized_targets,
        connection_factory=connection_factory,
    )
    identity_issues = tuple(
        issue
        for snapshot in target_snapshots
        for issue in _identity_issues(snapshot)
    )

    target_game_ids = tuple(
        snapshot.game_id
        for snapshot in target_snapshots
        if snapshot.game_id is not None
    )
    if len(set(target_game_ids)) != len(target_game_ids):
        identity_issues += (
            "target schedule contains multiple MLB IDs for one canonical game",
        )

    if identity_issues:
        raise MlbCompletenessError(
            "MLB target identity check failed: "
            + "; ".join(identity_issues)
            + "."
        )

    target_team_ids = tuple(
        dict.fromkeys(
            team_id
            for snapshot in target_snapshots
            for team_id in (
                snapshot.home_team_id,
                snapshot.away_team_id,
            )
            if team_id is not None
        )
    )
    required_game_pks = _load_required_feature_game_pks(
        team_ids=target_team_ids,
        starting_pitcher_ids=normalized_starters,
        cutoff_time=cutoff_time,
        connection_factory=connection_factory,
    )

    assert_mlb_games_complete(
        required_game_pks,
        connection_factory=connection_factory,
        as_of=cutoff_time,
    )


def _identity_issues(
    snapshot: MlbGameCompletenessSnapshot,
) -> tuple[str, ...]:
    if len(snapshot.mapping_game_ids) != 1:
        return (
            _issue(
                snapshot.game_pk,
                "expected exactly one raw MLB identity mapping",
            ),
        )

    if (
        snapshot.home_team_id is None
        or snapshot.away_team_id is None
        or snapshot.home_team_id == snapshot.away_team_id
    ):
        return (
            _issue(
                snapshot.game_pk,
                "canonical identity is missing or invalid",
            ),
        )

    if snapshot.canonical_mlb_game_pks != (str(snapshot.game_pk),):
        return (
            _issue(
                snapshot.game_pk,
                "canonical game has conflicting MLB source mappings",
            ),
        )

    return ()


def _validate_team_statistics(
    *,
    snapshot: MlbGameCompletenessSnapshot,
    rows: tuple[TeamStatisticsRecord, ...],
    result: HistoricalResultRecord | None,
) -> tuple[str, ...]:
    expected = {
        snapshot.home_team_id: True,
        snapshot.away_team_id: False,
    }
    actual = Counter((row.team_id, row.is_home) for row in rows)

    if len(rows) != 2 or actual != Counter(expected.items()):
        return (
            _issue(
                snapshot.game_pk,
                "team-stat coverage is incomplete or misoriented",
            ),
        )

    if result is None:
        return ()

    by_team = {row.team_id: row for row in rows}
    home = by_team[snapshot.home_team_id]
    away = by_team[snapshot.away_team_id]

    if (
        home.runs != result.home_score
        or away.runs != result.away_score
        or home.runs_allowed != result.away_score
        or away.runs_allowed != result.home_score
    ):
        return (
            _issue(
                snapshot.game_pk,
                "result and team-stat scores disagree",
            ),
        )

    return ()


def _validate_pitching_statistics(
    *,
    snapshot: MlbGameCompletenessSnapshot,
    team_rows: tuple[TeamStatisticsRecord, ...],
    pitching_rows: tuple[PitchingStatisticsRecord, ...],
) -> tuple[str, ...]:
    expected_team_ids = {
        snapshot.home_team_id,
        snapshot.away_team_id,
    }
    actual_team_ids = {row.team_id for row in pitching_rows}

    if (
        not pitching_rows
        or not actual_team_ids.issubset(expected_team_ids)
        or any(
            sum(
                row.is_starter
                for row in pitching_rows
                if row.team_id == team_id
            )
            != 1
            for team_id in expected_team_ids
        )
    ):
        return (
            _issue(
                snapshot.game_pk,
                "pitching-stat coverage is incomplete or conflicts with teams",
            ),
        )

    for team_id in expected_team_ids:
        orders = sorted(
            row.appearance_order
            for row in pitching_rows
            if row.team_id == team_id
        )
        if orders != list(range(1, len(orders) + 1)):
            return (
                _issue(
                    snapshot.game_pk,
                    "pitching appearance order is incomplete",
                ),
            )

    team_by_id = {row.team_id: row for row in team_rows}
    if set(team_by_id) != expected_team_ids:
        return ()

    metric_pairs = (
        ("pitching_outs", "pitching_outs"),
        ("runs_allowed", "runs_allowed"),
        # Rule 9.16(i) permits team and summed pitcher earned runs to differ.
        ("hits_allowed", "hits_allowed"),
        ("home_runs_allowed", "home_runs_allowed"),
        ("walks_allowed", "walks_allowed"),
        ("strikeouts_recorded", "strikeouts"),
    )

    for team_id in expected_team_ids:
        team_row = team_by_id[team_id]
        team_pitchers = tuple(
            row
            for row in pitching_rows
            if row.team_id == team_id
        )
        if any(
            getattr(team_row, team_metric)
            != sum(
                getattr(row, pitcher_metric)
                for row in team_pitchers
            )
            for team_metric, pitcher_metric in metric_pairs
        ):
            return (
                _issue(
                    snapshot.game_pk,
                    "pitching-stat aggregates disagree with team statistics",
                ),
            )

    return ()


def _available_team_statistics(
    rows: tuple[TeamStatisticsRecord, ...],
    *,
    as_of: datetime | None,
) -> tuple[TeamStatisticsRecord, ...]:
    if as_of is None:
        return rows
    return tuple(row for row in rows if row.created_at <= as_of)


def _available_pitching_statistics(
    rows: tuple[PitchingStatisticsRecord, ...],
    *,
    as_of: datetime | None,
) -> tuple[PitchingStatisticsRecord, ...]:
    if as_of is None:
        return rows
    return tuple(row for row in rows if row.created_at <= as_of)


def _load_completeness_snapshots(
    game_pks: tuple[int, ...],
    *,
    connection_factory: ConnectionFactory,
) -> tuple[MlbGameCompletenessSnapshot, ...]:
    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    requested.game_pk,
                    source.game_id,
                    game.home_team_id,
                    game.away_team_id
                FROM unnest(%s::text[]) WITH ORDINALITY
                    AS requested(game_pk, requested_order)
                LEFT JOIN game_sources AS source
                    ON source.source_name = %s
                    AND source.external_game_id = requested.game_pk
                LEFT JOIN games AS game
                    ON game.game_id = source.game_id
                ORDER BY
                    requested.requested_order,
                    source.game_source_id;
                """,
                ([str(game_pk) for game_pk in game_pks], MLB_SOURCE_NAME),
            )
            identity_rows = cursor.fetchall()

        mapping_rows: dict[int, list[int]] = defaultdict(list)
        canonical_rows: dict[int, tuple[int | None, int | None]] = {}
        for game_pk_text, game_id, home_team_id, away_team_id in identity_rows:
            game_pk = int(game_pk_text)
            if game_id is not None:
                normalized_game_id = int(game_id)
                mapping_rows[game_pk].append(normalized_game_id)
                canonical_rows[normalized_game_id] = (
                    None if home_team_id is None else int(home_team_id),
                    None if away_team_id is None else int(away_team_id),
                )

        game_ids = tuple(
            dict.fromkeys(
                game_id
                for values in mapping_rows.values()
                for game_id in values
            )
        )
        canonical_mlb_sources = _load_canonical_mlb_sources(
            connection,
            game_ids=game_ids,
        )
        results = _load_results(
            connection,
            game_ids=game_ids,
            game_pks=game_pks,
        )
        teams = _load_team_statistics(connection, game_ids=game_ids)
        pitchers = _load_pitching_statistics(connection, game_ids=game_ids)

        snapshots: list[MlbGameCompletenessSnapshot] = []
        for game_pk in game_pks:
            mapped = tuple(mapping_rows[game_pk])
            canonical = (
                canonical_rows.get(mapped[0], (None, None))
                if len(mapped) == 1
                else (None, None)
            )
            mapped_set = set(mapped)
            snapshots.append(
                MlbGameCompletenessSnapshot(
                    game_pk=game_pk,
                    mapping_game_ids=mapped,
                    home_team_id=canonical[0],
                    away_team_id=canonical[1],
                    canonical_mlb_game_pks=tuple(
                        canonical_mlb_sources.get(
                            mapped[0],
                            (),
                        )
                        if len(mapped) == 1
                        else ()
                    ),
                    results=tuple(
                        row
                        for row in results
                        if row.mlb_game_id == game_pk
                        or row.game_id in mapped_set
                    ),
                    team_statistics=tuple(
                        row
                        for game_id, row in teams
                        if game_id in mapped_set
                    ),
                    pitching_statistics=tuple(
                        row
                        for game_id, row in pitchers
                        if game_id in mapped_set
                    ),
                )
            )

        return tuple(snapshots)
    finally:
        connection.close()


def _load_canonical_mlb_sources(
    connection: Any,
    *,
    game_ids: tuple[int, ...],
) -> dict[int, tuple[str, ...]]:
    if not game_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT game_id, external_game_id
            FROM game_sources
            WHERE game_id = ANY(%s)
              AND source_name = %s
            ORDER BY game_id, game_source_id;
            """,
            (list(game_ids), MLB_SOURCE_NAME),
        )
        grouped: dict[int, list[str]] = defaultdict(list)
        for game_id, external_game_id in cursor.fetchall():
            grouped[int(game_id)].append(str(external_game_id))
        return {
            game_id: tuple(external_ids)
            for game_id, external_ids in grouped.items()
        }


def _load_results(
    connection: Any,
    *,
    game_ids: tuple[int, ...],
    game_pks: tuple[int, ...],
) -> tuple[HistoricalResultRecord, ...]:
    if not game_ids:
        return ()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT game_id, mlb_game_id, home_score, away_score
            FROM historical_games
            WHERE game_id = ANY(%s) OR mlb_game_id = ANY(%s);
            """,
            (list(game_ids), list(game_pks)),
        )
        return tuple(HistoricalResultRecord(*row) for row in cursor.fetchall())


def _load_team_statistics(
    connection: Any,
    *,
    game_ids: tuple[int, ...],
) -> tuple[tuple[int, TeamStatisticsRecord], ...]:
    if not game_ids:
        return ()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                game_id, team_id, is_home, runs, pitching_outs,
                runs_allowed, earned_runs_allowed, hits_allowed,
                home_runs_allowed, walks_allowed, strikeouts_recorded,
                created_at
            FROM team_game_statistics
            WHERE game_id = ANY(%s);
            """,
            (list(game_ids),),
        )
        return tuple(
            (int(row[0]), TeamStatisticsRecord(*row[1:]))
            for row in cursor.fetchall()
        )


def _load_pitching_statistics(
    connection: Any,
    *,
    game_ids: tuple[int, ...],
) -> tuple[tuple[int, PitchingStatisticsRecord], ...]:
    if not game_ids:
        return ()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                game_id, team_id, appearance_order, is_starter,
                pitching_outs, hits_allowed, runs_allowed,
                earned_runs_allowed, home_runs_allowed, walks_allowed,
                strikeouts, created_at
            FROM player_game_pitching_statistics
            WHERE game_id = ANY(%s);
            """,
            (list(game_ids),),
        )
        return tuple(
            (int(row[0]), PitchingStatisticsRecord(*row[1:]))
            for row in cursor.fetchall()
        )


def _load_required_feature_game_pks(
    *,
    team_ids: tuple[int, ...],
    starting_pitcher_ids: tuple[int, ...] = (),
    cutoff_time: datetime,
    connection_factory: ConnectionFactory,
) -> tuple[int, ...]:
    if not team_ids and not starting_pitcher_ids:
        return ()

    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH team_games AS (
                    SELECT
                        requested.team_id,
                        game.game_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY requested.team_id
                            ORDER BY game.game_date DESC, game.game_id DESC
                        ) AS history_rank
                    FROM unnest(%s::integer[]) AS requested(team_id)
                    JOIN games AS game
                        ON game.home_team_id = requested.team_id
                        OR game.away_team_id = requested.team_id
                    WHERE game.game_date < %s
                      AND EXISTS (
                          SELECT 1
                          FROM game_sources AS source
                          WHERE source.game_id = game.game_id
                            AND source.source_name = %s
                      )
                ), starter_games AS (
                    SELECT
                        requested.baseball_player_id,
                        pitching.game_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY requested.baseball_player_id
                            ORDER BY game.game_date DESC, game.game_id DESC
                        ) AS history_rank
                    FROM unnest(%s::bigint[])
                        AS requested(baseball_player_id)
                    JOIN player_game_pitching_statistics AS pitching
                        ON pitching.baseball_player_id = (
                            requested.baseball_player_id
                        )
                        AND pitching.is_starter = TRUE
                    JOIN games AS game
                        ON game.game_id = pitching.game_id
                    WHERE game.game_date < %s
                      AND EXISTS (
                          SELECT 1
                          FROM game_sources AS source
                          WHERE source.game_id = game.game_id
                            AND source.source_name = %s
                      )
                ), required_games AS (
                    SELECT game_id
                    FROM team_games
                    WHERE history_rank <= %s
                    UNION
                    SELECT game_id
                    FROM starter_games
                    WHERE history_rank <= %s
                )
                SELECT source.external_game_id
                FROM required_games
                JOIN game_sources AS source
                    ON source.game_id = required_games.game_id
                    AND source.source_name = %s
                ORDER BY source.external_game_id;
                """,
                (
                    list(team_ids),
                    cutoff_time,
                    MLB_SOURCE_NAME,
                    list(starting_pitcher_ids),
                    cutoff_time,
                    MLB_SOURCE_NAME,
                    FEATURE_TEAM_GAME_LIMIT,
                    FEATURE_START_LIMIT,
                    MLB_SOURCE_NAME,
                ),
            )
            external_ids = tuple(row[0] for row in cursor.fetchall())
    finally:
        connection.close()

    game_pks: list[int] = []
    for external_id in external_ids:
        text = str(external_id)
        if not text.isdigit() or int(text) <= 0:
            raise MlbCompletenessError(
                "Required MLB feature history contains an invalid source ID."
            )
        game_pks.append(int(text))

    return tuple(dict.fromkeys(game_pks))


def _normalize_game_pks(game_pks: Iterable[int]) -> tuple[int, ...]:
    materialized = tuple(game_pks)
    if any(type(game_pk) is not int or game_pk <= 0 for game_pk in materialized):
        raise ValueError("MLB gamePk values must be positive integers.")
    return tuple(dict.fromkeys(materialized))


def _normalize_positive_ids(
    values: Iterable[int],
    *,
    field_name: str,
) -> tuple[int, ...]:
    materialized = tuple(values)
    if any(type(value) is not int or value <= 0 for value in materialized):
        raise ValueError(f"{field_name} must be positive integers.")
    return tuple(dict.fromkeys(materialized))


def _validate_as_of(as_of: datetime | None) -> None:
    if as_of is not None and (
        as_of.tzinfo is None or as_of.utcoffset() is None
    ):
        raise ValueError("Completeness cutoff must be timezone-aware.")


def _issue(game_pk: int, detail: str) -> str:
    return f"gamePk {game_pk}: {detail}"
