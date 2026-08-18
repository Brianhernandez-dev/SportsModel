from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.nfl.early_dataset_audit import early_dataset_fingerprint
from sportsmodel.nfl.early_features import (
    NFL_EARLY_MONEYLINE_FEATURE_NAMES,
    NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION,
    NFLEarlyGameFeatureVectorBuilder,
    NFLMoneylineRoute,
    select_nfl_moneyline_route,
)
from sportsmodel.nfl.early_moneyline_dataset import (
    NFLEarlyMoneylineTrainingDatasetBuilder,
)
from sportsmodel.nfl.features import HistoricalNflTeamGame, NFLFeatureDataProvider
from sportsmodel.nfl.models import (
    NflGame,
    NflGameStatus,
    NflSeasonType,
    NflTeamGameStatistics,
)


KICKOFF = datetime(2022, 9, 25, 17, tzinfo=timezone.utc)


class InMemoryHistoryRepository:
    def __init__(self, history):
        self.history = tuple(history)
        self.requests = []

    def get_completed_games_before(
        self,
        *,
        team_id,
        cutoff_time,
        season=None,
        limit=None,
    ):
        self.requests.append((team_id, cutoff_time, season, limit))
        eligible = [
            item
            for item in self.history
            if item.team_statistics.team_id == team_id
            and item.game.status is NflGameStatus.FINAL
            and item.game.scheduled_start_time < cutoff_time
            and (season is None or item.game.season == season)
        ]
        eligible.sort(
            key=lambda item: (
                item.game.scheduled_start_time,
                item.game.game_id,
            ),
            reverse=True,
        )
        return tuple(eligible if limit is None else eligible[:limit])


@pytest.mark.parametrize(
    ("home_count", "away_count", "expected"),
    [
        (0, 0, NFLMoneylineRoute.EARLY),
        (1, 1, NFLMoneylineRoute.EARLY),
        (2, 2, NFLMoneylineRoute.EARLY),
        (4, 2, NFLMoneylineRoute.EARLY),
        (2, 4, NFLMoneylineRoute.EARLY),
        (3, 3, NFLMoneylineRoute.MATURE),
        (4, 3, NFLMoneylineRoute.MATURE),
    ],
)
def test_routing_uses_actual_current_game_counts(
    home_count,
    away_count,
    expected,
) -> None:
    assert select_nfl_moneyline_route(home_count, away_count) is expected


def test_2022_target_uses_2021_regular_season_not_calendar_year() -> None:
    target = _target(season=2022)
    prior_regular = _history_for_team(
        100,
        datetime(2021, 12, 26, 18, tzinfo=timezone.utc),
        season=2021,
        team=10,
        opponent=30,
        home_score=21,
        away_score=14,
    )
    january_postseason = _history_for_team(
        101,
        datetime(2022, 1, 16, 18, tzinfo=timezone.utc),
        season=2021,
        season_type=NflSeasonType.POSTSEASON,
        team=10,
        opponent=31,
        home_score=45,
        away_score=10,
    )
    wrong_calendar_season = _history_for_team(
        102,
        datetime(2022, 1, 2, 18, tzinfo=timezone.utc),
        season=2022,
        team=10,
        opponent=32,
        home_score=40,
        away_score=0,
    )
    repository = InMemoryHistoryRepository([
        wrong_calendar_season,
        january_postseason,
        prior_regular,
    ])

    home = NFLEarlyGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(target, repository=repository),
    ).home

    assert home.prior_season.games_played == 1
    assert home.prior_season.source_game_ids == (100,)
    assert home.prior_season.average_point_differential == 7
    assert home.current_season.source_game_ids == (102,)
    assert {(request[2], request[3]) for request in repository.requests} == {
        (2021, None),
        (2022, None),
    }


def test_2019_target_sources_complete_2018_regular_season() -> None:
    target = _target(season=2019, kickoff=datetime(
        2019, 9, 8, 17, tzinfo=timezone.utc,
    ))
    prior = _history_for_team(
        90,
        datetime(2018, 12, 30, 18, tzinfo=timezone.utc),
        season=2018,
        team=10,
        opponent=30,
        home_score=17,
        away_score=17,
    )

    home = NFLEarlyGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(
            target,
            repository=InMemoryHistoryRepository([prior]),
        ),
    ).home

    assert home.prior_season.games_played == 1
    assert home.prior_season.win_percentage == 0.5
    assert home.prior_season.source_game_ids == (90,)


@pytest.mark.parametrize("current_count", [0, 1, 2])
def test_current_season_zero_one_two_game_states(current_count) -> None:
    target = _target()
    history = [
        _history_for_team(
            200 + index,
            KICKOFF - timedelta(days=7 * (index + 1)),
            season=2022,
            team=10,
            opponent=30 + index,
            home_score=10 + index,
            away_score=7,
        )
        for index in range(current_count)
    ]

    current = NFLEarlyGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(
            target,
            repository=InMemoryHistoryRepository(history),
        ),
    ).home.current_season

    assert current.games_played == current_count
    if current_count == 0:
        assert current.win_percentage is None
        assert current.average_points_for is None
        assert current.average_points_against is None
        assert current.average_point_differential is None
        assert current.average_turnover_differential is None
    else:
        assert current.win_percentage == 1.0
        assert current.average_points_for is not None


def test_strict_cutoff_excludes_future_simultaneous_and_target_games() -> None:
    target = _target(game_id=300, week=3)
    eligible = _history_for_team(
        201,
        KICKOFF - timedelta(hours=1),
        season=2022,
        week=10,
        team=10,
        opponent=31,
    )
    simultaneous = _history_for_team(
        202,
        KICKOFF,
        season=2022,
        week=2,
        team=10,
        opponent=32,
    )
    target_as_history = _history_for_team(
        300,
        KICKOFF,
        season=2022,
        week=3,
        team=10,
        opponent=20,
    )
    postponed_earlier_week = _history_for_team(
        203,
        KICKOFF + timedelta(days=2),
        season=2022,
        week=1,
        team=10,
        opponent=33,
    )

    current = NFLEarlyGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(
            target,
            repository=InMemoryHistoryRepository([
                postponed_earlier_week,
                target_as_history,
                simultaneous,
                eligible,
            ]),
        ),
    ).home.current_season

    assert current.source_game_ids == (201,)


def test_canonical_team_id_preserves_franchise_continuity() -> None:
    stable_franchise_id = 2520
    target = _target(home=stable_franchise_id)
    oakland_era_history = _history_for_team(
        100,
        datetime(2021, 12, 20, 1, tzinfo=timezone.utc),
        season=2021,
        team=stable_franchise_id,
        opponent=30,
        home_score=24,
        away_score=20,
    )

    home = NFLEarlyGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(
            target,
            repository=InMemoryHistoryRepository([oakland_era_history]),
        ),
    ).home

    assert home.team_id == stable_franchise_id
    assert home.prior_season.source_game_ids == (100,)


def test_symmetric_features_preserve_none_and_home_away_orientation() -> None:
    target = _target(neutral_site=True)
    home_prior = _history_for_team(
        100,
        KICKOFF - timedelta(days=300),
        season=2021,
        team=10,
        opponent=30,
        home_score=30,
        away_score=10,
        turnovers=0,
        opponent_turnovers=2,
    )
    away_prior = _history_for_team(
        101,
        KICKOFF - timedelta(days=301),
        season=2021,
        team=20,
        opponent=31,
        home_score=7,
        away_score=21,
        turnovers=3,
        opponent_turnovers=0,
    )
    home_current = _history_for_team(
        200,
        KICKOFF - timedelta(days=7),
        season=2022,
        team=10,
        opponent=32,
        home_score=24,
        away_score=20,
    )
    vector = NFLEarlyGameFeatureVectorBuilder().build(
        target,
        provider=NFLFeatureDataProvider(
            target,
            repository=InMemoryHistoryRepository([
                away_prior,
                home_current,
                home_prior,
            ]),
        ),
    )
    features = dict(zip(
        vector.feature_names,
        vector.feature_values,
        strict=True,
    ))

    assert features["prior_season_average_point_differential_difference"] == 34
    assert features["prior_season_average_turnover_differential_difference"] == 5
    assert features["current_season_prior_games_played_difference"] == 1
    assert features["current_season_average_points_for_difference"] is None
    assert features["minimum_current_season_prior_games"] == 0
    assert features["neutral_site"] == 1
    assert vector.route is NFLMoneylineRoute.EARLY


def test_early_dataset_is_inspectable_deterministic_and_excludes_mature() -> None:
    earlier = _target(
        game_id=400,
        season=2021,
        kickoff=datetime(2021, 9, 12, 17, tzinfo=timezone.utc),
    )
    later = _target(game_id=401)
    repository = InMemoryHistoryRepository([])
    builder = NFLEarlyMoneylineTrainingDatasetBuilder(
        provider_factory=lambda game: NFLFeatureDataProvider(
            game,
            repository=repository,
        )
    )

    forward = builder.build([later, earlier])
    reverse = builder.build([earlier, later])

    assert forward == reverse
    assert [row["target_game_id"] for row in forward.rows] == [400, 401]
    assert forward.rows[0]["feature_schema_version"] == (
        NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION
    )
    assert forward.rows[0]["feature_names"] == NFL_EARLY_MONEYLINE_FEATURE_NAMES
    assert len(forward.rows[0]["feature_names"]) == 11
    assert (
        "current_season_average_point_differential_difference"
        not in forward.rows[0]
    )
    assert forward.rows[0]["target_tie"] is False
    assert early_dataset_fingerprint(forward.rows) == early_dataset_fingerprint(
        reverse.rows
    )


def test_dataset_ties_are_excluded_and_reported() -> None:
    tie = replace(_target(), home_score=17, away_score=17)
    result = NFLEarlyMoneylineTrainingDatasetBuilder(
        provider_factory=lambda game: pytest.fail("tie must not build features")
    ).build([tie])

    assert result.rows == ()
    assert result.ties_skipped == 1


def test_2025_target_is_rejected_before_history_access() -> None:
    calls = 0

    def provider_factory(game):
        nonlocal calls
        calls += 1
        return pytest.fail("guard must run before provider construction")

    with pytest.raises(ValueError, match="outside the guarded range"):
        NFLEarlyMoneylineTrainingDatasetBuilder(
            provider_factory=provider_factory
        ).build([_target(season=2025)])

    assert calls == 0


def _target(
    *,
    game_id=500,
    season=2022,
    kickoff=KICKOFF,
    week=3,
    home=10,
    away=20,
    neutral_site=False,
) -> NflGame:
    return NflGame(
        game_id=game_id,
        season=season,
        season_type=NflSeasonType.REGULAR,
        week=week,
        week_label=f"Week {week}",
        scheduled_start_time=kickoff,
        home_team_id=home,
        away_team_id=away,
        status=NflGameStatus.FINAL,
        home_score=24,
        away_score=17,
        overtime=False,
        neutral_site=neutral_site,
    )


def _history_for_team(
    game_id,
    kickoff,
    *,
    season,
    team,
    opponent,
    season_type=NflSeasonType.REGULAR,
    week=1,
    team_is_home=True,
    home_score=17,
    away_score=10,
    turnovers=1,
    opponent_turnovers=1,
) -> HistoricalNflTeamGame:
    home, away = (team, opponent) if team_is_home else (opponent, team)
    game = NflGame(
        game_id=game_id,
        season=season,
        season_type=season_type,
        week=week,
        week_label=f"Week {week}",
        scheduled_start_time=kickoff,
        home_team_id=home,
        away_team_id=away,
        status=NflGameStatus.FINAL,
        home_score=home_score,
        away_score=away_score,
        overtime=False,
        neutral_site=False,
    )
    team_stats = _statistics(game_id, team, turnovers)
    opponent_stats = _statistics(game_id, opponent, opponent_turnovers)
    return HistoricalNflTeamGame(game, team_stats, opponent_stats)


def _statistics(game_id, team_id, turnovers) -> NflTeamGameStatistics:
    return NflTeamGameStatistics(
        game_id=game_id,
        team_id=team_id,
        completions=20,
        pass_attempts=30,
        passing_yards=220,
        passing_touchdowns=2,
        passing_interceptions=turnovers,
        sacks_suffered=2,
        carries=25,
        rushing_yards=110,
        rushing_touchdowns=1,
        fumbles_lost=0,
        penalties=5,
        penalty_yards=45,
    )
