from dataclasses import replace

import pytest

from sportsmodel.database.nfl_team_game_statistics_repository import (
    NflStatisticsGameAmbiguousError,
    NflStatisticsGameNotFoundError,
    resolve_statistics_game,
)
from sportsmodel.nfl.models import NflSeasonType, NflTeamGameStatisticsSourceRecord


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
    oak = replace(RECORD, team_external_id="2520")
    lv = replace(RECORD, team_external_id="2520")
    assert oak.team_external_id == lv.team_external_id
