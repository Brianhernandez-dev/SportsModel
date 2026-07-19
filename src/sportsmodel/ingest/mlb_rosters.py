from dataclasses import dataclass
from typing import Any

import requests

from sportsmodel.ingest.mlb_players import (
    PlayerSyncSummary,
    sync_mlb_players,
)


MLB_TEAMS_URL = "https://statsapi.mlb.com/api/v1/teams"
MLB_TEAM_ROSTER_URL = (
    "https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
)


@dataclass(frozen=True)
class MlbTeam:
    external_team_id: int
    team_name: str


@dataclass(frozen=True)
class RosterDiscoverySummary:
    teams_received: int
    teams_processed: int
    teams_skipped: int
    roster_entries_received: int
    unique_players_discovered: int
    player_sync: PlayerSyncSummary


def fetch_active_mlb_teams() -> list[dict[str, Any]]:
    """
    Fetch active Major League Baseball teams.
    """

    response = requests.get(
        MLB_TEAMS_URL,
        params={
            "sportId": 1,
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()
    teams = data.get("teams", [])

    if not isinstance(teams, list):
        raise ValueError(
            "MLB teams response did not contain a teams list."
        )

    return teams


def normalize_mlb_team(
    payload: dict[str, Any],
) -> MlbTeam:
    """
    Normalize one MLB team payload.
    """

    external_team_id = payload.get("id")
    team_name = payload.get("name")

    if not isinstance(external_team_id, int):
        raise ValueError("MLB team payload is missing id.")

    if not isinstance(team_name, str) or not team_name.strip():
        raise ValueError("MLB team payload is missing name.")

    return MlbTeam(
        external_team_id=external_team_id,
        team_name=team_name.strip(),
    )


def fetch_active_team_roster(
    team_id: int,
) -> list[dict[str, Any]]:
    """
    Fetch the active roster for one MLB team.
    """

    response = requests.get(
        MLB_TEAM_ROSTER_URL.format(team_id=team_id),
        params={
            "rosterType": "active",
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()
    roster = data.get("roster", [])

    if not isinstance(roster, list):
        raise ValueError(
            "MLB roster response did not contain a roster list."
        )

    return roster


def extract_roster_player_ids(
    roster: list[dict[str, Any]],
) -> set[str]:
    """
    Extract unique MLB person IDs from roster entries.
    """

    player_ids: set[str] = set()

    for roster_entry in roster:
        person = roster_entry.get("person")

        if not isinstance(person, dict):
            continue

        player_id = person.get("id")

        if isinstance(player_id, int):
            player_ids.add(str(player_id))

    return player_ids


def sync_active_mlb_rosters() -> RosterDiscoverySummary:
    """
    Discover active MLB rosters and synchronize all unique players.
    """

    team_payloads = fetch_active_mlb_teams()

    teams_processed = 0
    teams_skipped = 0
    roster_entries_received = 0
    player_ids: set[str] = set()

    for team_payload in team_payloads:
        try:
            team = normalize_mlb_team(team_payload)
            roster = fetch_active_team_roster(
                team.external_team_id,
            )

            roster_entries_received += len(roster)
            player_ids.update(
                extract_roster_player_ids(roster)
            )
            teams_processed += 1

        except (
            KeyError,
            TypeError,
            ValueError,
            requests.RequestException,
        ):
            teams_skipped += 1

    player_sync = sync_mlb_players(
        sorted(player_ids),
    )

    return RosterDiscoverySummary(
        teams_received=len(team_payloads),
        teams_processed=teams_processed,
        teams_skipped=teams_skipped,
        roster_entries_received=roster_entries_received,
        unique_players_discovered=len(player_ids),
        player_sync=player_sync,
    )