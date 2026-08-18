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


def test_simultaneous_kickoff_games_cannot_see_each_other() -> None:
    first_target = _game(50, KICKOFF, home=1, away=2)
    second_target = _game(51, KICKOFF, home=1, away=3)
    earlier = _history(
        40, KICKOFF - timedelta(hours=1), team=1, opponent=4,
    )
    first_as_history = _history(50, KICKOFF, team=1, opponent=2)
    second_as_history = _history(51, KICKOFF, team=1, opponent=3)
    repository = InMemoryHistoryRepository([
        second_as_history, earlier, first_as_history,
    ])

    first_history = NFLFeatureDataProvider(
        first_target, repository=repository,
    ).get_team_history(team_id=1, season=2025)
    second_history = NFLFeatureDataProvider(
        second_target, repository=repository,
    ).get_team_history(team_id=1, season=2025)

    assert [item.game.game_id for item in first_history] == [40]
    assert [item.game.game_id for item in second_history] == [40]


def test_schedule_length_change_does_not_normalize_history_or_rolling_windows() -> None:
    for season, game_count in ((2020, 16), (2021, 17)):
        target_kickoff = datetime(season, 12, 31, 20, tzinfo=timezone.utc)
        target = _game(
            900 + season, target_kickoff, season=season, home=1, away=2,
        )
        history = [
            _history(
                (season * 100) + index + 1,
                target_kickoff - timedelta(days=index + 1),
                season=season, team=1, opponent=10 + index,
            )
            for index in range(game_count)
        ]

        vector = NFLGameFeatureVectorBuilder().build(
            target,
            provider=NFLFeatureDataProvider(
                target, repository=InMemoryHistoryRepository(history),
            ),
        ).home

        assert vector.prior_games_used == game_count
        assert vector.rolling_3.games_used == 3
        assert vector.rolling_5.games_used == 5


def test_2020_rescheduled_game_eligibility_uses_actual_kickoff_not_week() -> None:
    target_kickoff = datetime(2020, 11, 29, 18, tzinfo=timezone.utc)
    target = _game(
        900, target_kickoff, season=2020, week=12, home=1, away=2,
    )
    earlier_later_week = _history(
        901, target_kickoff - timedelta(hours=2),
        season=2020, week=13, team=1, opponent=3,
    )
    rescheduled_earlier_week = _history(
        902, target_kickoff + timedelta(days=3),
        season=2020, week=6, team=1, opponent=4,
    )

    history = NFLFeatureDataProvider(
        target,
        repository=InMemoryHistoryRepository([
            rescheduled_earlier_week, earlier_later_week,
        ]),
    ).get_team_history(team_id=1, season=2020)

    assert [item.game.game_id for item in history] == [901]


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
        HistoricalNflTeamGame(
            game, _statistics(game_id=11, team_id=1),
            _statistics(game_id=10, team_id=2),
        )
    with pytest.raises(ValueError, match="canonical game participant"):
        HistoricalNflTeamGame(
            game, _statistics(game_id=10, team_id=3),
            _statistics(game_id=10, team_id=2),
        )


@pytest.mark.parametrize(
    ("opponent_game_id", "opponent_team_id", "message"),
    [
        (11, 2, "opponent statistics must match"),
        (10, 1, "canonical opponent"),
        (10, 3, "canonical opponent"),
    ],
)
def test_historical_game_rejects_invalid_opponent_statistics(
    opponent_game_id, opponent_team_id, message,
) -> None:
    game = _game(10, KICKOFF - timedelta(days=7), home=1, away=2)

    with pytest.raises(ValueError, match=message):
        HistoricalNflTeamGame(
            game,
            _statistics(game_id=10, team_id=1),
            _statistics(
                game_id=opponent_game_id,
                team_id=opponent_team_id,
            ),
        )


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
    assert vector.home.average_point_differential is None
    assert vector.home.average_passing_yards is None
    assert vector.home.average_passing_yards_allowed is None
    assert vector.home.average_rushing_yards is None
    assert vector.home.average_rushing_yards_allowed is None
    assert vector.home.average_turnovers is None
    assert vector.home.average_takeaways is None
    assert vector.home.average_turnover_differential is None
    assert vector.home.rolling_3.games_used == 0
    assert vector.home.rolling_3.average_points_for is None
    assert vector.home.rolling_5.games_used == 0
    assert vector.home.rolling_5.average_turnover_differential is None


def test_team_catalog_and_partial_rolling_windows_are_hand_computable() -> None:
    target = _game(100, KICKOFF, home=1, away=2)
    games = [
        _history(
            game_id, KICKOFF - timedelta(days=days), team=1,
            opponent=10 + game_id, home_score=points_for,
            away_score=points_against, passing_yards=passing,
            opponent_passing_yards=allowed_passing, rushing_yards=rushing,
            opponent_rushing_yards=allowed_rushing,
            interceptions=interceptions, fumbles_lost=fumbles,
            opponent_interceptions=opponent_interceptions,
            opponent_fumbles_lost=opponent_fumbles,
        )
        for (
            game_id, days, points_for, points_against, passing,
            allowed_passing, rushing, allowed_rushing, interceptions,
            fumbles, opponent_interceptions, opponent_fumbles,
        ) in (
            (11, 7, 30, 20, 300, 200, 100, 80, 1, 0, 2, 0),
            (10, 14, 10, 13, 200, 220, 80, 90, 0, 1, 0, 0),
            (9, 21, 24, 21, 250, 240, 120, 100, 0, 0, 1, 0),
            (8, 28, 7, 17, 150, 260, 60, 110, 2, 1, 0, 1),
        )
    ]
    vector = NFLGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(
            target, repository=InMemoryHistoryRepository(games)
        ),
    ).home

    assert vector.prior_games_used == 4
    assert vector.average_points_for == 17.75
    assert vector.average_points_against == 17.75
    assert vector.average_point_differential == 0
    assert vector.average_passing_yards == 225
    assert vector.average_passing_yards_allowed == 230
    assert vector.average_rushing_yards == 90
    assert vector.average_rushing_yards_allowed == 95
    assert vector.average_turnovers == 1.25
    assert vector.average_takeaways == 1
    assert vector.average_turnover_differential == -0.25
    assert vector.rolling_3.games_used == 3
    assert vector.rolling_3.average_points_for == pytest.approx(64 / 3)
    assert vector.rolling_3.average_points_against == 18
    assert vector.rolling_3.average_point_differential == pytest.approx(10 / 3)
    assert vector.rolling_3.average_turnover_differential == pytest.approx(1 / 3)
    assert vector.rolling_5.games_used == 4
    assert vector.rolling_5.average_point_differential == 0


def test_season_history_uses_all_games_while_rolling_uses_newest_windows() -> None:
    target = _game(100, KICKOFF, home=1, away=2)
    points = (60, 50, 40, 30, 20, 0)
    games = [
        _history(
            20 - index,
            KICKOFF - timedelta(days=7 * (index + 1)),
            team=1,
            opponent=30 + index,
            home_score=points_for,
            away_score=0,
        )
        for index, points_for in enumerate(points)
    ]

    vector = NFLGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(
            target, repository=InMemoryHistoryRepository(games)
        ),
    ).home

    assert vector.prior_games_used == 6
    assert vector.average_points_for == pytest.approx(200 / 6)
    assert vector.average_point_differential == pytest.approx(200 / 6)
    assert vector.rolling_3.games_used == 3
    assert vector.rolling_3.average_points_for == 50
    assert vector.rolling_3.average_point_differential == 50
    assert vector.rolling_5.games_used == 5
    assert vector.rolling_5.average_points_for == 40
    assert vector.rolling_5.average_point_differential == 40
    assert vector.average_points_for != vector.rolling_3.average_points_for
    assert vector.average_points_for != vector.rolling_5.average_points_for


def test_feature_history_is_explicitly_target_season_only() -> None:
    target = _game(100, KICKOFF, season=2025, home=1, away=2)
    current = _history(11, KICKOFF - timedelta(days=7), season=2025,
                       team=1, opponent=3, home_score=21, away_score=14)
    prior = _history(10, KICKOFF - timedelta(days=300), season=2024,
                     team=1, opponent=4, home_score=40, away_score=0)

    vector = NFLGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(
            target, repository=InMemoryHistoryRepository([prior, current])
        ),
    ).home

    assert vector.prior_games_used == 1
    assert vector.average_points_for == 21
    assert vector.rolling_3.games_used == 1


def test_rolling_windows_exclude_target_and_later_same_week_games() -> None:
    target = _game(100, KICKOFF, week=4, home=1, away=2)
    earlier = _history(
        10, KICKOFF - timedelta(hours=3), week=4, team=1, opponent=3,
        home_score=17, away_score=10,
    )
    self_game = _history(
        100, KICKOFF, week=4, team=1, opponent=2,
        home_score=50, away_score=0,
    )
    later = _history(
        11, KICKOFF + timedelta(hours=2), week=4, team=1, opponent=4,
        home_score=60, away_score=0,
    )

    vector = NFLGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(
            target,
            repository=InMemoryHistoryRepository([later, self_game, earlier]),
        ),
    ).home

    assert vector.rolling_3.games_used == 1
    assert vector.rolling_3.average_points_for == 17
    assert vector.rolling_5.average_point_differential == 7


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
    assert result.rows[0]["home_rolling_3_games_used"] == 0
    assert result.rows[0]["home_rolling_5_average_points_for"] is None
    assert result.rows[0]["feature_schema_version"] == "nfl_moneyline_0.2.0"


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


def test_training_dataset_flattens_distinct_home_and_away_histories() -> None:
    target = _game(100, KICKOFF, home=1, away=2, home_score=24, away_score=17)
    home_history = _history(
        10, KICKOFF - timedelta(days=7), team=1, opponent=3,
        home_score=30, away_score=10,
        opponent_passing_yards=111,
        interceptions=1, fumbles_lost=0,
        opponent_interceptions=2, opponent_fumbles_lost=1,
    )
    away_history_newest = _history(
        12, KICKOFF - timedelta(days=7), team=2, opponent=4,
        home_score=7, away_score=17,
        opponent_passing_yards=333,
        interceptions=2, fumbles_lost=1,
        opponent_interceptions=1, opponent_fumbles_lost=0,
    )
    away_history_older = _history(
        11, KICKOFF - timedelta(days=14), team=2, opponent=5,
        home_score=14, away_score=24,
        opponent_passing_yards=555,
        interceptions=1, fumbles_lost=1,
        opponent_interceptions=0, opponent_fumbles_lost=0,
    )
    repository = InMemoryHistoryRepository(
        [away_history_older, home_history, away_history_newest]
    )
    result = NFLMoneylineTrainingDatasetBuilder(
        provider_factory=lambda game: NFLFeatureDataProvider(
            game, repository=repository
        )
    ).build([target])

    row = result.rows[0]
    assert row["home_average_passing_yards_allowed"] == 111
    assert row["away_average_passing_yards_allowed"] == 444
    assert row["home_average_turnover_differential"] == 2
    assert row["away_average_turnover_differential"] == -2
    assert row["home_rolling_3_games_used"] == 1
    assert row["away_rolling_3_games_used"] == 2
    assert row["home_rolling_5_games_used"] == 1
    assert row["away_rolling_5_games_used"] == 2
    assert row["home_rolling_3_average_point_differential"] == 20
    assert row["away_rolling_3_average_point_differential"] == -10
    assert row["home_rolling_5_average_point_differential"] == 20
    assert row["away_rolling_5_average_point_differential"] == -10


def test_postgres_contract_has_strict_temporal_boundary_and_deterministic_order() -> None:
    normalized = " ".join(GET_NFL_COMPLETED_GAMES_BEFORE_QUERY.split())
    assert "nfl.scheduled_start_time < %s" in normalized
    assert "nfl.status = 'final'" in normalized
    assert "stats.team_id = game.home_team_id" in normalized
    assert "stats.team_id = game.away_team_id" in normalized
    assert "ORDER BY nfl.scheduled_start_time DESC, nfl.game_id DESC" in normalized


def _game(game_id, kickoff, *, season=2025, week=1, home=1, away=2,
          home_score=17, away_score=10):
    return NflGame(
        game_id=game_id, season=season, season_type=NflSeasonType.REGULAR,
        week=week, week_label=f"Week {week}", scheduled_start_time=kickoff,
        home_team_id=home, away_team_id=away, status=NflGameStatus.FINAL,
        home_score=home_score, away_score=away_score, overtime=False, neutral_site=False,
    )


def _history(game_id, kickoff, *, season=2025, week=1, team, opponent,
             team_is_home=True, home_score=17, away_score=10,
             passing_yards=220, opponent_passing_yards=210,
             rushing_yards=110, opponent_rushing_yards=100,
             interceptions=1, fumbles_lost=0,
             opponent_interceptions=0, opponent_fumbles_lost=0):
    home, away = (team, opponent) if team_is_home else (opponent, team)
    game = _game(game_id, kickoff, season=season, week=week, home=home, away=away,
                 home_score=home_score, away_score=away_score)
    return HistoricalNflTeamGame(
        game,
        _statistics(
            game_id=game_id, team_id=team, passing_yards=passing_yards,
            rushing_yards=rushing_yards, interceptions=interceptions,
            fumbles_lost=fumbles_lost,
        ),
        _statistics(
            game_id=game_id, team_id=opponent,
            passing_yards=opponent_passing_yards,
            rushing_yards=opponent_rushing_yards,
            interceptions=opponent_interceptions,
            fumbles_lost=opponent_fumbles_lost,
        ),
    )


def _statistics(*, game_id, team_id, passing_yards=220, rushing_yards=110,
                interceptions=1, fumbles_lost=0):
    return NflTeamGameStatistics(
        game_id=game_id, team_id=team_id, completions=20, pass_attempts=30,
        passing_yards=passing_yards, passing_touchdowns=2,
        passing_interceptions=interceptions,
        sacks_suffered=2, carries=25, rushing_yards=rushing_yards,
        rushing_touchdowns=1, fumbles_lost=fumbles_lost,
        penalties=5, penalty_yards=45,
    )
