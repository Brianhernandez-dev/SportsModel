import json
from pathlib import Path

import pytest

from sportsmodel.database.nfl_team_game_statistics_repository import (
    NflStatisticsGameAmbiguousError,
    NflStatisticsGameNotFoundError,
    resolve_statistics_game,
)
from sportsmodel.database.nfl_team_repository import resolve_nfl_team_by_source
from sportsmodel.nfl.models import NflSeasonType, NflTeamGameStatisticsSourceRecord
from sportsmodel.nfl.nflverse_parser import (
    build_nflverse_team_identity_index,
    parse_nflverse_team_game_statistics_records,
    parse_nflverse_team_records,
)


RECORD = NflTeamGameStatisticsSourceRecord(
    source_name="nflverse", external_game_id="2025_01_DAL_PHI",
    season=2025, season_type=NflSeasonType.REGULAR, week=1,
    team_external_id="1200", opponent_external_id="3700",
    completions=21, pass_attempts=34, passing_yards=188,
    passing_touchdowns=0, passing_interceptions=0, sacks_suffered=0,
    carries=22, rushing_yards=119, rushing_touchdowns=2,
    fumbles_lost=1, penalties=4, penalty_yards=42,
)


class Cursor:
    def __init__(self, matches, provider_match=None):
        self.matches = matches
        self.provider_match = provider_match
        self.calls = 0

    def execute(self, sql, params):
        self.calls += 1
        self.params = params

    def fetchall(self):
        return self.matches

    def fetchone(self):
        return self.provider_match


def test_resolution_uses_season_week_and_canonical_participants() -> None:
    cursor = Cursor([(44,)], provider_match=(44,))
    assert resolve_statistics_game(
        cursor, record=RECORD, team_id=10, opponent_team_id=20) == 44
    assert cursor.params == ("nflverse", "2025_01_DAL_PHI")


def test_missing_and_ambiguous_game_resolution_are_explicit() -> None:
    with pytest.raises(NflStatisticsGameNotFoundError):
        resolve_statistics_game(Cursor([]), record=RECORD,
                                team_id=10, opponent_team_id=20)
    with pytest.raises(NflStatisticsGameAmbiguousError):
        resolve_statistics_game(Cursor([(44,), (45,)]), record=RECORD,
                                team_id=10, opponent_team_id=20)


def test_provider_game_mapping_must_match_resolved_game() -> None:
    with pytest.raises(ValueError, match="conflicts"):
        resolve_statistics_game(Cursor([(44,)], provider_match=(99,)),
                                record=RECORD, team_id=10, opponent_team_id=20)
    with pytest.raises(NflStatisticsGameNotFoundError, match="identity"):
        resolve_statistics_game(Cursor([(44,)], provider_match=None),
                                record=RECORD, team_id=10, opponent_team_id=20)


def test_historical_alias_external_identity_is_provider_owned_not_canonical() -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "nflverse" / "phase_1_source_rows.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    identities = build_nflverse_team_identity_index(
        parse_nflverse_team_records(fixture["teams"]))
    raw = dict(fixture["team_stats"][0])
    oak = parse_nflverse_team_game_statistics_records(
        (dict(raw, team="OAK"),), team_identities=identities)[0]
    lv = parse_nflverse_team_game_statistics_records(
        (dict(raw, team="LV"),), team_identities=identities)[0]
    assert oak.team_external_id == lv.team_external_id == "2520"

    canonical_row = (
        101, "nfl_franchise_38f7d31e-ff94-48ec-905a-0c80ca64c6db", "LV", True)
    oak_team = resolve_nfl_team_by_source(
        Cursor([], provider_match=canonical_row), source_name="nflverse",
        external_team_id=oak.team_external_id)
    lv_team = resolve_nfl_team_by_source(
        Cursor([], provider_match=canonical_row), source_name="nflverse",
        external_team_id=lv.team_external_id)
    assert oak_team == lv_team
    assert oak_team.team_id == 101
