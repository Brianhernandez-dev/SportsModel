from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.nfl.dataset_audit import (
    SnapshotNflTeamHistoryRepository,
    audit_generated_dataset,
    dataset_fingerprint,
)
from sportsmodel.nfl.features import (
    HistoricalNflTeamGame,
    NFLFeatureDataProvider,
)
from sportsmodel.nfl.models import (
    NflGame,
    NflGameStatus,
    NflSeasonType,
    NflTeamGameStatistics,
)
from sportsmodel.nfl.moneyline_dataset import (
    NFLMoneylineTrainingDatasetBuilder,
)


KICKOFF = datetime(2025, 10, 26, 20, 20, tzinfo=timezone.utc)


def test_valid_dataset_and_independent_history_replay_pass_integrity_audit() -> None:
    game, dataset, traces, history = _built_case(_history_games(1))

    report = audit_generated_dataset(
        [game], dataset, traces, canonical_history=history,
    )

    assert report["integrity_passed"] is True
    assert report["integrity_findings"] == []


def test_duplicate_targets_invalid_label_and_rolling_violation_are_detected() -> None:
    game, dataset, traces, history = _built_case(_history_games(1))
    invalid = dict(dataset.rows[0])
    invalid["home_win"] = 1
    invalid["home_rolling_3_games_used"] = 4
    invalid["away_rolling_5_games_used"] = 0
    invalid_dataset = replace(dataset, rows=(invalid, invalid))

    report = audit_generated_dataset(
        [game], invalid_dataset, traces, canonical_history=history,
    )
    codes = _finding_codes(report)

    assert "duplicate_target_game_id" in codes
    assert "duplicate_dataset_row" in codes
    assert "invalid_home_win" in codes
    assert "rolling_window_exceeded" in codes
    assert "rolling_count_mismatch" in codes


def test_incorrect_boolean_class_label_is_detected() -> None:
    game, dataset, traces, history = _built_case(_history_games(1))
    row = dict(dataset.rows[0])
    row["home_win"] = False

    report = audit_generated_dataset(
        [game], replace(dataset, rows=(row,)), traces,
        canonical_history=history,
    )

    assert "incorrect_home_win" in _finding_codes(report)


def test_future_history_trace_is_detected() -> None:
    game, dataset, traces, history = _built_case(_history_games(1))
    future_pair = _history_pair(
        game_id=999, kickoff=KICKOFF + timedelta(hours=1),
        home_score=21, away_score=17, home_passing=310, away_passing=210,
        home_rushing=130, away_rushing=80,
        home_turnovers=0, away_turnovers=2,
    )
    future = replace(traces[0], source_games=(future_pair[0],))

    report = audit_generated_dataset(
        [game], dataset, (future, traces[1]),
        canonical_history=history + future_pair,
    )

    assert "future_history" in _finding_codes(report)


def test_omitted_eligible_history_is_detected_against_bulk_snapshot() -> None:
    game, dataset, traces, history = _built_case(_history_games(2))
    incomplete_home = replace(
        traces[0], source_games=traces[0].source_games[:-1],
    )

    report = audit_generated_dataset(
        [game], dataset, (incomplete_home, traces[1]),
        canonical_history=history,
    )

    assert "history_completeness_mismatch" in _finding_codes(report)
    assert "trace_history_count_mismatch" in _finding_codes(report)


def test_oldest_game_rolling_values_are_rejected() -> None:
    game, dataset, traces, history = _built_case(_history_games(6))
    row = dict(dataset.rows[0])
    home_history = traces[0].source_games
    for window in (3, 5):
        oldest = home_history[-window:]
        row[f"home_rolling_{window}_average_points_for"] = _average(
            [item.points_for for item in oldest]
        )
        row[f"home_rolling_{window}_average_points_against"] = _average(
            [item.points_against for item in oldest]
        )
        row[f"home_rolling_{window}_average_point_differential"] = _average([
            item.points_for - item.points_against for item in oldest
        ])

    report = audit_generated_dataset(
        [game], replace(dataset, rows=(row,)), traces,
        canonical_history=history,
    )

    assert "rolling_feature_replay" in _finding_codes(report)


def test_incorrect_opponent_allowed_and_takeaway_values_are_rejected() -> None:
    game, dataset, traces, history = _built_case(_history_games(2))
    row = dict(dataset.rows[0])
    row["home_average_passing_yards_allowed"] = row["home_average_passing_yards"]
    row["home_average_rushing_yards_allowed"] = row["home_average_rushing_yards"]
    row["home_average_takeaways"] = row["home_average_turnovers"]
    row["home_average_turnover_differential"] = 0.0

    report = audit_generated_dataset(
        [game], replace(dataset, rows=(row,)), traces,
        canonical_history=history,
    )

    assert "opponent_feature_replay" in _finding_codes(report)


def test_flattened_prior_count_must_match_complete_history() -> None:
    game, dataset, traces, history = _built_case(_history_games(2))
    row = dict(dataset.rows[0])
    row["away_prior_games_used"] = 1

    report = audit_generated_dataset(
        [game], replace(dataset, rows=(row,)), traces,
        canonical_history=history,
    )

    assert "prior_game_count_replay" in _finding_codes(report)


def test_builder_counters_are_reconciled_with_winner_tie_and_nonfinal() -> None:
    winner = _target_game()
    tie = replace(
        winner, game_id=2, scheduled_start_time=KICKOFF + timedelta(days=1),
        home_score=20, away_score=20,
    )
    nonfinal = replace(
        winner, game_id=3, scheduled_start_time=KICKOFF + timedelta(days=2),
        status=NflGameStatus.UNPLAYED, home_score=None, away_score=None,
        overtime=None,
    )
    game, dataset, traces, history = _built_case(())
    assert game == winner
    incorrect = replace(
        dataset, games_received=1, ties_skipped=0, nonfinal_games_skipped=0,
    )

    report = audit_generated_dataset(
        [winner, tie, nonfinal], incorrect, traces,
        canonical_history=history,
    )
    codes = _finding_codes(report)

    assert "games_received_mismatch" in codes
    assert "ties_skipped_mismatch" in codes
    assert "nonfinal_skipped_mismatch" in codes


def test_nonfinite_feature_is_detected_and_cannot_be_fingerprinted() -> None:
    game, dataset, traces, history = _built_case(_history_games(1))
    row = dict(dataset.rows[0])
    row["home_average_points_for"] = float("nan")
    report = audit_generated_dataset(
        [game], replace(dataset, rows=(row,)), traces,
        canonical_history=history,
    )

    assert "nonfinite_feature" in _finding_codes(report)
    with pytest.raises(ValueError):
        dataset_fingerprint([row])


def test_fingerprint_is_deterministic_across_mapping_key_order() -> None:
    row = _built_case(_history_games(1))[1].rows[0]
    reversed_row = dict(reversed(tuple(row.items())))

    assert dataset_fingerprint([row]) == dataset_fingerprint([reversed_row])


def test_fingerprint_normalizes_equivalent_timezone_offsets_to_utc() -> None:
    row = dict(_built_case(_history_games(1))[1].rows[0])
    offset = timezone(timedelta(hours=-7))
    same_instant = dict(row)
    same_instant["target_kickoff"] = row["target_kickoff"].astimezone(offset)
    same_instant["feature_cutoff"] = row["feature_cutoff"].astimezone(offset)
    different_instant = dict(same_instant)
    different_instant["target_kickoff"] += timedelta(seconds=1)

    assert dataset_fingerprint([row]) == dataset_fingerprint([same_instant])
    assert dataset_fingerprint([row]) != dataset_fingerprint([different_instant])


def test_fingerprint_rejects_naive_datetimes() -> None:
    row = dict(_built_case(_history_games(1))[1].rows[0])
    row["target_kickoff"] = row["target_kickoff"].replace(tzinfo=None)

    with pytest.raises(ValueError, match="must be timezone-aware"):
        dataset_fingerprint([row])


def test_fingerprint_covers_every_material_row_field_and_row_order() -> None:
    row = dict(_built_case(_history_games(1))[1].rows[0])
    changed = dict(row)
    changed["home_average_passing_yards"] += 1.0

    assert dataset_fingerprint([row]) != dataset_fingerprint([changed])
    assert dataset_fingerprint([row, changed]) != dataset_fingerprint([changed, row])


def _built_case(history):
    game = _target_game()
    canonical_history = tuple(history)
    snapshot = SnapshotNflTeamHistoryRepository(canonical_history)
    builder = NFLMoneylineTrainingDatasetBuilder(
        provider_factory=lambda target: NFLFeatureDataProvider(
            target, repository=snapshot.for_target(target),
        )
    )
    dataset = builder.build((game,))
    return game, dataset, tuple(snapshot.traces), canonical_history


def _target_game() -> NflGame:
    return NflGame(
        game_id=1, season=2025, season_type=NflSeasonType.REGULAR,
        week=8, week_label="Week 8", scheduled_start_time=KICKOFF,
        home_team_id=10, away_team_id=20, status=NflGameStatus.FINAL,
        home_score=24, away_score=17, overtime=False, neutral_site=False,
    )


def _history_games(count: int) -> tuple[HistoricalNflTeamGame, ...]:
    items = []
    for index in range(count):
        items.extend(_history_pair(
            game_id=100 + index,
            kickoff=KICKOFF - timedelta(days=7 * (index + 1)),
            home_score=30 - 3 * index,
            away_score=10 + index,
            home_passing=300 - 20 * index,
            away_passing=150 + 10 * index,
            home_rushing=140 - 5 * index,
            away_rushing=70 + 5 * index,
            home_turnovers=index % 3,
            away_turnovers=2 - (index % 3),
        ))
    return tuple(items)


def _history_pair(
    *, game_id: int, kickoff: datetime, home_score: int, away_score: int,
    home_passing: int, away_passing: int,
    home_rushing: int, away_rushing: int,
    home_turnovers: int, away_turnovers: int,
) -> tuple[HistoricalNflTeamGame, HistoricalNflTeamGame]:
    game = NflGame(
        game_id=game_id, season=2025, season_type=NflSeasonType.REGULAR,
        week=1, week_label="Prior", scheduled_start_time=kickoff,
        home_team_id=10, away_team_id=20, status=NflGameStatus.FINAL,
        home_score=home_score, away_score=away_score,
        overtime=False, neutral_site=False,
    )
    home = _statistics(
        game_id, 10, passing=home_passing, rushing=home_rushing,
        turnovers=home_turnovers,
    )
    away = _statistics(
        game_id, 20, passing=away_passing, rushing=away_rushing,
        turnovers=away_turnovers,
    )
    return (
        HistoricalNflTeamGame(game, home, away),
        HistoricalNflTeamGame(game, away, home),
    )


def _statistics(
    game_id: int, team_id: int, *, passing: int, rushing: int, turnovers: int,
) -> NflTeamGameStatistics:
    return NflTeamGameStatistics(
        game_id=game_id, team_id=team_id,
        completions=20, pass_attempts=30, passing_yards=passing,
        passing_touchdowns=2, passing_interceptions=turnovers,
        sacks_suffered=2, carries=25, rushing_yards=rushing,
        rushing_touchdowns=1, fumbles_lost=0, penalties=5, penalty_yards=45,
    )


def _average(values) -> float:
    return sum(values) / len(values)


def _finding_codes(report) -> set[str]:
    return {finding["code"] for finding in report["integrity_findings"]}
