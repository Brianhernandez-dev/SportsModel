"""Existing-only MLB identities and narrowly scoped recovery persistence."""

from dataclasses import asdict

from sportsmodel.database.boxscore_repository import save_parsed_boxscore_with_cursor
from sportsmodel.ingest.mlb_players import normalize_mlb_player


def load_mlb_identity(cursor, game_pk: int, *, lock: bool = False) -> dict:
    """Count raw MLB mappings before checking their target; never match/create."""
    if type(game_pk) is not int or game_pk <= 0:
        raise ValueError('MLB gamePk must be a positive integer')
    cursor.execute(
        "SELECT game_source_id, game_id FROM game_sources "
        "WHERE source_name='mlb_stats' AND external_game_id=%s "
        "ORDER BY game_source_id" + (" FOR SHARE" if lock else ""),
        (str(game_pk),),
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError(f"MLB {game_pk}: expected exactly one raw mapping")
    source_id, game_id = rows[0]
    cursor.execute(
        "SELECT game_date,home_team_id,away_team_id,mlb_game_id,odds_api_event_id "
        "FROM games WHERE game_id=%s" + (" FOR UPDATE" if lock else ""),
        (game_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"MLB {game_pk}: dangling canonical target")
    cursor.execute(
        "SELECT game_source_id,source_name,external_game_id FROM game_sources "
        "WHERE game_id=%s ORDER BY game_source_id" + (" FOR SHARE" if lock else ""),
        (game_id,),
    )
    return dict(game_id=game_id, source_id=source_id, start=row[0].isoformat(),
                home_team_id=row[1], away_team_id=row[2], mlb_game_id=row[3],
                odds_api_event_id=row[4], sources=[list(r) for r in cursor.fetchall()])


def resolve_existing_mlb_game(cursor, game_pk: int, *, home_team_id: int,
                              away_team_id: int, lock: bool = False) -> dict:
    identity = load_mlb_identity(cursor, game_pk, lock=lock)
    if (identity['home_team_id'], identity['away_team_id']) != (home_team_id, away_team_id):
        raise ValueError(f"MLB {game_pk}: authoritative orientation conflicts")
    return identity


def resolve_mlb_team(cursor, external_id: int, *, lock: bool = False) -> int:
    cursor.execute(
        "SELECT s.team_id FROM baseball_team_sources s JOIN teams t USING(team_id) "
        "WHERE s.source_name='mlb_stats' AND s.external_team_id=%s" +
        (" FOR SHARE OF s,t" if lock else ""), (str(external_id),),
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError(f"Missing/ambiguous existing MLB team {external_id}")
    return rows[0][0]


def resolve_mlb_player(cursor, external_id: int, *, lock: bool = False):
    cursor.execute(
        "SELECT s.baseball_player_id,p.full_name,p.bats,p.throws,p.primary_position,"
        "p.active_from,p.active_through,p.is_active FROM baseball_player_sources s "
        "LEFT JOIN baseball_players p USING(baseball_player_id) "
        "WHERE s.source_name='mlb_stats' AND s.external_player_id=%s" +
        (" FOR SHARE OF s" if lock else ""), (str(external_id),),
    )
    rows = cursor.fetchall()
    if len(rows) > 1 or (rows and rows[0][1] is None):
        raise ValueError(f"Dangling/ambiguous MLB player {external_id}")
    return rows[0] if rows else None


def insert_missing_mlb_player(cursor, payload: dict, observed_at: str) -> int:
    """Create player and MLB source atomically; no assignments or other identities."""
    p = asdict(normalize_mlb_player(payload))
    cursor.execute(
        "INSERT INTO baseball_players(full_name,bats,throws,primary_position,"
        "active_from,active_through,is_active,last_synced_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING baseball_player_id",
        tuple(p[k] for k in ('full_name','bats','throws','primary_position',
                            'active_from','active_through','is_active')) + (observed_at,),
    )
    player_id = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO baseball_player_sources(baseball_player_id,source_name,external_player_id) "
        "VALUES(%s,'mlb_stats',%s)", (player_id, p['external_player_id']),
    )
    return player_id


def save_recovery_boxscore(cursor, parsed) -> None:
    save_parsed_boxscore_with_cursor(cursor, parsed)


def validate_result_scope(cursor, game_id: int, game_pk: int, schedule_date) -> None:
    """Never let the maintained MLB-key upsert move another game's history."""
    cursor.execute(
        "SELECT game_id,mlb_game_id,game_date FROM historical_games "
        "WHERE game_id=%s OR mlb_game_id=%s FOR UPDATE", (game_id, game_pk),
    )
    if any(row != (game_id, game_pk, schedule_date) for row in cursor.fetchall()):
        raise ValueError('Existing historical result conflicts with approved identity/date')
