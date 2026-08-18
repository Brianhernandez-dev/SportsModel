from dataclasses import replace
from datetime import datetime, timedelta, timezone
from statistics import median

import pytest

from sportsmodel.nfl.features import NFL_MONEYLINE_FEATURE_SCHEMA_VERSION
from sportsmodel.nfl.models import NflGame, NflGameStatus, NflSeasonType
from sportsmodel.nfl.moneyline_baseline import (
    NFL_BASELINE_FEATURE_NAMES,
    NFL_DEVELOPMENT_FOLDS,
    NFL_MISSING_VALUE_POLICIES,
    NflMissingValuePolicy,
    NflMoneylineModelingExample,
    build_nfl_moneyline_modeling_examples,
    evaluate_nfl_moneyline_development,
    nfl_development_evaluation_to_dict,
)


def test_matchup_representation_is_symmetric_nonredundant_and_target_free() -> None:
    game = _game(game_id=1, season=2024, index=0)
    row = _dataset_row(game, home_win=True)

    examples = build_nfl_moneyline_modeling_examples((row,), (game,))

    assert len(examples) == 1
    assert examples[0].feature_values[0] == 2.0
    assert examples[0].feature_values[1] == 1.0
    assert examples[0].home_win is True
    assert len(NFL_BASELINE_FEATURE_NAMES) == 19
    assert "matchup_average_point_differential_difference" not in NFL_BASELINE_FEATURE_NAMES
    assert "matchup_average_turnover_differential_difference" not in NFL_BASELINE_FEATURE_NAMES
    assert "matchup_rolling_3_average_point_differential_difference" not in NFL_BASELINE_FEATURE_NAMES
    assert "matchup_rolling_5_average_point_differential_difference" not in NFL_BASELINE_FEATURE_NAMES
    assert all("home_win" not in name for name in NFL_BASELINE_FEATURE_NAMES)
    assert all("score" not in name for name in NFL_BASELINE_FEATURE_NAMES)
    assert all("team_id" not in name for name in NFL_BASELINE_FEATURE_NAMES)

    loss_game = replace(game, game_id=2, home_score=17, away_score=24)
    loss = build_nfl_moneyline_modeling_examples(
        (_dataset_row(loss_game, home_win=False),), (loss_game,),
    )[0]
    assert loss.feature_values == examples[0].feature_values
    assert loss.home_win is False


def test_holdout_games_and_examples_are_rejected_before_evaluation() -> None:
    holdout_game = _game(game_id=1, season=2025, index=0)
    with pytest.raises(ValueError, match="2025 holdout games"):
        build_nfl_moneyline_modeling_examples((), (holdout_game,))

    examples = _development_examples()
    holdout = replace(
        examples[-1], game_id=9999, season=2025,
        kickoff=datetime(2025, 9, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="2025 holdout examples"):
        evaluate_nfl_moneyline_development((*examples[:-1], holdout))


def test_exact_expanding_season_folds_and_policy_retention_counts() -> None:
    evaluation = evaluate_nfl_moneyline_development(_development_examples())

    assert [
        (fold.training_seasons[0], fold.training_seasons[-1], fold.validation_season)
        for fold in evaluation.selected_evaluation.folds
    ] == [(2018, 2021, 2022), (2018, 2022, 2023), (2018, 2023, 2024)]
    assert NFL_DEVELOPMENT_FOLDS == (
        (1, 2021, 2022), (2, 2022, 2023), (3, 2023, 2024),
    )

    by_policy = {item.policy: item for item in evaluation.policies}
    assert by_policy[NflMissingValuePolicy.TRAINING_MEDIAN].selection_training_rows_retained == 63
    assert by_policy[NflMissingValuePolicy.TRAINING_MEDIAN].selection_validation_rows_evaluated == 14
    assert by_policy[NflMissingValuePolicy.MINIMUM_HISTORY_1].selection_training_rows_retained == 54
    assert by_policy[NflMissingValuePolicy.MINIMUM_HISTORY_1].selection_validation_rows_evaluated == 12
    assert by_policy[NflMissingValuePolicy.MINIMUM_HISTORY_3].selection_training_rows_retained == 36
    assert by_policy[NflMissingValuePolicy.MINIMUM_HISTORY_3].selection_validation_rows_evaluated == 8
    assert by_policy[NflMissingValuePolicy.MINIMUM_HISTORY_5].selection_training_rows_retained == 18
    assert by_policy[NflMissingValuePolicy.MINIMUM_HISTORY_5].selection_validation_rows_evaluated == 4
    assert by_policy[NflMissingValuePolicy.MINIMUM_HISTORY_5].validation_retention_rate < 0.80
    assert evaluation.selected_evaluation.selection_validation_retention_rate >= 0.80
    assert evaluation.selected_evaluation.selection_training_retention_rate >= 0.80
    assert all(
        len(policy.folds) == (
            3 if policy.policy is evaluation.selected_policy else 2
        )
        for policy in evaluation.policies
    )
    assert all(
        [fold.validation_season for fold in policy.folds]
        == (
            [2022, 2023, 2024]
            if policy.policy is evaluation.selected_policy
            else [2022, 2023]
        )
        for policy in evaluation.policies
    )

    for policy in evaluation.policies:
        for fold in policy.folds:
            assert set(fold.training_game_ids).isdisjoint(fold.validation_game_ids)
            assert fold.training_end_time < fold.validation_start_time
            assert all(
                prediction.season == fold.validation_season
                for prediction in fold.predictions
            )


def test_imputer_and_scaler_statistics_are_fit_from_training_fold_only() -> None:
    examples = _development_examples()
    evaluation = evaluate_nfl_moneyline_development(
        examples,
        policies=(NflMissingValuePolicy.TRAINING_MEDIAN,),
    )
    fold = evaluation.policies[0].folds[0]
    training = [item for item in examples if item.season <= 2021]
    validation = [item for item in examples if item.season == 2022]
    training_nonmissing = [
        item.feature_values[1]
        for item in training
        if item.feature_values[1] is not None
    ]
    expected_median = median(training_nonmissing)
    validation_values = [
        item.feature_values[1]
        for item in validation
        if item.feature_values[1] is not None
    ]

    assert fold.imputer_statistics[1] == pytest.approx(expected_median)
    assert max(validation_values) > max(training_nonmissing)
    imputed_training = [
        expected_median if item.feature_values[1] is None else item.feature_values[1]
        for item in training
    ]
    assert fold.scaler_means[1] == pytest.approx(
        sum(imputed_training) / len(imputed_training)
    )
    assert len(fold.imputer_statistics) == len(NFL_BASELINE_FEATURE_NAMES)
    assert len(fold.coefficients) == len(NFL_BASELINE_FEATURE_NAMES)
    assert isinstance(fold.intercept, float)
    assert tuple(item.feature_name for item in fold.coefficients) == NFL_BASELINE_FEATURE_NAMES


def test_repeated_development_evaluation_is_identical() -> None:
    examples = _development_examples()

    first = evaluate_nfl_moneyline_development(examples)
    second = evaluate_nfl_moneyline_development(examples)

    assert first.selected_policy is second.selected_policy
    assert first.report_fingerprint == second.report_fingerprint
    assert nfl_development_evaluation_to_dict(first) == (
        nfl_development_evaluation_to_dict(second)
    )
    assert tuple(item.policy for item in first.policies) == NFL_MISSING_VALUE_POLICIES


def test_policy_selection_uses_only_folds_one_and_two() -> None:
    examples = _development_examples()
    first = evaluate_nfl_moneyline_development(examples)
    changed_fold_three = tuple(
        replace(
            item,
            home_win=not item.home_win,
            feature_values=tuple(
                None if value is None else -value
                for value in item.feature_values
            ),
        )
        if item.season == 2024
        else item
        for item in examples
    )

    second = evaluate_nfl_moneyline_development(changed_fold_three)

    assert second.selected_policy is first.selected_policy
    for first_policy, second_policy in zip(
        first.policies, second.policies, strict=True,
    ):
        assert second_policy.selection_model_metrics == (
            first_policy.selection_model_metrics
        )
        assert second_policy.selection_validation_rows_evaluated == (
            first_policy.selection_validation_rows_evaluated
        )
    assert second.selected_evaluation.confirmation_fold.model_metrics != (
        first.selected_evaluation.confirmation_fold.model_metrics
    )


def test_training_label_shuffle_collapses_toward_no_signal() -> None:
    selected = evaluate_nfl_moneyline_development(
        _leakage_smoke_examples()
    ).selected_evaluation
    real = selected.aggregate_model_metrics
    shuffled = selected.aggregate_shuffled_label_metrics
    shuffled_aucs = [
        fold.shuffled_label_metrics.roc_auc for fold in selected.folds
    ]

    assert all(auc is not None and 0.20 <= auc <= 0.80 for auc in shuffled_aucs)
    assert shuffled.roc_auc is not None
    assert 0.35 <= shuffled.roc_auc <= 0.65
    assert shuffled.log_loss > real.log_loss + 0.01
    assert shuffled.brier_score > real.brier_score + 0.005


def test_bootstrap_intervals_are_paired_deterministic_and_segmented() -> None:
    evaluation = evaluate_nfl_moneyline_development(_leakage_smoke_examples())
    selected = evaluation.selected_evaluation
    intervals = evaluation.selected_aggregate_confidence_intervals
    differences = evaluation.selected_paired_difference_intervals

    assert intervals.accuracy.lower <= selected.aggregate_model_metrics.accuracy <= intervals.accuracy.upper
    assert intervals.log_loss.lower <= selected.aggregate_model_metrics.log_loss <= intervals.log_loss.upper
    assert intervals.brier_score.lower <= selected.aggregate_model_metrics.brier_score <= intervals.brier_score.upper
    assert intervals.roc_auc is not None
    assert differences.log_loss.upper < 0
    assert differences.brier_score.upper < 0
    assert differences.roc_auc is None
    segmented = evaluate_nfl_moneyline_development(_development_examples())
    segments = {item.name: item for item in segmented.selected_segments}
    assert segments["regular_season"].metrics is not None
    assert segments["postseason"].row_count == 3
    assert segments["postseason"].metrics is None


def _leakage_smoke_examples() -> tuple[NflMoneylineModelingExample, ...]:
    examples = []
    for season in range(2018, 2025):
        for index in range(40):
            home_win = index % 2 == 0
            signal = 1.0 if home_win else -1.0
            examples.append(NflMoneylineModelingExample(
                game_id=(season * 1000) + index + 1,
                kickoff=datetime(season, 9, 1, tzinfo=timezone.utc)
                + timedelta(days=index),
                season=season,
                season_type=NflSeasonType.REGULAR,
                home_win=home_win,
                home_prior_games=5,
                away_prior_games=5,
                feature_values=(
                    5.0,
                    *(
                        signal + (
                            ((index * 7 + feature_index * 3) % 17) - 8
                        ) / 5
                        for feature_index in range(
                            1, len(NFL_BASELINE_FEATURE_NAMES)
                        )
                    ),
                ),
            ))
    return tuple(examples)


def _development_examples() -> tuple[NflMoneylineModelingExample, ...]:
    examples = []
    for season in range(2018, 2025):
        for index in range(7):
            prior = index
            home_win = index % 2 == 0
            signal = 1.0 if home_win else -1.0
            values = [float(prior)]
            for feature_index in range(1, len(NFL_BASELINE_FEATURE_NAMES)):
                values.append(
                    None
                    if prior == 0
                    else signal * feature_index + 0.1 * (season - 2018)
                )
            if season == 2022 and prior > 0:
                values[1] += 1000.0
            examples.append(NflMoneylineModelingExample(
                game_id=(season * 100) + index + 1,
                kickoff=datetime(season, 9, 1, tzinfo=timezone.utc)
                + timedelta(days=index),
                season=season,
                season_type=(
                    NflSeasonType.POSTSEASON
                    if index == 6
                    else NflSeasonType.REGULAR
                ),
                home_win=home_win,
                home_prior_games=prior,
                away_prior_games=prior,
                feature_values=tuple(values),
            ))
    return tuple(examples)


def _game(*, game_id: int, season: int, index: int) -> NflGame:
    return NflGame(
        game_id=game_id,
        season=season,
        season_type=NflSeasonType.REGULAR,
        week=index + 1,
        week_label=f"Week {index + 1}",
        scheduled_start_time=datetime(season, 9, 1, tzinfo=timezone.utc)
        + timedelta(days=index),
        home_team_id=10,
        away_team_id=20,
        status=NflGameStatus.FINAL,
        home_score=24,
        away_score=17,
        overtime=False,
        neutral_site=False,
    )


def _dataset_row(game: NflGame, *, home_win: bool) -> dict[str, object]:
    row: dict[str, object] = {
        "target_game_id": game.game_id,
        "target_kickoff": game.scheduled_start_time,
        "feature_schema_version": NFL_MONEYLINE_FEATURE_SCHEMA_VERSION,
        "home_prior_games_used": 3,
        "away_prior_games_used": 2,
        "home_win": home_win,
    }
    for output_name in NFL_BASELINE_FEATURE_NAMES[1:]:
        suffix = output_name.removeprefix("matchup_").removesuffix("_difference")
        if suffix == "prior_games_used":
            continue
        row[f"home_{suffix}"] = 5.0
        row[f"away_{suffix}"] = 4.0
    return row
