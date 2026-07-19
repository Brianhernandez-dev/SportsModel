from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import requests

from sportsmodel.database.player_repository import (
    get_baseball_player_by_source,
)
from sportsmodel.database.team_assignment_repository import (
    add_baseball_team_source,
    close_current_player_team_assignment,
    create_player_team_assignment,
    get_all_current_player_team_assignments,
    get_current_player_team_assignment,
    get_team_id_by_name,
    get_team_id_by_source,
    update_current_player_team_assignment,
)
from sportsmodel.ingest.mlb_players import (
    PlayerSyncSummary,
    sync_mlb_players,
)
from sportsmodel.models.baseball_player_team_assignment import (
    BaseballPlayerTeamAssignment,
)
from sportsmodel.models.baseball_team_source import BaseballTeamSource


SOURCE_NAME = "mlb_stats"

MLB_TEAMS_URL = "https://statsapi.mlb.com/api/v1/teams"
MLB_TEAM_ROSTER_URL = (
    "https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
)


@dataclass(frozen=True)
class MlbTeam:
    external_team_id: int
    team_name: str


@dataclass(frozen=True)
class NormalizedRosterEntry:
    external_player_id: str
    external_team_id: str

    roster_status_code: str | None
    roster_status_description: str | None

    jersey_number: str | None

    position_code: str | None
    position_name: str | None


@dataclass(frozen=True)
class RosterDiscoverySummary:
    teams_received: int
    teams_processed: int
    teams_skipped: int

    roster_entries_received: int
    unique_players_discovered: int

    team_mappings_created: int

    assignments_created: int
    assignments_updated: int
    assignments_transferred: int
    assignments_skipped: int
    assignments_closed: int

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


def _optional_string(value: Any) -> str | None:
    """
    Normalize an optional string value.
    """

    if not isinstance(value, str):
        return None

    normalized = value.strip()

    return normalized or None


def normalize_roster_entry(
    payload: dict[str, Any],
    *,
    external_team_id: int | str,
) -> NormalizedRosterEntry:
    """
    Normalize one MLB active-roster entry.
    """

    person = payload.get("person")

    if not isinstance(person, dict):
        raise ValueError("MLB roster entry is missing person.")

    external_player_id = person.get("id")

    if not isinstance(external_player_id, int):
        raise ValueError("MLB roster entry is missing player id.")

    status = payload.get("status")
    position = payload.get("position")

    roster_status_code = None
    roster_status_description = None

    if isinstance(status, dict):
        roster_status_code = _optional_string(
            status.get("code")
        )
        roster_status_description = _optional_string(
            status.get("description")
        )

    position_code = None
    position_name = None

    if isinstance(position, dict):
        position_code = _optional_string(
            position.get("code")
        )
        position_name = _optional_string(
            position.get("name")
        )

    return NormalizedRosterEntry(
        external_player_id=str(external_player_id),
        external_team_id=str(external_team_id),
        roster_status_code=roster_status_code,
        roster_status_description=roster_status_description,
        jersey_number=_optional_string(
            payload.get("jerseyNumber")
        ),
        position_code=position_code,
        position_name=position_name,
    )


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


def get_or_create_team_mapping(
    team: MlbTeam,
) -> tuple[int, bool]:
    """
    Resolve an MLB team to a canonical team and ensure its source mapping.

    Returns:
        Canonical team ID and whether a new source mapping was created.
    """

    external_team_id = str(team.external_team_id)

    existing_team_id = get_team_id_by_source(
        SOURCE_NAME,
        external_team_id,
    )

    if existing_team_id is not None:
        return existing_team_id, False

    canonical_team_id = get_team_id_by_name(
        team.team_name,
    )

    if canonical_team_id is None:
        raise LookupError(
            "No canonical team exists for MLB team: "
            f"{team.team_name}"
        )

    add_baseball_team_source(
        BaseballTeamSource(
            baseball_team_source_id=None,
            team_id=canonical_team_id,
            source_name=SOURCE_NAME,
            external_team_id=external_team_id,
        )
    )

    return canonical_team_id, True


def sync_roster_assignment(
    entry: NormalizedRosterEntry,
    *,
    team_id: int,
    synced_at: datetime,
    assignment_date: date,
) -> str:
    """
    Create or update the current team assignment for one player.

    Returns:
        One of: created, updated, transferred.
    """

    player = get_baseball_player_by_source(
        SOURCE_NAME,
        entry.external_player_id,
    )

    if player is None or player.baseball_player_id is None:
        raise LookupError(
            "No canonical player exists for MLB player ID: "
            f"{entry.external_player_id}"
        )

    current = get_current_player_team_assignment(
        player.baseball_player_id,
    )

    assignment = BaseballPlayerTeamAssignment(
        baseball_player_team_assignment_id=(
            current.baseball_player_team_assignment_id
            if current is not None
            else None
        ),
        baseball_player_id=player.baseball_player_id,
        team_id=team_id,
        roster_status_code=entry.roster_status_code,
        roster_status_description=(
            entry.roster_status_description
        ),
        jersey_number=entry.jersey_number,
        position_code=entry.position_code,
        position_name=entry.position_name,
        valid_from=(
            current.valid_from
            if current is not None
            else assignment_date
        ),
        valid_through=None,
        is_current=True,
        last_synced_at=synced_at,
        created_at=(
            current.created_at
            if current is not None
            else None
        ),
        updated_at=(
            current.updated_at
            if current is not None
            else None
        ),
    )

    if current is None:
        create_player_team_assignment(assignment)
        return "created"

    if current.team_id == team_id:
        update_current_player_team_assignment(
            assignment
        )
        return "updated"

    close_current_player_team_assignment(
        player.baseball_player_id,
        assignment_date,
    )

    create_player_team_assignment(
        BaseballPlayerTeamAssignment(
            baseball_player_team_assignment_id=None,
            baseball_player_id=player.baseball_player_id,
            team_id=team_id,
            roster_status_code=entry.roster_status_code,
            roster_status_description=(
                entry.roster_status_description
            ),
            jersey_number=entry.jersey_number,
            position_code=entry.position_code,
            position_name=entry.position_name,
            valid_from=assignment_date,
            valid_through=None,
            is_current=True,
            last_synced_at=synced_at,
        )
    )

    return "transferred"


def sync_active_mlb_rosters() -> RosterDiscoverySummary:
    """
    Discover MLB rosters, sync players, and persist current team assignments.

    Current assignments for players missing from the active-roster snapshot
    are closed only when the complete roster snapshot is considered safe.
    """

    team_payloads = fetch_active_mlb_teams()

    teams_processed = 0
    teams_skipped = 0
    roster_entries_received = 0
    team_mappings_created = 0

    player_ids: set[str] = set()

    roster_entries: list[
        tuple[int, NormalizedRosterEntry]
    ] = []

    for team_payload in team_payloads:
        try:
            team = normalize_mlb_team(team_payload)

            canonical_team_id, mapping_created = (
                get_or_create_team_mapping(team)
            )

            if mapping_created:
                team_mappings_created += 1

            roster = fetch_active_team_roster(
                team.external_team_id,
            )

            roster_entries_received += len(roster)
            player_ids.update(
                extract_roster_player_ids(roster)
            )

            for roster_payload in roster:
                try:
                    normalized_entry = normalize_roster_entry(
                        roster_payload,
                        external_team_id=team.external_team_id,
                    )

                    roster_entries.append(
                        (
                            canonical_team_id,
                            normalized_entry,
                        )
                    )

                except (
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    continue

            teams_processed += 1

        except (
            KeyError,
            LookupError,
            TypeError,
            ValueError,
            requests.RequestException,
        ):
            teams_skipped += 1

    player_sync = sync_mlb_players(
        sorted(player_ids),
    )

    assignments_created = 0
    assignments_updated = 0
    assignments_transferred = 0
    assignments_skipped = 0
    assignments_closed = 0

    synced_at = datetime.now(timezone.utc)
    assignment_date = synced_at.date()

    active_baseball_player_ids: set[int] = set()
    all_active_players_resolved = True

    for external_player_id in player_ids:
        player = get_baseball_player_by_source(
            SOURCE_NAME,
            external_player_id,
        )

        if player is None or player.baseball_player_id is None:
            all_active_players_resolved = False
            continue

        active_baseball_player_ids.add(
            player.baseball_player_id
        )

    for canonical_team_id, roster_entry in roster_entries:
        try:
            result = sync_roster_assignment(
                roster_entry,
                team_id=canonical_team_id,
                synced_at=synced_at,
                assignment_date=assignment_date,
            )

            if result == "created":
                assignments_created += 1
            elif result == "updated":
                assignments_updated += 1
            elif result == "transferred":
                assignments_transferred += 1

        except (
            KeyError,
            LookupError,
            TypeError,
            ValueError,
        ):
            assignments_skipped += 1

    all_teams_processed = (
        teams_processed == len(team_payloads)
        and teams_skipped == 0
    )

    all_roster_entries_normalized = (
        len(roster_entries) == roster_entries_received
    )

    lifecycle_cleanup_is_safe = (
        all_teams_processed
        and all_roster_entries_normalized
        and all_active_players_resolved
        and assignments_skipped == 0
    )

    if lifecycle_cleanup_is_safe:
        current_assignments = (
            get_all_current_player_team_assignments()
        )

        for current_assignment in current_assignments:
            baseball_player_id = (
                current_assignment.baseball_player_id
            )

            if baseball_player_id in active_baseball_player_ids:
                continue

            close_current_player_team_assignment(
                baseball_player_id,
                assignment_date,
            )
            assignments_closed += 1

    return RosterDiscoverySummary(
        teams_received=len(team_payloads),
        teams_processed=teams_processed,
        teams_skipped=teams_skipped,
        roster_entries_received=roster_entries_received,
        unique_players_discovered=len(player_ids),
        team_mappings_created=team_mappings_created,
        assignments_created=assignments_created,
        assignments_updated=assignments_updated,
        assignments_transferred=assignments_transferred,
        assignments_skipped=assignments_skipped,
        assignments_closed=assignments_closed,
        player_sync=player_sync,
    )