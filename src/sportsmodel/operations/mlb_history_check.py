"""Read-only, sport-scoped H-1 audit without prediction or provider execution."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sportsmodel.database import mlb_completeness_repository as completeness
from sportsmodel.database.mlb_operator_guard import (
    OperatorRefusal, SnapshotConnection, load_mlb_teams, positive, verify_target,
)
from sportsmodel.features.builders.starting_pitcher import SEASON_START_LIMIT


def _load_retained_starter_history(cursor, starters, cutoff_time):
    """Mirror persisted feature starts, independently of game-source identity."""
    if completeness.FEATURE_START_LIMIT != SEASON_START_LIMIT:
        raise OperatorRefusal("Starter feature/completeness window limits disagree")
    # The feature repository excludes invalid orientation; do not silently certify
    # malformed eligible persisted appearances as a clean history window.
    cursor.execute("""SELECT pitching.game_id FROM player_game_pitching_statistics pitching
        JOIN games g USING(game_id)
        WHERE pitching.baseball_player_id=ANY(%s) AND pitching.is_starter=TRUE
          AND g.game_date < %s AND pitching.created_at <= %s
          AND (g.home_team_id IS NULL OR g.away_team_id IS NULL
               OR g.home_team_id=g.away_team_id
               OR pitching.team_id NOT IN (g.home_team_id,g.away_team_id)) LIMIT 1""",
        (list(sorted(set(starters))), cutoff_time, cutoff_time))
    if cursor.fetchall():
        raise OperatorRefusal("Malformed persisted starter team orientation")
    cursor.execute("""WITH ranked_starts AS (
        SELECT pitching.baseball_player_id,g.game_id,g.game_date,pitching.team_id,
            g.home_team_id,g.away_team_id,pitching.created_at,
            row_number() OVER(PARTITION BY pitching.baseball_player_id
                ORDER BY g.game_date DESC,g.game_id DESC) AS rank
        FROM player_game_pitching_statistics pitching JOIN games g USING(game_id)
        WHERE pitching.baseball_player_id=ANY(%s) AND pitching.is_starter=TRUE
          AND g.game_date < %s AND pitching.created_at <= %s
          AND (g.home_team_id=pitching.team_id OR g.away_team_id=pitching.team_id)
          AND g.home_team_id IS NOT NULL AND g.away_team_id IS NOT NULL
    ) SELECT baseball_player_id,game_id,game_date,team_id,home_team_id,away_team_id,created_at,rank
        FROM ranked_starts WHERE rank <= %s ORDER BY baseball_player_id,rank""",
        (list(sorted(set(starters))), cutoff_time, cutoff_time, SEASON_START_LIMIT))
    rows = cursor.fetchall()
    seen = set()
    for player, game, start, team, home, away, created, rank in rows:
        key = (player, game)
        if (key in seen or player not in starters or home == away or team not in (home, away)
                or start >= cutoff_time or created > cutoff_time
                or not 1 <= rank <= SEASON_START_LIMIT):
            raise OperatorRefusal("Malformed or ambiguous retained starter history")
        seen.add(key)
    if rows:
        load_mlb_teams(cursor, {i for row in rows for i in row[4:6]})
    return rows


def check_feature_history(*, target_date, target_game_ids, starting_pitcher_ids,
                          cutoff_time, target, connection_factory, process_probe=None):
    if type(target_date) is not date or not isinstance(cutoff_time, datetime):
        raise OperatorRefusal("Explicit prediction date and aware cutoff required")
    if cutoff_time.tzinfo is None or cutoff_time.utcoffset() is None:
        raise OperatorRefusal("Cutoff must be timezone-aware")
    ids = tuple(positive(i) for i in target_game_ids)
    starters = tuple(positive(i) for i in starting_pitcher_ids)
    if not ids or len(ids) > 16 or len(ids) != len(set(ids)) or len(starters) != 2 * len(ids):
        raise OperatorRefusal("Nonempty exact target slate and two canonical starters per game required")
    if len(set(starters)) != len(starters):
        raise OperatorRefusal("Supplied canonical starter IDs must be unique across the target slate")
    zone = ZoneInfo("America/Los_Angeles")
    start = datetime.combine(target_date, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(target_date + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    connection = connection_factory()
    report = {"version": 1, "domain": "MLB", "target_prediction_date": target_date.isoformat(),
              "cutoff_time": cutoff_time.isoformat(), "target_game_ids": list(ids),
              "starting_pitcher_ids": list(starters), "status": "FAIL", "issues": []}
    try:
        connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
        kwargs = {} if process_probe is None else {"process_probe": process_probe}
        report["guard"] = verify_target(connection, target, readonly=True, **kwargs)
        with connection.cursor() as cursor:
            cursor.execute("""SELECT g.game_id,g.game_date,g.home_team_id,g.away_team_id
                FROM games g WHERE g.game_date >= %s AND g.game_date < %s
                AND EXISTS(SELECT 1 FROM baseball_team_sources h WHERE h.team_id=g.home_team_id AND h.source_name='mlb_stats')
                AND EXISTS(SELECT 1 FROM baseball_team_sources a WHERE a.team_id=g.away_team_id AND a.source_name='mlb_stats')
                ORDER BY g.game_id""", (start, end))
            slate = cursor.fetchall()
            if set(row[0] for row in slate) != set(ids):
                raise OperatorRefusal("Requested slate differs from retained canonical MLB date")
            if cutoff_time >= min(row[1] for row in slate):
                raise OperatorRefusal("Cutoff must precede every target game")
            cursor.execute("SELECT transaction_timestamp()")
            if cutoff_time > cursor.fetchone()[0]:
                raise OperatorRefusal("Future cutoff cannot certify PIT availability")
            team_ids = tuple(sorted({i for row in slate for i in row[2:]}))
            report["teams"] = load_mlb_teams(cursor, team_ids)
            cursor.execute("""SELECT p.baseball_player_id,s.external_player_id
                FROM baseball_players p JOIN baseball_player_sources s USING(baseball_player_id)
                WHERE p.baseball_player_id=ANY(%s) AND s.source_name='mlb_stats'
                ORDER BY p.baseball_player_id,s.baseball_player_source_id""", (list(set(starters)),))
            source_players = cursor.fetchall()
            if (len(source_players) != len(set(starters))
                    or {r[0] for r in source_players} != set(starters)
                    or any(not r[1].isdigit() or int(r[1]) <= 0 for r in source_players)):
                raise OperatorRefusal("Missing/ambiguous authoritative MLB starter source")
            cursor.execute("""WITH ranked AS (
                SELECT requested.team_id,g.game_id,g.game_date,g.home_team_id,g.away_team_id,
                    row_number() OVER(PARTITION BY requested.team_id ORDER BY g.game_date DESC,g.game_id DESC) AS rank
                FROM unnest(%s::integer[]) requested(team_id) JOIN games g
                    ON g.home_team_id=requested.team_id OR g.away_team_id=requested.team_id
                WHERE g.game_date < %s
            ) SELECT team_id,game_id,game_date,home_team_id,away_team_id,rank FROM ranked
                WHERE rank <= %s ORDER BY team_id,rank""",
                (list(team_ids), cutoff_time, completeness.FEATURE_TEAM_GAME_LIMIT))
            retained = cursor.fetchall()
            retained_team_ids = {i for row in retained for i in row[3:5]}
            if retained_team_ids:
                load_mlb_teams(cursor, retained_team_ids)
            starter_retained = _load_retained_starter_history(cursor, starters, cutoff_time)
            team_history_ids = {row[1] for row in retained}
            starter_history_ids = {row[1] for row in starter_retained}
            retained_ids = sorted(team_history_ids | starter_history_ids | set(ids))
            cursor.execute("""SELECT game_id,external_game_id FROM game_sources
                WHERE game_id=ANY(%s) AND source_name='mlb_stats'
                ORDER BY game_id,game_source_id""", (retained_ids,))
            sources = cursor.fetchall()
            missing = []
            target_pks = []
            independent_history_pks = []
            for game_id in retained_ids:
                mappings = [r[1] for r in sources if r[0] == game_id]
                if (len(mappings) != 1 or not isinstance(mappings[0], str)
                        or not mappings[0].isascii() or not mappings[0].isdigit() or int(mappings[0]) <= 0):
                    missing.append(game_id)
                else:
                    if game_id in ids:
                        target_pks.append(int(mappings[0]))
                    if game_id in team_history_ids | starter_history_ids:
                        independent_history_pks.append(int(mappings[0]))
            report["retained_history_games"] = [dict(team_id=r[0], game_id=r[1], start=r[2].isoformat(), rank=r[5]) for r in retained]
            report["retained_team_history_games"] = report["retained_history_games"]
            report["retained_starter_history_games"] = [dict(baseball_player_id=r[0], game_id=r[1], start=r[2].isoformat(), team_id=r[3], created_at=r[6].isoformat(), rank=r[7]) for r in starter_retained]
            report["team_history_games_missing_mlb_stats_identity"] = sorted(team_history_ids & set(missing))
            report["starter_history_games_missing_mlb_stats_identity"] = sorted(starter_history_ids & set(missing))
            report["games_missing_mlb_stats_identity"] = missing
            if missing:
                report["issues"].append("Retained target/history identities are invisible or ambiguous to MLB completeness")
        factory = lambda: SnapshotConnection(connection)
        required = completeness._load_required_feature_game_pks(
            team_ids=team_ids, starting_pitcher_ids=starters,
            cutoff_time=cutoff_time, connection_factory=factory)
        # Audit mapped independent windows even if the core mapping-filtered
        # selector chose a different window. Core production semantics unchanged.
        required = tuple(sorted(set(required) | set(independent_history_pks)))
        snapshots = completeness._load_completeness_snapshots(required, connection_factory=factory)
        with connection.cursor() as cursor:
            snapshot_teams = {i for s in snapshots for i in (s.home_team_id, s.away_team_id) if i is not None}
            if snapshot_teams:
                load_mlb_teams(cursor, snapshot_teams)
        issues = completeness.validate_mlb_game_completeness(snapshots, as_of=cutoff_time)
        report["visible_required_game_pks"] = list(required)
        report["visible_required_canonical_game_ids"] = sorted({s.game_id for s in snapshots if s.game_id is not None})
        report["required_canonical_game_ids"] = sorted(set(report["visible_required_canonical_game_ids"]) | team_history_ids | starter_history_ids)
        report["games_missing_required_feature_history"] = list(issues)
        report["feature_window"] = {"team_limit": completeness.FEATURE_TEAM_GAME_LIMIT,
                                    "starter_limit": completeness.FEATURE_START_LIMIT,
                                    "retained_earliest": min((r[2] for r in retained), default=None),
                                    "retained_latest": max((r[2] for r in retained), default=None),
                                    "cutoff": cutoff_time}
        report["issues"].extend(issues)
        if not missing and not issues:
            completeness.assert_mlb_feature_history_complete(
                target_game_pks=target_pks, starting_pitcher_ids=starters,
                cutoff_time=cutoff_time, connection_factory=factory)
            report["status"] = "PASS"
        return report
    finally:
        connection.rollback()
        connection.close()
