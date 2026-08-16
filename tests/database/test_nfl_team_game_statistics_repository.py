import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sportsmodel.database.nfl_game_repository import (
    list_nfl_games_by_season_range,
)
from sportsmodel.database.nfl_team_game_statistics_repository import (
    GET_ALL_NFL_COMPLETED_HISTORY_QUERY,
    GET_NFL_COMPLETED_GAMES_BEFORE_QUERY,
    NflStatisticsGameAmbiguousError,
    NflStatisticsGameNotFoundError,
    PostgresNflTeamHistoryRepository,
    list_all_nfl_completed_history,
    resolve_statistics_game,
)
from sportsmodel.database.nfl_team_repository import resolve_nfl_team_by_source
from sportsmodel.nfl.models import (
    NflGame,
    NflGameStatus,
    NflSeasonType,
    NflTeamGameStatisticsSourceRecord,
)
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


def test_point_in_time_history_repository_passes_scope_and_maps_domain_row() -> None:
    cutoff = datetime(2025, 9, 14, 20, 20, tzinfo=timezone.utc)
    kickoff = datetime(2025, 9, 7, 20, 20, tzinfo=timezone.utc)
    row = (
        44, 2025, "regular", 1, "Week 1", kickoff, 10, 20,
        "final", 24, 17, False, False, 20,
        21, 31, 245, 2, 1, 3, 24, 112, 1, 0, 6, 55,
        10, 18, 29, 205, 1, 2, 2, 26, 130, 1, 0, 4, 35,
    )
    cursor = HistoryCursor([row])
    connection = HistoryConnection(cursor)
    repository = PostgresNflTeamHistoryRepository(
        connection_factory=lambda: connection
    )

    result = repository.get_completed_games_before(
        team_id=20, cutoff_time=cutoff, season=2025, limit=8
    )

    assert cursor.sql == GET_NFL_COMPLETED_GAMES_BEFORE_QUERY
    assert cursor.params == (20, cutoff, 2025, 2025, 8)
    assert connection.closed is True
    assert len(result) == 1
    assert result[0].game.game_id == 44
    assert result[0].game.scheduled_start_time == kickoff
    assert result[0].team_statistics.game_id == 44
    assert result[0].team_statistics.team_id == 20
    assert result[0].opponent_statistics.team_id == 10
    assert result[0].opponent_statistics.passing_yards == 205
    assert result[0].points_for == 17
    assert result[0].points_against == 24

    normalized = " ".join(cursor.sql.split())
    assert "nfl.scheduled_start_time < %s" in normalized
    assert "nfl.status = 'final'" in normalized
    assert "stats.team_id = game.home_team_id" in normalized
    assert "stats.team_id = game.away_team_id" in normalized


def test_list_nfl_games_by_season_range_maps_read_only_canonical_rows() -> None:
    kickoff = datetime(2024, 9, 6, 0, 20, tzinfo=timezone.utc)
    cursor = HistoryCursor([(
        44, 2024, "regular", 1, "Week 1", kickoff, 10, 20,
        "final", 27, 20, False, False,
    )])

    games = list_nfl_games_by_season_range(
        cursor, season_from=2018, season_to=2025,
    )

    assert cursor.params == (2018, 2025)
    assert games == (
        NflGame(
            game_id=44, season=2024, season_type=NflSeasonType.REGULAR,
            week=1, week_label="Week 1", scheduled_start_time=kickoff,
            home_team_id=10, away_team_id=20, status=NflGameStatus.FINAL,
            home_score=27, away_score=20, overtime=False,
            neutral_site=False,
        ),
    )
    normalized = " ".join(cursor.sql.split())
    assert "nfl.season BETWEEN %s AND %s" in normalized
    assert "ORDER BY nfl.scheduled_start_time, nfl.game_id" in normalized
    assert normalized.startswith("SELECT ")
    assert " INSERT " not in f" {normalized} "
    assert " UPDATE " not in f" {normalized} "
    assert " DELETE " not in f" {normalized} "


def test_list_all_completed_history_maps_both_team_perspectives_read_only() -> None:
    kickoff = datetime(2025, 9, 7, 20, 20, tzinfo=timezone.utc)
    cursor = HistoryCursor([
        _bulk_history_row(
            kickoff=kickoff, team_id=10, opponent_id=20,
            passing_yards=205, rushing_yards=130,
            opponent_passing_yards=245, opponent_rushing_yards=112,
        ),
        _bulk_history_row(
            kickoff=kickoff, team_id=20, opponent_id=10,
            passing_yards=245, rushing_yards=112,
            opponent_passing_yards=205, opponent_rushing_yards=130,
        ),
    ])

    history = list_all_nfl_completed_history(
        cursor, season_from=2018, season_to=2025,
    )

    assert cursor.sql == GET_ALL_NFL_COMPLETED_HISTORY_QUERY
    assert cursor.params == (2018, 2025)
    assert len(history) == 2
    home, away = history
    assert home.team_statistics.team_id == 10
    assert home.opponent_statistics.team_id == 20
    assert home.points_for == 24
    assert home.points_against == 17
    assert home.team_statistics.passing_yards == 205
    assert home.opponent_statistics.rushing_yards == 112
    assert away.team_statistics.team_id == 20
    assert away.opponent_statistics.team_id == 10
    assert away.points_for == 17
    assert away.points_against == 24
    assert away.team_statistics.passing_yards == 245
    assert away.opponent_statistics.rushing_yards == 130

    normalized = " ".join(cursor.sql.split())
    assert "nfl.status = 'final'" in normalized
    assert "stats.team_id = game.home_team_id" in normalized
    assert "stats.team_id = game.away_team_id" in normalized
    assert "WHEN stats.team_id = game.home_team_id THEN game.away_team_id" in normalized
    assert "ORDER BY stats.team_id, nfl.scheduled_start_time DESC, nfl.game_id DESC" in normalized
    assert normalized.startswith("SELECT ")
    assert " INSERT " not in f" {normalized} "
    assert " UPDATE " not in f" {normalized} "
    assert " DELETE " not in f" {normalized} "


class HistoryCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class HistoryConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


def _bulk_history_row(
    *, kickoff, team_id, opponent_id, passing_yards, rushing_yards,
    opponent_passing_yards, opponent_rushing_yards,
):
    return (
        44, 2025, "regular", 1, "Week 1", kickoff, 10, 20,
        "final", 24, 17, False, False, team_id,
        18, 29, passing_yards, 1, 2, 2, 26, rushing_yards, 1, 0, 4, 35,
        opponent_id, 21, 31, opponent_passing_yards, 2, 1, 3,
        24, opponent_rushing_yards, 1, 0, 6, 55,
    )
