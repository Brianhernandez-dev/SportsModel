from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.database.nfl_team_game_statistics_repository import (
    GET_NFL_COMPLETED_GAMES_BEFORE_QUERY,
)
from sportsmodel.nfl.features import (
    HistoricalNflTeamGame,
    NFLFeatureDataProvider,
    NFLGameFeatureVectorBuilder,
)
from sportsmodel.nfl.models import (
    NflGame,
    NflGameStatus,
    NflSeasonType,
    NflTeamGameStatistics,
)
from sportsmodel.nfl.moneyline_dataset import NFLMoneylineTrainingDatasetBuilder


KICKOFF = datetime(2025, 9, 7, 20, 20, tzinfo=timezone.utc)


class InMemoryHistoryRepository:
    def __init__(self, games):
        self.games = tuple(games)

    def get_completed_games_before(self, *, team_id, cutoff_time, season=None, limit=None):
        eligible = [item for item in self.games
                    if item.team_statistics.team_id == team_id
                    and item.game.status is NflGameStatus.FINAL
                    and item.game.scheduled_start_time < cutoff_time
                    and (season is None or item.game.season == season)]
        eligible.sort(key=lambda item: (item.game.scheduled_start_time, item.game.game_id), reverse=True)
        return tuple(eligible[:limit] if limit is not None else eligible)


def test_point_in_time_history_uses_strict_kickoff_not_week_or_insertion_order() -> None:
    target = _game(50, KICKOFF, week=1, home=1, away=2)
    earlier = _history(99, KICKOFF - timedelta(hours=3), week=1, team=1, opponent=3)
    much_earlier_high_id = _history(500, KICKOFF - timedelta(days=7), week=1, team=1, opponent=4)
    self_game = _history(50, KICKOFF, week=1, team=1, opponent=2)
    later_same_week = _history(1, KICKOFF + timedelta(hours=2), week=1, team=1, opponent=5)
    later_lower_week = _history(2, KICKOFF + timedelta(days=1), week=0, team=1, opponent=6)
    repository = InMemoryHistoryRepository(
        [later_same_week, self_game, much_earlier_high_id, later_lower_week, earlier]
    )

    history = NFLFeatureDataProvider(target, repository=repository).get_team_history(
        team_id=1, season=2025
    )

    assert [item.game.game_id for item in history] == [99, 500]


def test_provider_defensively_rejects_repository_cutoff_violation() -> None:
    target = _game(50, KICKOFF, home=1, away=2)

    class LeakyRepository:
        def get_completed_games_before(self, **kwargs):
            return (_history(51, KICKOFF, team=1, opponent=2),)

    with pytest.raises(ValueError, match="at or after"):
        NFLFeatureDataProvider(target, repository=LeakyRepository()).get_team_history(team_id=1)


def test_game_vector_is_inspectable_and_counts_prior_games_per_team() -> None:
    target = _game(50, KICKOFF, home=1, away=2)
    repository = InMemoryHistoryRepository([
        _history(10, KICKOFF - timedelta(days=14), team=1, opponent=3, home_score=21, away_score=10),
        _history(11, KICKOFF - timedelta(days=7), team=1, opponent=4, home_score=14, away_score=17),
        _history(12, KICKOFF - timedelta(days=7), team=2, opponent=5, home_score=24, away_score=20),
    ])
    provider = NFLFeatureDataProvider(target, repository=repository)

    vector = NFLGameFeatureVectorBuilder().build(target, provider=provider)

    assert (vector.target_game_id, vector.target_kickoff, vector.feature_cutoff) == (50, KICKOFF, KICKOFF)
    assert (vector.home_team_id, vector.away_team_id) == (1, 2)
    assert vector.home.prior_games_used == 2
    assert vector.away.prior_games_used == 1
    assert vector.home.win_percentage == .5


def test_away_team_points_use_away_perspective() -> None:
    historical = _history(
        10, KICKOFF - timedelta(days=7), team=1, opponent=2,
        team_is_home=False, home_score=27, away_score=20,
    )

    assert historical.points_for == 20
    assert historical.points_against == 27


def test_historical_game_rejects_mismatched_game_or_nonparticipant_team() -> None:
    game = _game(10, KICKOFF - timedelta(days=7), home=1, away=2)
    with pytest.raises(ValueError, match="match the canonical game"):
        HistoricalNflTeamGame(game, _statistics(game_id=11, team_id=1))
    with pytest.raises(ValueError, match="canonical game participant"):
        HistoricalNflTeamGame(game, _statistics(game_id=10, team_id=3))


def test_historical_tie_contributes_half_to_win_percentage() -> None:
    target = _game(50, KICKOFF, home=1, away=2)
    repository = InMemoryHistoryRepository([
        _history(10, KICKOFF - timedelta(days=14), team=1, opponent=3,
                 home_score=21, away_score=10),
        _history(11, KICKOFF - timedelta(days=7), team=1, opponent=4,
                 home_score=17, away_score=17),
    ])

    vector = NFLGameFeatureVectorBuilder().build(
        target, provider=NFLFeatureDataProvider(target, repository=repository)
    )

    assert vector.home.win_percentage == .75


def test_zero_history_uses_none_for_rates_and_averages() -> None:
    target = _game(50, KICKOFF, home=1, away=2)
    vector = NFLGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(
            target, repository=InMemoryHistoryRepository([])
        ),
    )

    assert vector.home.prior_games_used == 0
    assert vector.home.win_percentage is None
    assert vector.home.average_points_for is None
    assert vector.home.average_points_against is None


def test_training_dataset_excludes_ties_and_labels_home_win_explicitly() -> None:
    winner = _game(50, KICKOFF, home=1, away=2, home_score=24, away_score=17)
    tie = _game(51, KICKOFF + timedelta(days=1), home=3, away=4, home_score=20, away_score=20)
    repository = InMemoryHistoryRepository([])
    builder = NFLMoneylineTrainingDatasetBuilder(
        provider_factory=lambda game: NFLFeatureDataProvider(game, repository=repository)
    )

    result = builder.build([winner, tie])

    assert result.games_received == 2
    assert result.ties_skipped == 1
    assert len(result.rows) == 1
    assert result.rows[0]["home_win"] is True
    assert result.rows[0]["home_prior_games_used"] == 0


def test_training_dataset_order_is_independent_of_caller_order() -> None:
    earlier = _game(60, KICKOFF - timedelta(days=1), home=1, away=2,
                    home_score=24, away_score=17)
    same_time_lower_id = _game(50, KICKOFF, home=3, away=4,
                               home_score=14, away_score=21)
    same_time_higher_id = _game(70, KICKOFF, home=5, away=6,
                                home_score=28, away_score=20)
    repository = InMemoryHistoryRepository([])
    builder = NFLMoneylineTrainingDatasetBuilder(
        provider_factory=lambda game: NFLFeatureDataProvider(
            game, repository=repository
        )
    )

    forward = builder.build([earlier, same_time_lower_id, same_time_higher_id])
    reversed_result = builder.build(
        [same_time_higher_id, same_time_lower_id, earlier]
    )

    assert forward.rows == reversed_result.rows
    assert [row["target_game_id"] for row in forward.rows] == [60, 50, 70]


def test_postgres_contract_has_strict_temporal_boundary_and_deterministic_order() -> None:
    normalized = " ".join(GET_NFL_COMPLETED_GAMES_BEFORE_QUERY.split())
    assert "nfl.scheduled_start_time < %s" in normalized
    assert "nfl.status = 'final'" in normalized
    assert "stats.team_id = game.home_team_id" in normalized
    assert "stats.team_id = game.away_team_id" in normalized
    assert "ORDER BY nfl.scheduled_start_time DESC, nfl.game_id DESC" in normalized


def _game(game_id, kickoff, *, week=1, home=1, away=2, home_score=17, away_score=10):
    return NflGame(
        game_id=game_id, season=2025, season_type=NflSeasonType.REGULAR,
        week=week, week_label=f"Week {week}", scheduled_start_time=kickoff,
        home_team_id=home, away_team_id=away, status=NflGameStatus.FINAL,
        home_score=home_score, away_score=away_score, overtime=False, neutral_site=False,
    )


def _history(game_id, kickoff, *, week=1, team, opponent, team_is_home=True,
             home_score=17, away_score=10):
    home, away = (team, opponent) if team_is_home else (opponent, team)
    game = _game(game_id, kickoff, week=week, home=home, away=away,
                 home_score=home_score, away_score=away_score)
    return HistoricalNflTeamGame(game, _statistics(game_id=game_id, team_id=team))


def _statistics(*, game_id, team_id):
    return NflTeamGameStatistics(
        game_id=game_id, team_id=team_id, completions=20, pass_attempts=30,
        passing_yards=220, passing_touchdowns=2, passing_interceptions=1,
        sacks_suffered=2, carries=25, rushing_yards=110, rushing_touchdowns=1,
        fumbles_lost=0, penalties=5, penalty_yards=45,
    )
