from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import requests

from sportsmodel.database.player_repository import (
    add_baseball_player_source,
    create_baseball_player,
    get_baseball_player_by_source,
    update_baseball_player,
)
from sportsmodel.models.baseball_player import BaseballPlayer
from sportsmodel.models.baseball_player_source import BaseballPlayerSource


SOURCE_NAME = "mlb_stats"
MLB_PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people"


@dataclass(frozen=True)
class NormalizedMlbPlayer:
    external_player_id: str
    full_name: str
    bats: str | None
    throws: str | None
    primary_position: str | None
    active_from: date | None
    active_through: date | None
    is_active: bool


@dataclass(frozen=True)
class PlayerSyncSummary:
    players_received: int
    players_created: int
    players_updated: int
    players_skipped: int


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None

    return date.fromisoformat(value)


def _normalize_side_code(
    value: Any,
    *,
    allow_switch: bool,
) -> str | None:
    if not isinstance(value, dict):
        return None

    code = value.get("code")

    valid_codes = {"L", "R"}

    if allow_switch:
        valid_codes.add("S")

    if code not in valid_codes:
        return None

    return code


def normalize_mlb_player(
    payload: dict[str, Any],
) -> NormalizedMlbPlayer:
    """
    Normalize one MLB Stats API person payload.
    """

    external_player_id = payload.get("id")
    full_name = payload.get("fullName")

    if external_player_id is None:
        raise ValueError("MLB player payload is missing id.")

    if not isinstance(full_name, str) or not full_name.strip():
        raise ValueError("MLB player payload is missing fullName.")

    primary_position = payload.get("primaryPosition")
    position_name = None

    if isinstance(primary_position, dict):
        raw_position_name = primary_position.get("name")

        if isinstance(raw_position_name, str):
            position_name = raw_position_name.strip() or None

    active_from = _parse_date(payload.get("mlbDebutDate"))

    active_value = payload.get("active")
    is_active = active_value if isinstance(active_value, bool) else True

    active_through = None

    if not is_active:
        active_through = _parse_date(payload.get("lastPlayedDate"))

    return NormalizedMlbPlayer(
        external_player_id=str(external_player_id),
        full_name=full_name.strip(),
        bats=_normalize_side_code(
            payload.get("batSide"),
            allow_switch=True,
        ),
        throws=_normalize_side_code(
            payload.get("pitchHand"),
            allow_switch=False,
        ),
        primary_position=position_name,
        active_from=active_from,
        active_through=active_through,
        is_active=is_active,
    )


def fetch_mlb_players(
    player_ids: list[int | str],
) -> list[dict[str, Any]]:
    """
    Fetch MLB player records by MLB person ID.
    """

    if not player_ids:
        return []

    response = requests.get(
        MLB_PEOPLE_URL,
        params={
            "personIds": ",".join(str(player_id) for player_id in player_ids),
            "hydrate": "currentTeam",
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()
    people = data.get("people", [])

    if not isinstance(people, list):
        raise ValueError("MLB people response did not contain a people list.")

    return people


def sync_normalized_player(
    player: NormalizedMlbPlayer,
    *,
    synced_at: datetime | None = None,
) -> tuple[BaseballPlayer, bool]:
    """
    Create or update one normalized MLB player.

    Returns:
        A tuple containing the saved player and whether it was newly created.
    """

    if synced_at is None:
        synced_at = datetime.now(timezone.utc)

    existing = get_baseball_player_by_source(
        SOURCE_NAME,
        player.external_player_id,
    )

    if existing is None:
        created = create_baseball_player(
            BaseballPlayer(
                baseball_player_id=None,
                full_name=player.full_name,
                bats=player.bats,
                throws=player.throws,
                primary_position=player.primary_position,
                active_from=player.active_from,
                active_through=player.active_through,
                is_active=player.is_active,
                last_synced_at=synced_at,
            )
        )

        if created.baseball_player_id is None:
            raise RuntimeError(
                "Created baseball player did not receive an ID."
            )

        add_baseball_player_source(
            BaseballPlayerSource(
                baseball_player_source_id=None,
                baseball_player_id=created.baseball_player_id,
                source_name=SOURCE_NAME,
                external_player_id=player.external_player_id,
            )
        )

        return created, True

    updated = update_baseball_player(
        BaseballPlayer(
            baseball_player_id=existing.baseball_player_id,
            full_name=player.full_name,
            bats=player.bats,
            throws=player.throws,
            primary_position=player.primary_position,
            active_from=player.active_from,
            active_through=player.active_through,
            is_active=player.is_active,
            last_synced_at=synced_at,
            created_at=existing.created_at,
            updated_at=existing.updated_at,
        )
    )

    return updated, False


def sync_mlb_players(
    player_ids: list[int | str],
) -> PlayerSyncSummary:
    """
    Fetch, normalize, and synchronize MLB players.
    """

    payloads = fetch_mlb_players(player_ids)

    created_count = 0
    updated_count = 0
    skipped_count = 0

    synced_at = datetime.now(timezone.utc)

    for payload in payloads:
        try:
            normalized = normalize_mlb_player(payload)
            _, was_created = sync_normalized_player(
                normalized,
                synced_at=synced_at,
            )

            if was_created:
                created_count += 1
            else:
                updated_count += 1

        except (KeyError, TypeError, ValueError):
            skipped_count += 1

    return PlayerSyncSummary(
        players_received=len(payloads),
        players_created=created_count,
        players_updated=updated_count,
        players_skipped=skipped_count,
    )