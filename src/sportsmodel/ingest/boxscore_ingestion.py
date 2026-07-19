from sportsmodel.database.boxscore_repository import (
    save_parsed_boxscore,
)
from sportsmodel.database.player_repository import (
    get_player_ids_by_source,
)
from sportsmodel.database.team_assignment_repository import (
    get_team_ids_by_source,
)
from sportsmodel.ingest.boxscore_parser import parse_boxscore
from sportsmodel.ingest.mlb_boxscore import (
    fetch_boxscore,
    fetch_live_feed,
)


SOURCE_NAME = "mlb_stats"


def ingest_boxscore(
    *,
    game_id: int,
    game_pk: int,
) -> None:
    """
    Download, parse, and persist one MLB box score.
    """

    live_feed = fetch_live_feed(game_pk)

    boxscore = fetch_boxscore(game_pk)

    team_ids_by_mlb_id = _build_team_lookup(boxscore)

    player_ids_by_mlb_id = _build_player_lookup(boxscore)

    parsed_boxscore = parse_boxscore(
        game_id=game_id,
        game_pk=game_pk,
        live_feed=live_feed,
        boxscore=boxscore,
        team_ids_by_mlb_id=team_ids_by_mlb_id,
        player_ids_by_mlb_id=player_ids_by_mlb_id,
    )

    save_parsed_boxscore(parsed_boxscore)


def _build_team_lookup(
    boxscore: dict,
) -> dict[int, int]:
    """
    Build a mapping of MLB team IDs to canonical team IDs.
    """

    teams = boxscore["teams"]

    mlb_team_ids = [
        teams["home"]["team"]["id"],
        teams["away"]["team"]["id"],
    ]

    return get_team_ids_by_source(
        SOURCE_NAME,
        mlb_team_ids,
    )


def _build_player_lookup(
    boxscore: dict,
) -> dict[int, int]:
    """
    Build a mapping of MLB player IDs to canonical player IDs.
    """

    mlb_player_ids: list[int] = []

    for side in ("home", "away"):
        players = boxscore["teams"][side]["players"]

        for player_key in players:
            player = players[player_key]

            person = player.get("person")

            if person is None:
                continue

            player_id = person.get("id")

            if player_id is not None:
                mlb_player_ids.append(player_id)

    return get_player_ids_by_source(
        SOURCE_NAME,
        mlb_player_ids,
    )