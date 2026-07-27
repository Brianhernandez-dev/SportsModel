from datetime import date

import pytest

from sportsmodel.ingest.mlb_players import normalize_mlb_player


def test_normalize_active_mlb_player() -> None:
    payload = {
        "id": 123456,
        "fullName": "Example Pitcher",
        "active": True,
        "mlbDebutDate": "2020-07-24",
        "batSide": {
            "code": "L",
        },
        "pitchHand": {
            "code": "R",
        },
        "primaryPosition": {
            "name": "Pitcher",
        },
    }

    result = normalize_mlb_player(payload)

    assert result.external_player_id == "123456"
    assert result.full_name == "Example Pitcher"
    assert result.bats == "L"
    assert result.throws == "R"
    assert result.primary_position == "Pitcher"
    assert result.active_from == date(2020, 7, 24)
    assert result.active_through is None
    assert result.is_active is True


def test_normalize_inactive_mlb_player() -> None:
    payload = {
        "id": 654321,
        "fullName": "Former Player",
        "active": False,
        "lastPlayedDate": "2024-09-29",
        "batSide": {
            "code": "S",
        },
        "pitchHand": {
            "code": "L",
        },
        "primaryPosition": {
            "name": "Shortstop",
        },
    }

    result = normalize_mlb_player(payload)

    assert result.external_player_id == "654321"
    assert result.full_name == "Former Player"
    assert result.bats == "S"
    assert result.throws == "L"
    assert result.primary_position == "Shortstop"
    assert result.active_from is None
    assert result.active_through == date(2024, 9, 29)
    assert result.is_active is False


def test_normalize_player_handles_missing_optional_fields() -> None:
    payload = {
        "id": 111111,
        "fullName": "Minimal Player",
    }

    result = normalize_mlb_player(payload)

    assert result.external_player_id == "111111"
    assert result.full_name == "Minimal Player"
    assert result.bats is None
    assert result.throws is None
    assert result.primary_position is None
    assert result.active_from is None
    assert result.active_through is None
    assert result.is_active is True


def test_normalize_player_strips_name_and_position() -> None:
    payload = {
        "id": 333333,
        "fullName": "  Spaced Player  ",
        "primaryPosition": {
            "name": "  Catcher  ",
        },
    }

    result = normalize_mlb_player(payload)

    assert result.full_name == "Spaced Player"
    assert result.primary_position == "Catcher"


def test_normalize_player_rejects_missing_id() -> None:
    payload = {
        "fullName": "Missing Identifier",
    }

    with pytest.raises(ValueError, match="missing id"):
        normalize_mlb_player(payload)


def test_normalize_player_rejects_missing_name() -> None:
    payload = {
        "id": 123456,
    }

    with pytest.raises(ValueError, match="missing fullName"):
        normalize_mlb_player(payload)


def test_normalize_player_rejects_blank_name() -> None:
    payload = {
        "id": 123456,
        "fullName": "   ",
    }

    with pytest.raises(ValueError, match="missing fullName"):
        normalize_mlb_player(payload)


def test_normalize_player_ignores_invalid_handedness() -> None:
    payload = {
        "id": 222222,
        "fullName": "Unknown Handedness",
        "batSide": {
            "code": "X",
        },
        "pitchHand": {
            "code": "S",
        },
    }

    result = normalize_mlb_player(payload)

    assert result.bats is None
    assert result.throws is None