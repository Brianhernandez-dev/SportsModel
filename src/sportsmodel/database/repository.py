from sportsmodel.database.connection import get_connection
from sportsmodel.database.mlb_canonical_time_repository import CertifiedReader, aware, reject_uncertified036
from sportsmodel.database.mlb_retirement_guard import OperatorRefusal
from decimal import Decimal, InvalidOperation
from sportsmodel.models import GameResult, MarketSnapshot


def get_market_snapshots(
    game_id: int | None = None,
    include_live: bool = False,
    *,
    certified_reader: CertifiedReader | None = None,
) -> list[MarketSnapshot]:
    """
    Return market snapshots ordered chronologically.

    By default, only snapshots captured before the scheduled game start
    are returned. Set include_live=True to include live and post-start
    snapshots.

    Args:
        game_id:
            Optionally limit results to one canonical game.
        include_live:
            Include snapshots captured at or after the scheduled start.
    """

    if certified_reader is not None:
        if not isinstance(certified_reader, CertifiedReader):
            raise OperatorRefusal("Typed036 certified market reader required")
        if type(game_id) is not int or game_id <= 0 or type(include_live) is not bool:
            raise OperatorRefusal("Certified markets require an exact game and boolean live policy")
        rows = certified_reader.rows("markets", id=game_id, include_live=include_live)
        return [_certified_market_snapshot(row, game_id=game_id,
                    cutoff_time=certified_reader.cutoff_time) for row in rows]

    conditions: list[str] = []
    parameters: list[object] = []

    if not include_live:
        conditions.append("snapshot.snapshot_time < g.game_date")

    if game_id is not None:
        conditions.append("snapshot.effective_game_id = %s")
        parameters.append(game_id)

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            snapshot.odds_market_snapshot_id,
            snapshot.effective_game_id,
            snapshot.sportsbook_id,
            snapshot.market_type,
            snapshot.selection_name,
            snapshot.line_value,
            snapshot.price,
            snapshot.snapshot_time,
            snapshot.raw_acquisition_game_id
        FROM mlb_retirement_effective_markets() AS snapshot
        JOIN games g
            ON g.game_id = snapshot.effective_game_id
        {where_clause}
        ORDER BY
            snapshot.snapshot_time,
            snapshot.odds_market_snapshot_id;
    """

    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            reject_uncertified036(cursor)
            cursor.execute(query, parameters)
            rows = cursor.fetchall()

        return [
            MarketSnapshot(
                odds_market_snapshot_id=row[0],
                game_id=row[1],
                sportsbook_id=row[2],
                market_type=row[3],
                selection_name=row[4],
                line_value=row[5],
                price=row[6],
                snapshot_time=row[7],
                raw_acquisition_game_id=row[8],
            )
            for row in rows
        ]

    finally:
        connection.close()


def _certified_market_snapshot(row, *, game_id, cutoff_time):
    """Do not reattribute raw quotes or round NUMERIC line values through a float."""
    if row["effective_game_id"] != game_id or type(row["price"]) is not int:
        raise OperatorRefusal("Certified market identity/price differs")
    snapshot_time = aware(row["snapshot_time"])
    created_at = aware(row["created_at"])
    observed_at = None if row["observed_at"] is None else aware(row["observed_at"])
    if any(value > cutoff_time for value in (snapshot_time, created_at) + (() if observed_at is None else (observed_at,))):
        raise OperatorRefusal("Certified quote was not available at the original cutoff")
    line_value = row["line_value"]
    if line_value is not None:
        if not isinstance(line_value, (str, Decimal)):
            raise OperatorRefusal("Certified market line requires exact decimal bytes")
        try:
            line_value = Decimal(line_value)
        except InvalidOperation:
            raise OperatorRefusal("Malformed certified decimal line") from None
        if not line_value.is_finite():
            raise OperatorRefusal("Nonfinite certified decimal line")
    return MarketSnapshot(odds_market_snapshot_id=row["odds_market_snapshot_id"],
        game_id=row["effective_game_id"], sportsbook_id=row["sportsbook_id"],
        market_type=row["market_type"], selection_name=row["selection_name"],
        line_value=line_value, price=row["price"], snapshot_time=snapshot_time,
        raw_acquisition_game_id=row["raw_acquisition_game_id"])

def get_game_results() -> list[GameResult]:
    """
    Return final scores linked to canonical games.

    Only complete historical results with both scores are returned.
    """

    query = """
        SELECT
            g.game_id,
            hg.home_team,
            hg.away_team,
            hg.home_score,
            hg.away_score
        FROM games g
        JOIN historical_games hg
            ON hg.game_id = g.game_id
        WHERE hg.home_score IS NOT NULL
          AND NOT mlb_identity_is_retired(g.game_id)
          AND hg.away_score IS NOT NULL
        ORDER BY g.game_id;
    """

    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            reject_uncertified036(cursor)
            cursor.execute(query)
            rows = cursor.fetchall()

        return [
            GameResult(
                game_id=row[0],
                home_team=row[1],
                away_team=row[2],
                home_score=row[3],
                away_score=row[4],
            )
            for row in rows
        ]

    finally:
        connection.close()
