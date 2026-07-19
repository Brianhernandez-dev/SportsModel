from sportsmodel.database.boxscore_repository import (
    save_parsed_boxscore,
)
from sportsmodel.ingest.boxscore_parser import parse_boxscore
from sportsmodel.ingest.mlb_boxscore import (
    fetch_boxscore,
    fetch_live_feed,
)


def ingest_boxscore(
    *,
    game_id: int,
    game_pk: int,
) -> None:
    """
    Download, parse, and persist one MLB box score.

    Args:
        game_id:
            Canonical SportsModel game identifier.

        game_pk:
            MLB Stats API gamePk.
    """

    live_feed = fetch_live_feed(game_pk)

    boxscore = fetch_boxscore(game_pk)

    parsed_boxscore = parse_boxscore(
        game_id=game_id,
        game_pk=game_pk,
        live_feed=live_feed,
        boxscore=boxscore,
    )

    save_parsed_boxscore(parsed_boxscore)