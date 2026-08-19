from dataclasses import replace
from datetime import datetime, timedelta, timezone
from statistics import median

import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from sportsmodel.nfl.early_dataset_audit import early_dataset_fingerprint
from sportsmodel.nfl.early_features import (
    NFL_EARLY_MONEYLINE_FEATURE_NAMES,
    NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION,
)
from sportsmodel.nfl.early_moneyline_baseline import (
    NFL_EARLY_BASELINE_C,
    NFL_EARLY_BASELINE_MAX_ITERATIONS,
    NFL_EARLY_BASELINE_RANDOM_STATE,
    NFL_EARLY_BASELINE_SOLVER,
    NFL_EARLY_BOOTSTRAP_ITERATIONS,
    NFL_EARLY_DEVELOPMENT_FOLDS,
    NFLEarlyMoneylineModelingExample,
    _pipeline,
    assert_nfl_early_production_dataset_contract,
    build_nfl_early_modeling_examples,
    evaluate_nfl_early_moneyline_baseline,
)


def test_fixed_specification_has_exact_pipeline_and_eleven_features() -> None:
    pipeline = _pipeline()

    assert len(NFL_EARLY_MONEYLINE_FEATURE_NAMES) == 11
    assert tuple(pipeline.named_steps) == ("imputer", "scaler", "classifier")
    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scaler"]
    classifier = pipeline.named_steps["classifier"]
    assert isinstance(imputer, SimpleImputer)
    assert imputer.strategy == "median"
    assert imputer.add_indicator is False
    assert isinstance(scaler, StandardScaler)
    assert isinstance(classifier, LogisticRegression)
    assert classifier.C == NFL_EARLY_BASELINE_C == 1.0
    assert classifier.solver == NFL_EARLY_BASELINE_SOLVER == "lbfgs"
    assert classifier.max_iter == NFL_EARLY_BASELINE_MAX_ITERATIONS == 5000
    assert classifier.random_state == NFL_EARLY_BASELINE_RANDOM_STATE == 42
    assert NFL_EARLY_BOOTSTRAP_ITERATIONS == 1000


def test_modeling_rows_assert_schema_order_and_exclude_target_metadata_from_x() -> None:
    rows = [_row(_examples()[0])]
    rows[0]["home_score"] = 99
    rows[0]["away_score"] = 0

    result = build_nfl_early_modeling_examples(rows)

    assert result[0].feature_values == _examples()[0].feature_values
    assert len(result[0].feature_values) == 11
    assert "home_win" not in NFL_EARLY_MONEYLINE_FEATURE_NAMES
    assert "target_game_id" not in NFL_EARLY_MONEYLINE_FEATURE_NAMES

    wrong_schema = dict(rows[0], feature_schema_version="wrong")
    with pytest.raises(ValueError, match="wrong schema"):
        build_nfl_early_modeling_examples([wrong_schema])
    wrong_order = dict(rows[0])
    wrong_order["feature_names"] = tuple(reversed(
        NFL_EARLY_MONEYLINE_FEATURE_NAMES
    ))
    with pytest.raises(ValueError, match="feature order"):
        build_nfl_early_modeling_examples([wrong_order])


def test_2025_row_is_rejected_before_modeling() -> None:
    row = _row(replace(_examples()[0], season=2025))

    with pytest.raises(ValueError, match="2019-2024"):
        build_nfl_early_modeling_examples([row])

    with pytest.raises(ValueError, match="2025 or later"):
        evaluate_nfl_early_moneyline_baseline(
            (
                *_examples(),
                replace(
                    _examples()[0],
                    game_id=999,
                    season=2025,
                    kickoff=datetime(2025, 9, 1, tzinfo=timezone.utc),
                ),
            ),
            dataset_fingerprint="synthetic",
        )


def test_modeling_rows_must_preserve_chronological_order() -> None:
    rows = [_row(item) for item in _examples()[:2]]

    with pytest.raises(ValueError, match="chronologically ordered"):
        build_nfl_early_modeling_examples(reversed(rows))


def test_locked_dataset_fingerprint_is_checked_against_rows_and_contract() -> None:
    rows = tuple(_row(item) for item in _examples())
    computed = early_dataset_fingerprint(rows)

    with pytest.raises(ValueError, match="reported early dataset fingerprint"):
        assert_nfl_early_production_dataset_contract(rows, "wrong")
    with pytest.raises(ValueError, match="locked Phase 3A1"):
        assert_nfl_early_production_dataset_contract(rows, computed)


def test_exact_expanding_folds_and_locked_confirmation_counts() -> None:
    evaluation = _evaluation()

    assert tuple(
        (fold.fold_number, fold.training_seasons, fold.validation_season)
        for fold in evaluation.development_folds
    ) == NFL_EARLY_DEVELOPMENT_FOLDS
    assert [fold.training_rows for fold in evaluation.development_folds] == [20, 30, 40]
    assert [fold.validation_rows for fold in evaluation.development_folds] == [10, 10, 10]
    assert evaluation.development_folds[0].training_home_win_rate == pytest.approx(
        sum(item.home_win for item in _examples() if item.season in {2019, 2020})
        / 20
    )
    assert evaluation.confirmation.training_seasons == (2019, 2020, 2021, 2022, 2023)
    assert evaluation.confirmation.training_rows == 50
    assert evaluation.confirmation.validation_season == 2024
    assert evaluation.confirmation.validation_rows == 10
    assert len(evaluation.confirmation.coefficients) == 11
    assert all(
        prediction.season in {2021, 2022, 2023}
        for fold in evaluation.development_folds
        for prediction in fold.predictions
    )


def test_imputer_and_scaler_are_fit_on_training_rows_only() -> None:
    examples = _examples()
    evaluation = evaluate_nfl_early_moneyline_baseline(
        examples,
        dataset_fingerprint="synthetic",
    )
    fold = evaluation.development_folds[0]
    training = [item for item in examples if item.season in {2019, 2020}]
    expected_median = median(
        item.feature_values[5]
        for item in training
        if item.feature_values[5] is not None
    )
    assert fold.imputer_statistics[5] == expected_median
    assert len(fold.imputer_statistics) == 11
    assert len(fold.scaler_means) == 11
    assert len(fold.scaler_scales) == 11

    changed_validation = tuple(
        replace(
            item,
            feature_values=(
                item.feature_values[:5]
                + (9999.0,)
                + item.feature_values[6:]
            ),
        )
        if item.season == 2021 else item
        for item in examples
    )
    changed = evaluate_nfl_early_moneyline_baseline(
        changed_validation,
        dataset_fingerprint="synthetic",
    )
    assert changed.development_folds[0].imputer_statistics == fold.imputer_statistics
    assert changed.development_folds[0].scaler_means == fold.scaler_means
    assert changed.development_folds[0].scaler_scales == fold.scaler_scales


def test_2024_cannot_change_development_fits_predictions_or_metrics() -> None:
    examples = _examples()
    first = evaluate_nfl_early_moneyline_baseline(
        examples,
        dataset_fingerprint="synthetic",
    )
    changed_2024 = tuple(
        replace(
            item,
            home_win=not item.home_win,
            feature_values=tuple(
                None if value is None else value * -5
                for value in item.feature_values
            ),
        )
        if item.season == 2024 else item
        for item in examples
    )
    second = evaluate_nfl_early_moneyline_baseline(
        changed_2024,
        dataset_fingerprint="synthetic",
    )

    assert first.development_folds == second.development_folds
    assert first.development_model_metrics == second.development_model_metrics
    assert first.development_confidence_intervals == (
        second.development_confidence_intervals
    )
    assert first.confirmation.coefficients == second.confirmation.coefficients
    assert first.confirmation.predictions != second.confirmation.predictions


def test_repeated_evaluation_is_fully_deterministic() -> None:
    first = _evaluation()
    second = _evaluation()

    assert first == second
    assert first.report_fingerprint == second.report_fingerprint
    assert sum(
        item.prediction_count for item in first.development_calibration_bins
    ) == 30
    assert sum(
        item.prediction_count for item in first.confirmation_calibration_bins
    ) == 10
    assert {item.minimum_current_prior_games for item in (
        *first.development_history_states,
        *first.confirmation_history_states,
    )} == {0, 1, 2}


def test_label_shuffle_and_2020_sensitivity_are_diagnostic_only() -> None:
    evaluation = _evaluation()

    assert all(
        fold.shuffled_label_metrics is not None
        for fold in evaluation.development_folds
    )
    assert 0.0 <= evaluation.development_shuffled_label_metrics.roc_auc <= 1.0
    assert [
        fold.training_rows_without_2020
        for fold in evaluation.sensitivity_without_2020.folds
    ] == [10, 20, 30]
    assert evaluation.confirmation.shuffled_label_metrics is None


def _evaluation():
    return evaluate_nfl_early_moneyline_baseline(
        _examples(),
        dataset_fingerprint="synthetic",
    )


def _examples() -> tuple[NFLEarlyMoneylineModelingExample, ...]:
    values = []
    game_id = 1
    for season in range(2019, 2025):
        season_start = datetime(season, 9, 1, tzinfo=timezone.utc)
        for index in range(10):
            state = index % 3
            current = None if state == 0 else (index - 4) / 5
            feature_values = (
                float((index % 3) - 1),
                (index - 4) / 10,
                float(index - 4),
                float((index % 5) - 2),
                float((index % 3) - 1),
                current,
                None if current is None else 20 + index,
                None if current is None else 18 - index / 2,
                None if current is None else float((index % 4) - 2),
                float(state),
                float(index == 9),
            )
            values.append(NFLEarlyMoneylineModelingExample(
                game_id=game_id,
                kickoff=season_start + timedelta(days=index),
                season=season,
                home_win=(index + season) % 4 != 0,
                minimum_current_prior_games=state,
                neutral_site=index == 9,
                feature_values=feature_values,
            ))
            game_id += 1
    return tuple(values)


def _row(item) -> dict[str, object]:
    row = {
        "target_game_id": item.game_id,
        "target_kickoff": item.kickoff,
        "target_season": item.season,
        "feature_schema_version": NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION,
        "route": "early",
        "feature_names": NFL_EARLY_MONEYLINE_FEATURE_NAMES,
        "feature_values": item.feature_values,
        "minimum_current_prior_games": item.minimum_current_prior_games,
        "home_win": item.home_win,
    }
    row.update(dict(zip(
        NFL_EARLY_MONEYLINE_FEATURE_NAMES,
        item.feature_values,
        strict=True,
    )))
    return row
