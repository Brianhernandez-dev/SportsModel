from copy import deepcopy
from datetime import date

import pytest

from sportsmodel.ingest.mlb_game_policy import (
    championship_game_type, confirmed_championship_game, extract_schedule_games,
)


def postseason_game():
    return {
        "gameType": "D", "ifNecessary": "N", "gamePk": 849833,
        "gameDate": "2026-10-07T20:00:00Z",
        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled",
                   "startTimeTBD": False},
        "teams": {
            "home": {"team": {"id": 145, "name": "Chicago White Sox"}},
            "away": {"team": {"id": 114, "name": "Cleveland Guardians"}},
        },
    }


def test_schedule_envelope_accepts_a_valid_empty_date_list():
    assert extract_schedule_games(
        {"dates": []},
        expected_date=date(2026, 10, 7),
    ) == ()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "not a mapping"),
        ({}, "dates must be a list"),
        ({"dates": {}}, "dates must be a list"),
        ({"dates": [None]}, "date block was not a mapping"),
        ({"dates": [{"games": []}]}, "valid ISO date"),
        ({"dates": [{"date": "not-a-date", "games": []}]}, "valid ISO date"),
        ({"dates": [{"date": "2026-10-08", "games": []}]}, "requested date"),
        ({"dates": [{"date": "2026-10-07"}]}, "games must be a list"),
        ({"dates": [{"date": "2026-10-07", "games": {}}]}, "games must be a list"),
        ({"dates": [{"date": "2026-10-07", "games": [None]}]}, "game entry"),
    ],
    ids=[
        "payload-not-mapping",
        "dates-missing",
        "dates-not-list",
        "date-block-not-mapping",
        "date-missing",
        "date-malformed",
        "date-wrong",
        "games-missing",
        "games-not-list",
        "game-not-mapping",
    ],
)
def test_schedule_envelope_fails_closed(payload, message):
    with pytest.raises(ValueError, match=message):
        extract_schedule_games(
            payload,
            expected_date=date(2026, 10, 7),
        )


@pytest.mark.parametrize("game_type", ["R", "F", "D", "L", "W"])
def test_championship_types_are_confirmed(game_type):
    game = postseason_game()
    game["gameType"] = game_type
    assert championship_game_type(game)
    assert confirmed_championship_game(game)


@pytest.mark.parametrize("game_type", ["S", "E", "A", "I"])
def test_known_non_model_types_are_deliberate_exclusions(game_type):
    assert not championship_game_type({"gameType": game_type})
    assert not confirmed_championship_game({"gameType": game_type})


@pytest.mark.parametrize("game_type", ["P", "C", "?", "", "r", " D ", None, [], {}, 1, True])
def test_unknown_types_are_errors_not_exclusions(game_type):
    with pytest.raises(ValueError, match="gameType"):
        championship_game_type({"gameType": game_type})


def test_fixed_time_real_clubs_do_not_prove_conditional_game_exists():
    game = postseason_game()
    game["ifNecessary"] = "Y"
    assert not confirmed_championship_game(game)
    game["status"]["abstractGameState"] = "Live"
    assert confirmed_championship_game(game)


@pytest.mark.parametrize("placeholder_id,name", [
    (5521, "AL Lower Seed"), (5513, "AL Higher Seed"),
    (2711, "Lower Seed League Champion"), (2710, "Higher Seed League Champion"),
    (145, "TBD"),
])
def test_positive_placeholder_identity_cannot_become_canonical_club(placeholder_id, name):
    game = postseason_game()
    game["teams"]["home"]["team"] = {"id": placeholder_id, "name": name}
    with pytest.raises(ValueError, match="participant"):
        confirmed_championship_game(game)


def test_tbd_time_is_deferred_not_invented():
    game = postseason_game()
    game["status"]["startTimeTBD"] = True
    assert not confirmed_championship_game(game)


@pytest.mark.parametrize("flag", [None, "", "?", True, [], {}])
def test_missing_or_unknown_confirmation_is_actionable(flag):
    game = postseason_game()
    game["ifNecessary"] = flag
    with pytest.raises(ValueError, match="ifNecessary"):
        confirmed_championship_game(game)


def test_policy_does_not_normalize_or_mutate_provider_evidence():
    game = postseason_game()
    original = deepcopy(game)
    assert confirmed_championship_game(game)
    assert game == original


@pytest.mark.parametrize("name", ["To Be Determined", "AL Participant", "New York Yankees"])
def test_real_club_id_cannot_create_unrecognized_or_conflicting_team_name(name):
    game = postseason_game()
    game["teams"]["home"]["team"]["name"] = name
    with pytest.raises(ValueError, match="participant"):
        confirmed_championship_game(game)


@pytest.mark.parametrize("club_id,name", [(114, "Cleveland Indians"), (133, "Oakland Athletics")])
def test_verified_historical_alias_keeps_the_same_club_identity(club_id, name):
    game = postseason_game()
    game["teams"]["home"]["team"] = {"id": club_id, "name": name}
    game["teams"]["away"]["team"] = {"id": 141, "name": "Toronto Blue Jays"}
    assert confirmed_championship_game(game)


@pytest.mark.parametrize("field,value", [
    ("gamePk", None), ("gamePk", True), ("gamePk", -1),
    ("gameDate", None), ("gameDate", "2026-10-07T20:00:00"),
    ("teams", []), ("teams", None),
])
def test_confirmed_postseason_malformed_identity_is_an_error(field, value):
    game = postseason_game()
    game[field] = value
    with pytest.raises(ValueError):
        confirmed_championship_game(game)
