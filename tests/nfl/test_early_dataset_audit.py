from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.nfl.dataset_audit import SnapshotNflTeamHistoryRepository
from sportsmodel.nfl.early_dataset_audit import (
    audit_generated_early_dataset,
    build_and_audit_production_early_dataset,
    early_dataset_fingerprint,
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


TARGET_KICKOFF = datetime(2022, 9, 18, 17, tzinfo=timezone.utc)


def test_valid_dataset_passes_independent_two_channel_replay() -> None:
    target, dataset, traces, history = _built_case()

    report = audit_generated_early_dataset(
        [target],
        dataset,
        traces,
        canonical_history=history,
        season_from=2022,
        season_to=2022,
    )

    assert report["integrity_passed"] is True
    assert report["integrity_findings"] == []
    assert report["early_route_counts_by_season"] == {2022: 1}
    assert report["minimum_current_prior_game_counts"] == {0: 1}
    assert report["prior_season_source_coverage_by_target_season"] == {
        2022: {
            "targets": 1,
            "both_teams_available": 1,
            "team_channels_available": 2,
            "team_channels_total": 2,
        }
    }


def test_audit_detects_postseason_in_prior_channel_and_bad_symmetric_math() -> None:
    target, dataset, traces, history = _built_case()
    row = dict(dataset.rows[0])
    row["home_prior_season_source_game_ids"] = (102, 100)
    row["prior_season_average_point_differential_difference"] = -999.0
    values = list(row["feature_values"])
    values[2] = -999.0
    row["feature_values"] = tuple(values)

    report = audit_generated_early_dataset(
        [target],
        replace(dataset, rows=(row,)),
        traces,
        canonical_history=history,
        season_from=2022,
        season_to=2022,
    )

    codes = _codes(report)
    assert "channel_replay_mismatch" in codes
    assert "symmetric_feature_mismatch" in codes


def test_audit_detects_omitted_current_source_and_wrong_route_population() -> None:
    target, dataset, traces, history = _built_case()
    current_trace = next(
        trace
        for trace in traces
        if trace.team_id == target.home_team_id
        and trace.requested_season == target.season
    )
    tampered = replace(current_trace, source_games=())
    altered_traces = tuple(
        tampered if trace is current_trace else trace
        for trace in traces
    )
    missing_dataset = replace(dataset, rows=())

    report = audit_generated_early_dataset(
        [target],
        missing_dataset,
        altered_traces,
        canonical_history=history,
        season_from=2022,
        season_to=2022,
    )

    codes = _codes(report)
    assert "trace_source_set_mismatch" in codes
    assert "early_target_population_mismatch" in codes


def test_fingerprint_canonicalizes_nested_timestamps_and_mapping_order() -> None:
    _, dataset, _, _ = _built_case()
    row = dataset.rows[0]
    reversed_row = dict(reversed(tuple(row.items())))
    offset = timezone(timedelta(hours=-7))
    equivalent = dict(reversed_row)
    equivalent["home_prior_season_source_kickoffs"] = tuple(
        kickoff.astimezone(offset)
        for kickoff in row["home_prior_season_source_kickoffs"]
    )

    assert early_dataset_fingerprint([row]) == early_dataset_fingerprint([
        equivalent
    ])


def test_audit_range_guard_rejects_2025_without_opening_database() -> None:
    opened = False

    def connection_factory():
        nonlocal opened
        opened = True
        return pytest.fail("range guard must run before database access")

    with pytest.raises(ValueError, match="after 2024"):
        build_and_audit_production_early_dataset(
            season_from=2019,
            season_to=2025,
            connection_factory=connection_factory,
        )

    assert opened is False


def _built_case():
    target = _game(
        500,
        TARGET_KICKOFF,
        season=2022,
        home=10,
        away=20,
    )
    history = (
        *_pair(
            100,
            datetime(2021, 12, 26, 18, tzinfo=timezone.utc),
            season=2021,
            home=10,
            away=30,
            home_score=24,
            away_score=10,
            home_turnovers=0,
            away_turnovers=2,
        ),
        *_pair(
            101,
            datetime(2021, 12, 27, 1, tzinfo=timezone.utc),
            season=2021,
            home=31,
            away=20,
            home_score=21,
            away_score=17,
            home_turnovers=1,
            away_turnovers=3,
        ),
        *_pair(
            102,
            datetime(2022, 1, 16, 18, tzinfo=timezone.utc),
            season=2021,
            season_type=NflSeasonType.POSTSEASON,
            home=10,
            away=32,
            home_score=40,
            away_score=7,
            home_turnovers=0,
            away_turnovers=4,
        ),
        *_pair(
            200,
            TARGET_KICKOFF - timedelta(days=7),
            season=2022,
            home=10,
            away=33,
            home_score=17,
            away_score=14,
            home_turnovers=1,
            away_turnovers=2,
        ),
    )
    snapshot = SnapshotNflTeamHistoryRepository(history)
    dataset = NFLEarlyMoneylineTrainingDatasetBuilder(
        season_from=2022,
        season_to=2022,
        provider_factory=lambda game: NFLFeatureDataProvider(
            game,
            repository=snapshot.for_target(game),
        ),
    ).build([target])
    return target, dataset, tuple(snapshot.traces), history


def _pair(
    game_id,
    kickoff,
    *,
    season,
    home,
    away,
    home_score,
    away_score,
    home_turnovers,
    away_turnovers,
    season_type=NflSeasonType.REGULAR,
):
    game = _game(
        game_id,
        kickoff,
        season=season,
        season_type=season_type,
        home=home,
        away=away,
        home_score=home_score,
        away_score=away_score,
    )
    home_stats = _statistics(game_id, home, home_turnovers)
    away_stats = _statistics(game_id, away, away_turnovers)
    return (
        HistoricalNflTeamGame(game, home_stats, away_stats),
        HistoricalNflTeamGame(game, away_stats, home_stats),
    )


def _game(
    game_id,
    kickoff,
    *,
    season,
    home,
    away,
    home_score=24,
    away_score=17,
    season_type=NflSeasonType.REGULAR,
):
    return NflGame(
        game_id=game_id,
        season=season,
        season_type=season_type,
        week=1,
        week_label="Week 1",
        scheduled_start_time=kickoff,
        home_team_id=home,
        away_team_id=away,
        status=NflGameStatus.FINAL,
        home_score=home_score,
        away_score=away_score,
        overtime=False,
        neutral_site=False,
    )


def _statistics(game_id, team_id, turnovers):
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
        rushing_yards=100,
        rushing_touchdowns=1,
        fumbles_lost=0,
        penalties=5,
        penalty_yards=45,
    )


def _codes(report):
    return {item["code"] for item in report["integrity_findings"]}
