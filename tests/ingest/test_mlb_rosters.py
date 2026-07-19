import pytest

from sportsmodel.ingest.mlb_rosters import (
    extract_roster_player_ids,
    normalize_mlb_team,
    normalize_roster_entry,
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