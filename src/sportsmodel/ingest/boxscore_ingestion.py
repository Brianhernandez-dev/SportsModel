from typing import Any

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
from sportsmodel.ingest.mlb_players import sync_mlb_players


SOURCE_NAME = "mlb_stats"


def ingest_boxscore(
    *,
    game_id: int,
    game_pk: int,
) -> None:
    """
    Download, resolve, parse, and persist one MLB box score.
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
    boxscore: dict[str, Any],
) -> dict[int, int]:
    """
    Build a mapping of MLB team IDs to canonical team IDs.
    """

    teams = boxscore.get("teams")

    if not isinstance(teams, dict):
        raise ValueError(
            "MLB box score did not contain a teams object."
        )

    mlb_team_ids: list[int] = []

    for side in ("home", "away"):
        team_section = teams.get(side)

        if not isinstance(team_section, dict):
            raise ValueError(
                f"MLB box score did not contain the {side} team."
            )

        team = team_section.get("team")

        if not isinstance(team, dict):
            raise ValueError(
                f"MLB box score {side} team did not contain team details."
            )

        mlb_team_id = team.get("id")

        if not isinstance(mlb_team_id, int):
            raise ValueError(
                f"MLB box score {side} team did not contain a valid ID."
            )

        mlb_team_ids.append(mlb_team_id)

    team_ids_by_mlb_id = get_team_ids_by_source(
        SOURCE_NAME,
        mlb_team_ids,
    )

    missing_team_ids = sorted(
        set(mlb_team_ids) - set(team_ids_by_mlb_id)
    )

    if missing_team_ids:
        raise LookupError(
            "Missing canonical MLB team mappings for IDs: "
            + ", ".join(
                str(team_id)
                for team_id in missing_team_ids
            )
        )

    return team_ids_by_mlb_id


def _build_player_lookup(
    boxscore: dict[str, Any],
) -> dict[int, int]:
    """
    Resolve all MLB players in a box score to canonical player IDs.

    Missing players are synchronized through the centralized MLB player
    synchronization service before the lookup is attempted again.
    """

    mlb_player_ids = _extract_player_ids(boxscore)

    player_ids_by_mlb_id = get_player_ids_by_source(
        SOURCE_NAME,
        mlb_player_ids,
    )

    missing_player_ids = sorted(
        set(mlb_player_ids) - set(player_ids_by_mlb_id)
    )

    if missing_player_ids:
        sync_mlb_players(missing_player_ids)

        player_ids_by_mlb_id = get_player_ids_by_source(
            SOURCE_NAME,
            mlb_player_ids,
        )

    unresolved_player_ids = sorted(
        set(mlb_player_ids) - set(player_ids_by_mlb_id)
    )

    if unresolved_player_ids:
        raise LookupError(
            "Unable to resolve MLB player IDs after synchronization: "
            + ", ".join(
                str(player_id)
                for player_id in unresolved_player_ids
            )
        )

    return player_ids_by_mlb_id


def _extract_player_ids(
    boxscore: dict[str, Any],
) -> list[int]:
    """
    Extract unique MLB player IDs from both teams in a box score.
    """

    teams = boxscore.get("teams")

    if not isinstance(teams, dict):
        raise ValueError(
            "MLB box score did not contain a teams object."
        )

    mlb_player_ids: set[int] = set()

    for side in ("home", "away"):
        team_section = teams.get(side)

        if not isinstance(team_section, dict):
            raise ValueError(
                f"MLB box score did not contain the {side} team."
            )

        players = team_section.get("players")

        if not isinstance(players, dict):
            raise ValueError(
                f"MLB box score {side} team did not contain players."
            )

        for player in players.values():
            if not isinstance(player, dict):
                continue

            person = player.get("person")

            if not isinstance(person, dict):
                continue

            player_id = person.get("id")

            if isinstance(player_id, int):
                mlb_player_ids.add(player_id)

    return sorted(mlb_player_ids)