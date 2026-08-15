from copy import deepcopy

import pytest

from sportsmodel.nfl.nflverse_parser import (
    parse_nflverse_team_game_statistics_records,
)
from sportsmodel.nfl.team_statistics_persistence import canonical_json


IDENTITIES = {"DAL": "1200", "PHI": "3700"}
ROW = {
    "season": "2025", "week": "1", "season_type": "REG",
    "game_id": "2025_01_DAL_PHI", "team": "DAL", "opponent_team": "PHI",
    "completions": "0", "attempts": "0", "passing_yards": "0",
    "passing_tds": "0", "passing_interceptions": "0", "sacks_suffered": "0",
    "carries": "0", "rushing_yards": "0", "rushing_tds": "0",
    "fumbles_lost_total": "0", "penalties": None, "penalty_yards": "",
}


def test_zero_values_and_nullable_penalties_are_preserved() -> None:
    record = parse_nflverse_team_game_statistics_records(
        (ROW,), team_identities=IDENTITIES)[0]
    assert record.completions == record.pass_attempts == 0
    assert record.fumbles_lost == 0
    assert record.penalties is None
    assert record.penalty_yards is None


@pytest.mark.parametrize("field,value", [
    ("attempts", "1.5"), ("carries", -1), ("completions", True),
])
def test_malformed_or_impossible_integral_statistics_are_rejected(field, value) -> None:
    row = deepcopy(ROW)
    row[field] = value
    with pytest.raises(ValueError):
        parse_nflverse_team_game_statistics_records((row,), team_identities=IDENTITIES)


def test_completions_cannot_exceed_attempts_and_opponent_is_required() -> None:
    row = deepcopy(ROW)
    row["completions"] = "2"
    row["attempts"] = "1"
    with pytest.raises(ValueError, match="completions"):
        parse_nflverse_team_game_statistics_records((row,), team_identities=IDENTITIES)
    row = deepcopy(ROW)
    row["opponent_team"] = "DAL"
    with pytest.raises(ValueError, match="team and opponent"):
        parse_nflverse_team_game_statistics_records((row,), team_identities=IDENTITIES)


def test_raw_payload_hash_input_is_canonical_and_order_independent() -> None:
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
