from types import SimpleNamespace
from typing import Any

import pytest
import requests

import sportsmodel.ingest.mlb_rosters as mlb_rosters
from sportsmodel.ingest.mlb_players import PlayerSyncSummary
from sportsmodel.ingest.mlb_rosters import (
    extract_roster_player_ids,
    normalize_mlb_team,
    normalize_roster_entry,
)


def _team_payload() -> dict[str, Any]:
    return {
        "id": 147,
        "name": "New York Yankees",
    }


def _roster_payload(
    *,
    player_id: int = 645305,
) -> dict[str, Any]:
    return {
        "person": {
            "id": player_id,
            "fullName": "Test Player",
        },
        "jerseyNumber": "39",
        "position": {
            "code": "2",
            "name": "Catcher",
        },
        "status": {
            "code": "A",
            "description": "Active",
        },
    }


def _player_sync_summary(
    *,
    players_received: int = 1,
) -> PlayerSyncSummary:
    return PlayerSyncSummary(
        players_received=players_received,
        players_created=0,
        players_updated=players_received,
        players_skipped=0,
    )


def test_normalize_mlb_team() -> None:
    payload = {
        "id": 147,
        "name": "New York Yankees",
    }

    result = normalize_mlb_team(payload)

    assert result.external_team_id == 147
    assert result.team_name == "New York Yankees"


def test_normalize_mlb_team_strips_name() -> None:
    payload = {
        "id": 119,
        "name": "  Los Angeles Dodgers  ",
    }

    result = normalize_mlb_team(payload)

    assert result.team_name == "Los Angeles Dodgers"


def test_normalize_mlb_team_rejects_missing_id() -> None:
    payload = {
        "name": "Missing ID",
    }

    with pytest.raises(ValueError, match="missing id"):
        normalize_mlb_team(payload)


def test_normalize_mlb_team_rejects_missing_name() -> None:
    payload = {
        "id": 147,
    }

    with pytest.raises(ValueError, match="missing name"):
        normalize_mlb_team(payload)


def test_normalize_roster_entry() -> None:
    payload = {
        "person": {
            "id": 645305,
            "fullName": "Ali Sánchez",
        },
        "jerseyNumber": "39",
        "position": {
            "code": "2",
            "name": "Catcher",
        },
        "status": {
            "code": "A",
            "description": "Active",
        },
        "parentTeamId": 147,
    }

    result = normalize_roster_entry(
        payload,
        external_team_id=147,
    )

    assert result.external_player_id == "645305"
    assert result.external_team_id == "147"
    assert result.roster_status_code == "A"
    assert result.roster_status_description == "Active"
    assert result.jersey_number == "39"
    assert result.position_code == "2"
    assert result.position_name == "Catcher"


def test_normalize_roster_entry_handles_optional_fields() -> None:
    payload = {
        "person": {
            "id": 123456,
        },
    }

    result = normalize_roster_entry(
        payload,
        external_team_id=147,
    )

    assert result.external_player_id == "123456"
    assert result.external_team_id == "147"
    assert result.roster_status_code is None
    assert result.roster_status_description is None
    assert result.jersey_number is None
    assert result.position_code is None
    assert result.position_name is None


def test_normalize_roster_entry_strips_values() -> None:
    payload = {
        "person": {
            "id": 123456,
        },
        "jerseyNumber": "  39  ",
        "position": {
            "code": "  2  ",
            "name": "  Catcher  ",
        },
        "status": {
            "code": "  A  ",
            "description": "  Active  ",
        },
    }

    result = normalize_roster_entry(
        payload,
        external_team_id=147,
    )

    assert result.jersey_number == "39"
    assert result.position_code == "2"
    assert result.position_name == "Catcher"
    assert result.roster_status_code == "A"
    assert result.roster_status_description == "Active"


def test_normalize_roster_entry_rejects_missing_person() -> None:
    with pytest.raises(ValueError, match="missing person"):
        normalize_roster_entry(
            {},
            external_team_id=147,
        )


def test_normalize_roster_entry_rejects_missing_player_id() -> None:
    payload = {
        "person": {},
    }

    with pytest.raises(ValueError, match="missing player id"):
        normalize_roster_entry(
            payload,
            external_team_id=147,
        )


def test_extract_roster_player_ids() -> None:
    roster = [
        {
            "person": {
                "id": 111111,
                "fullName": "Player One",
            }
        },
        {
            "person": {
                "id": 222222,
                "fullName": "Player Two",
            }
        },
        {
            "person": {
                "id": 111111,
                "fullName": "Player One",
            }
        },
    ]

    result = extract_roster_player_ids(roster)

    assert result == {
        "111111",
        "222222",
    }


def test_extract_roster_player_ids_skips_invalid_entries() -> None:
    roster = [
        {},
        {
            "person": None,
        },
        {
            "person": {},
        },
        {
            "person": {
                "id": "not-an-integer",
            }
        },
        {
            "person": {
                "id": 333333,
            }
        },
    ]

    result = extract_roster_player_ids(roster)

    assert result == {
        "333333",
    }


def test_sync_active_mlb_rosters_closes_missing_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_assignments: list[tuple[int, Any]] = []

    monkeypatch.setattr(
        mlb_rosters,
        "fetch_active_mlb_teams",
        lambda: [_team_payload()],
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_or_create_team_mapping",
        lambda team: (10, False),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "fetch_active_team_roster",
        lambda team_id: [_roster_payload(player_id=645305)],
    )
    monkeypatch.setattr(
        mlb_rosters,
        "sync_mlb_players",
        lambda player_ids: _player_sync_summary(),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_baseball_player_by_source",
        lambda source_name, external_player_id: SimpleNamespace(
            baseball_player_id=101,
        ),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "sync_roster_assignment",
        lambda entry, **kwargs: "updated",
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_all_current_player_team_assignments",
        lambda: [
            SimpleNamespace(baseball_player_id=101),
            SimpleNamespace(baseball_player_id=202),
        ],
    )
    monkeypatch.setattr(
        mlb_rosters,
        "close_current_player_team_assignment",
        lambda player_id, valid_through: closed_assignments.append(
            (
                player_id,
                valid_through,
            )
        ),
    )

    summary = mlb_rosters.sync_active_mlb_rosters()

    assert summary.assignments_closed == 1
    assert len(closed_assignments) == 1
    assert closed_assignments[0][0] == 202


def test_sync_active_mlb_rosters_keeps_active_assignment_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_assignments: list[tuple[int, Any]] = []

    monkeypatch.setattr(
        mlb_rosters,
        "fetch_active_mlb_teams",
        lambda: [_team_payload()],
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_or_create_team_mapping",
        lambda team: (10, False),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "fetch_active_team_roster",
        lambda team_id: [_roster_payload(player_id=645305)],
    )
    monkeypatch.setattr(
        mlb_rosters,
        "sync_mlb_players",
        lambda player_ids: _player_sync_summary(),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_baseball_player_by_source",
        lambda source_name, external_player_id: SimpleNamespace(
            baseball_player_id=101,
        ),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "sync_roster_assignment",
        lambda entry, **kwargs: "updated",
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_all_current_player_team_assignments",
        lambda: [
            SimpleNamespace(baseball_player_id=101),
        ],
    )
    monkeypatch.setattr(
        mlb_rosters,
        "close_current_player_team_assignment",
        lambda player_id, valid_through: closed_assignments.append(
            (
                player_id,
                valid_through,
            )
        ),
    )

    summary = mlb_rosters.sync_active_mlb_rosters()

    assert summary.assignments_closed == 0
    assert closed_assignments == []


def test_sync_active_mlb_rosters_skips_cleanup_when_team_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_requested = False

    def fail_roster_fetch(team_id: int) -> list[dict[str, Any]]:
        raise requests.RequestException(
            "Temporary MLB roster API failure."
        )

    def get_current_assignments() -> list[Any]:
        nonlocal cleanup_requested
        cleanup_requested = True
        return []

    monkeypatch.setattr(
        mlb_rosters,
        "fetch_active_mlb_teams",
        lambda: [_team_payload()],
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_or_create_team_mapping",
        lambda team: (10, False),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "fetch_active_team_roster",
        fail_roster_fetch,
    )
    monkeypatch.setattr(
        mlb_rosters,
        "sync_mlb_players",
        lambda player_ids: _player_sync_summary(
            players_received=0,
        ),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_all_current_player_team_assignments",
        get_current_assignments,
    )

    summary = mlb_rosters.sync_active_mlb_rosters()

    assert summary.teams_processed == 0
    assert summary.teams_skipped == 1
    assert summary.assignments_closed == 0
    assert cleanup_requested is False


def test_sync_active_mlb_rosters_skips_cleanup_when_assignment_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_requested = False

    def fail_assignment_sync(
        entry: Any,
        **kwargs: Any,
    ) -> str:
        raise ValueError("Assignment synchronization failed.")

    def get_current_assignments() -> list[Any]:
        nonlocal cleanup_requested
        cleanup_requested = True
        return []

    monkeypatch.setattr(
        mlb_rosters,
        "fetch_active_mlb_teams",
        lambda: [_team_payload()],
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_or_create_team_mapping",
        lambda team: (10, False),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "fetch_active_team_roster",
        lambda team_id: [_roster_payload(player_id=645305)],
    )
    monkeypatch.setattr(
        mlb_rosters,
        "sync_mlb_players",
        lambda player_ids: _player_sync_summary(),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_baseball_player_by_source",
        lambda source_name, external_player_id: SimpleNamespace(
            baseball_player_id=101,
        ),
    )
    monkeypatch.setattr(
        mlb_rosters,
        "sync_roster_assignment",
        fail_assignment_sync,
    )
    monkeypatch.setattr(
        mlb_rosters,
        "get_all_current_player_team_assignments",
        get_current_assignments,
    )

    summary = mlb_rosters.sync_active_mlb_rosters()

    assert summary.assignments_skipped == 1
    assert summary.assignments_closed == 0
    assert cleanup_requested is False