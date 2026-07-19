import pytest

from sportsmodel.ingest.mlb_rosters import (
    extract_roster_player_ids,
    normalize_mlb_team,
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