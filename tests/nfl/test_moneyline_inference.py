from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.nfl.features import HistoricalNflTeamGame, NFLFeatureDataProvider
from sportsmodel.nfl.models import (
    NflGame,
    NflGameStatus,
    NflSeasonType,
    NflTeamGameStatistics,
)
from sportsmodel.nfl.moneyline_frozen import (
    EARLY_FEATURE_NAMES,
    MATURE_FEATURE_NAMES,
)
from sportsmodel.nfl.moneyline_inference import (
    NFLPredictedSide,
    _infer_nfl_moneyline,
    infer_nfl_moneyline,
)
from sportsmodel.nfl.moneyline_routing import (
    NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
    NFLMoneylineRoute,
    select_nfl_moneyline_route,
)


KICKOFF = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)


class HistoryRepository:
    def __init__(self, history):
        self.history = tuple(history)

    def get_completed_games_before(
        self, *, team_id, cutoff_time, season=None, limit=None
    ):
        result = [
            item
            for item in self.history
            if item.team_statistics.team_id == team_id
            and item.game.scheduled_start_time < cutoff_time
            and (season is None or item.game.season == season)
        ]
        result.sort(
            key=lambda item: (item.game.scheduled_start_time, item.game.game_id),
            reverse=True,
        )
        return tuple(result if limit is None else result[:limit])


@pytest.mark.parametrize(
    ("home", "away", "expected"),
    [
        (0, 0, NFLMoneylineRoute.EARLY),
        (2, 2, NFLMoneylineRoute.EARLY),
        (4, 2, NFLMoneylineRoute.EARLY),
        (2, 4, NFLMoneylineRoute.EARLY),
        (3, 3, NFLMoneylineRoute.MATURE),
        (4, 3, NFLMoneylineRoute.MATURE),
    ],
)
def test_pure_routing_contract(home, away, expected) -> None:
    assert select_nfl_moneyline_route(home, away) is expected


def test_routing_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="negative"):
        select_nfl_moneyline_route(-1, 3)


def test_early_inference_is_fit_free_exact_and_deterministic(monkeypatch) -> None:
    import sklearn.pipeline

    monkeypatch.setattr(
        sklearn.pipeline.Pipeline,
        "fit",
        lambda *args, **kwargs: pytest.fail("production inference cannot fit"),
    )
    target = _target()
    provider = NFLFeatureDataProvider(
        target,
        repository=HistoryRepository(_early_history()),
    )

    first = infer_nfl_moneyline(target, provider=provider)
    second = infer_nfl_moneyline(target, provider=provider)

    assert first == second
    assert first.selected_route is NFLMoneylineRoute.EARLY
    assert first.routing_contract_version == NFL_MONEYLINE_ROUTING_CONTRACT_VERSION
    assert first.ordered_feature_names == EARLY_FEATURE_NAMES
    assert len(first.ordered_feature_values) == 4
    assert first.home_current_prior_games == 0
    assert first.away_current_prior_games == 0
    assert 0 <= first.model_home_win_probability <= 1
    assert first.model_home_win_probability == 0.9389045037659678
    assert first.predicted_side is (
        NFLPredictedSide.HOME
        if first.model_home_win_probability >= first.classification_threshold
        else NFLPredictedSide.AWAY
    )
    assert first.feature_vector_fingerprint == second.feature_vector_fingerprint


def test_mature_inference_uses_exact_frozen_order_and_is_deterministic() -> None:
    target = _target()
    provider = NFLFeatureDataProvider(
        target,
        repository=HistoryRepository(_mature_history()),
    )

    first = infer_nfl_moneyline(target, provider=provider)
    second = infer_nfl_moneyline(target, provider=provider)

    assert first == second
    assert first.selected_route is NFLMoneylineRoute.MATURE
    assert first.ordered_feature_names == MATURE_FEATURE_NAMES
    assert len(first.ordered_feature_values) == 19
    assert first.home_current_prior_games == 3
    assert first.away_current_prior_games == 3
    assert 0 <= first.model_home_win_probability <= 1
    assert first.model_home_win_probability == 0.5324024480464203


def test_only_selected_route_artifact_is_loaded() -> None:
    target = _target()
    provider = NFLFeatureDataProvider(
        target,
        repository=HistoryRepository(_early_history()),
    )

    result = infer_nfl_moneyline(
        target,
        provider=provider,
        mature_artifact_loader=lambda: pytest.fail(
            "mature artifact must not load for early route"
        ),
    )
    assert result.selected_route is NFLMoneylineRoute.EARLY


def test_current_early_metadata_does_not_enter_learned_vector() -> None:
    target = _target()
    prior = _early_history()
    first_current = _current_history(2, score_offset=0)
    second_current = _current_history(2, score_offset=100)

    first = infer_nfl_moneyline(
        target,
        provider=NFLFeatureDataProvider(
            target,
            repository=HistoryRepository((*prior, *first_current)),
        ),
    )
    second = infer_nfl_moneyline(
        target,
        provider=NFLFeatureDataProvider(
            target,
            repository=HistoryRepository((*prior, *second_current)),
        ),
    )

    assert first.home_current_prior_games == second.home_current_prior_games == 2
    assert first.away_current_prior_games == second.away_current_prior_games == 2
    assert first.ordered_feature_values == second.ordered_feature_values
    assert first.model_home_win_probability == second.model_home_win_probability


def test_production_entry_rejects_pre_2026_and_known_results() -> None:
    historical = _target(season=2025)
    with pytest.raises(ValueError, match=r"2026\+"):
        infer_nfl_moneyline(historical)

    final = NflGame(
        **{
            **_target().__dict__,
            "status": NflGameStatus.FINAL,
            "home_score": 20,
            "away_score": 17,
            "overtime": False,
        }
    )
    with pytest.raises(ValueError, match="unplayed"):
        infer_nfl_moneyline(final)


def test_explicit_internal_path_can_replay_historical_fixture() -> None:
    target = _target(season=2025)
    result = _infer_nfl_moneyline(
        target,
        provider=NFLFeatureDataProvider(
            target,
            repository=HistoryRepository(()),
        ),
        require_forward_target=False,
    )
    assert result.season == 2025


def _target(*, season=2026) -> NflGame:
    return NflGame(
        game_id=9000,
        season=season,
        season_type=NflSeasonType.REGULAR,
        week=4,
        week_label="Week 4",
        scheduled_start_time=KICKOFF,
        home_team_id=1,
        away_team_id=2,
        status=NflGameStatus.UNPLAYED,
        home_score=None,
        away_score=None,
        overtime=None,
        neutral_site=False,
    )


def _early_history():
    return (
        _history(100, 2025, 1, 11, 24, 17),
        _history(101, 2025, 2, 12, 14, 21),
    )


def _mature_history():
    return _current_history(3, score_offset=0)


def _current_history(count, *, score_offset):
    return tuple(
        _history(
            200 + team * 10 + index,
            2026,
            team,
            20 + team * 10 + index,
            20 + score_offset + team + index,
            13 + index,
            days_ago=7 * (index + 1),
        )
        for team in (1, 2)
        for index in range(count)
    )


def _history(
    game_id,
    season,
    team,
    opponent,
    points_for,
    points_against,
    *,
    days_ago=300,
):
    kickoff = KICKOFF - timedelta(days=days_ago)
    game = NflGame(
        game_id=game_id,
        season=season,
        season_type=NflSeasonType.REGULAR,
        week=1,
        week_label="Week 1",
        scheduled_start_time=kickoff,
        home_team_id=team,
        away_team_id=opponent,
        status=NflGameStatus.FINAL,
        home_score=points_for,
        away_score=points_against,
        overtime=False,
        neutral_site=False,
    )
    return HistoricalNflTeamGame(
        game=game,
        team_statistics=_statistics(game_id, team, passing=220 + team),
        opponent_statistics=_statistics(game_id, opponent, passing=200 + team),
    )


def _statistics(game_id, team_id, *, passing):
    return NflTeamGameStatistics(
        game_id=game_id,
        team_id=team_id,
        completions=20,
        pass_attempts=30,
        passing_yards=passing,
        passing_touchdowns=2,
        passing_interceptions=1,
        sacks_suffered=2,
        carries=25,
        rushing_yards=105,
        rushing_touchdowns=1,
        fumbles_lost=0,
        penalties=5,
        penalty_yards=45,
    )
