from dataclasses import replace
from datetime import datetime, timedelta, timezone
from statistics import median

import pytest

import scripts.evaluate_nfl_moneyline_final_holdout as holdout_script
from sportsmodel.nfl.features import NFL_MONEYLINE_FEATURE_SCHEMA_VERSION
from sportsmodel.nfl.models import NflGame, NflGameStatus, NflSeasonType
from sportsmodel.nfl.moneyline_baseline import (
    NFL_BASELINE_FEATURE_NAMES,
    NflMoneylineModelingExample,
    build_nfl_moneyline_holdout_examples,
    build_nfl_moneyline_modeling_examples,
)
import sportsmodel.nfl.moneyline_holdout as holdout_module
from sportsmodel.nfl.moneyline_holdout import (
    FROZEN_NFL_BASELINE_SPECIFICATION,
    FROZEN_NFL_FEATURE_NAMES,
    FROZEN_NFL_MINIMUM_HISTORY,
    FinalNflHoldoutConfirmationRequired,
    assert_frozen_nfl_baseline_specification,
    evaluate_frozen_nfl_moneyline_holdout,
    nfl_final_holdout_evaluation_to_dict,
    run_guarded_final_nfl_holdout_evaluation,
)


def test_guard_refuses_before_any_loader_is_invoked() -> None:
    calls: list[str] = []

    def development_loader():
        calls.append("development")
        raise AssertionError("must not load")

    def holdout_loader():
        calls.append("holdout")
        raise AssertionError("must not load")

    with pytest.raises(FinalNflHoldoutConfirmationRequired):
        run_guarded_final_nfl_holdout_evaluation(
            confirmed=False,
            development_loader=development_loader,
            holdout_loader=holdout_loader,
        )

    assert calls == []


def test_cli_refuses_before_production_dataset_function_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden_production_load(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("production loader must not run")

    monkeypatch.setattr(
        holdout_script, "build_and_audit_production_dataset",
        forbidden_production_load,
    )
    with pytest.raises(SystemExit) as raised:
        holdout_script.main(["--json-output", "unused-synthetic-report.json"])

    assert raised.value.code == 2
    assert calls == 0


def test_frozen_specification_matches_exact_committed_model_contract() -> None:
    spec = FROZEN_NFL_BASELINE_SPECIFICATION

    assert_frozen_nfl_baseline_specification()
    assert spec.target == "home_win"
    assert spec.training_seasons == tuple(range(2018, 2025))
    assert spec.holdout_season == 2025
    assert spec.minimum_history_per_team == FROZEN_NFL_MINIMUM_HISTORY == 3
    assert spec.feature_schema_version == NFL_MONEYLINE_FEATURE_SCHEMA_VERSION
    assert spec.feature_names == FROZEN_NFL_FEATURE_NAMES
    assert spec.feature_names == NFL_BASELINE_FEATURE_NAMES
    assert len(spec.feature_names) == 19
    assert (
        spec.regularization_c,
        spec.solver,
        spec.max_iterations,
        spec.random_state,
    ) == (1.0, "lbfgs", 5000, 42)
    assert spec.imputation == "training-row median"
    assert spec.scaling == "training-row StandardScaler"


def test_specification_drift_aborts_before_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        raise AssertionError("loader must not run after specification drift")

    monkeypatch.setattr(holdout_module, "NFL_BASELINE_RANDOM_STATE", 99)
    with pytest.raises(RuntimeError, match="random state"):
        run_guarded_final_nfl_holdout_evaluation(
            confirmed=True,
            development_loader=loader,
            holdout_loader=loader,
        )

    assert calls == 0


@pytest.mark.parametrize(
    ("attribute", "drifted_value", "message"),
    (
        (
            "NFL_MONEYLINE_FEATURE_SCHEMA_VERSION",
            "nfl_moneyline_changed",
            "feature schema",
        ),
        (
            "NFL_BASELINE_FEATURE_NAMES",
            tuple(reversed(NFL_BASELINE_FEATURE_NAMES)),
            "ordered feature representation",
        ),
        ("FROZEN_NFL_MINIMUM_HISTORY", 2, "minimum history"),
    ),
)
def test_schema_representation_and_minimum_history_drift_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    drifted_value: object,
    message: str,
) -> None:
    monkeypatch.setattr(holdout_module, attribute, drifted_value)

    with pytest.raises(RuntimeError, match=message):
        assert_frozen_nfl_baseline_specification()


def test_population_boundary_uses_nfl_season_not_calendar_year() -> None:
    training_game = _game(
        1, season=2024,
        kickoff=datetime(2025, 1, 12, 21, tzinfo=timezone.utc),
        season_type=NflSeasonType.POSTSEASON,
    )
    holdout_game = _game(
        2, season=2025,
        kickoff=datetime(2026, 1, 11, 21, tzinfo=timezone.utc),
        season_type=NflSeasonType.POSTSEASON,
    )

    training = build_nfl_moneyline_modeling_examples(
        (_row(training_game),), (training_game,),
    )
    holdout = build_nfl_moneyline_holdout_examples(
        (_row(holdout_game),), (holdout_game,),
    )

    assert training[0].season == 2024
    assert training[0].kickoff.year == 2025
    assert holdout[0].season == 2025
    assert holdout[0].kickoff.year == 2026


def test_population_validation_rejects_season_identity_drift() -> None:
    training, holdout = _synthetic_populations()
    wrong_training = (
        replace(training[0], season=2017),
        *training[1:],
    )
    wrong_holdout = (
        replace(holdout[0], season=2024),
        *holdout[1:],
    )

    with pytest.raises(ValueError, match="NFL seasons 2018-2024"):
        evaluate_frozen_nfl_moneyline_holdout(wrong_training, holdout)
    with pytest.raises(ValueError, match="NFL season 2025"):
        evaluate_frozen_nfl_moneyline_holdout(training, wrong_holdout)


def test_holdout_fit_uses_training_preprocessing_and_training_home_baseline() -> None:
    training, holdout = _synthetic_populations()

    evaluation = evaluate_frozen_nfl_moneyline_holdout(training, holdout)
    eligible_training = [
        item for item in training
        if item.home_prior_games >= 3 and item.away_prior_games >= 3
    ]
    training_values = [
        item.feature_values[1] for item in eligible_training
        if item.feature_values[1] is not None
    ]
    expected_median = median(training_values)
    expected_home_rate = sum(item.home_win for item in eligible_training) / len(
        eligible_training
    )

    assert evaluation.holdout_rows_available == len(holdout)
    assert evaluation.holdout_rows_excluded == 2
    assert evaluation.imputer_statistics[1] == pytest.approx(expected_median)
    assert evaluation.scaler_means[1] < 100.0
    assert evaluation.training_home_win_rate == pytest.approx(expected_home_rate)
    assert all(
        item.home_baseline_probability == pytest.approx(expected_home_rate)
        for item in evaluation.predictions
    )
    assert [item.game_id for item in evaluation.predictions] == [
        item.game_id for item in holdout
        if item.home_prior_games >= 3 and item.away_prior_games >= 3
    ]
    assert evaluation.home_baseline_metrics.roc_auc is None
    assert evaluation.paired_differences.accuracy == pytest.approx(
        evaluation.model_metrics.accuracy
        - evaluation.home_baseline_metrics.accuracy
    )


def test_holdout_path_fits_exactly_once_and_does_no_policy_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    training, holdout = _synthetic_populations()
    original_pipeline = holdout_module._pipeline
    fit_calls = 0

    class CountingPipeline:
        def __init__(self, delegate):
            self._delegate = delegate

        @property
        def named_steps(self):
            return self._delegate.named_steps

        def fit(self, *args, **kwargs):
            nonlocal fit_calls
            fit_calls += 1
            self._delegate.fit(*args, **kwargs)
            return self

        def predict_proba(self, *args, **kwargs):
            return self._delegate.predict_proba(*args, **kwargs)

    monkeypatch.setattr(
        holdout_module, "_pipeline",
        lambda regularization_c: CountingPipeline(
            original_pipeline(regularization_c)
        ),
    )

    evaluation = evaluate_frozen_nfl_moneyline_holdout(training, holdout)

    assert fit_calls == 1
    assert evaluation.training_rows_eligible < evaluation.training_rows_available
    assert evaluation.holdout_rows_eligible < evaluation.holdout_rows_available


def test_repeated_synthetic_holdout_evaluation_is_deterministic() -> None:
    training, holdout = _synthetic_populations()

    first = evaluate_frozen_nfl_moneyline_holdout(training, holdout)
    second = evaluate_frozen_nfl_moneyline_holdout(training, holdout)

    assert first == second
    assert first.report_fingerprint == second.report_fingerprint
    assert nfl_final_holdout_evaluation_to_dict(first) == (
        nfl_final_holdout_evaluation_to_dict(second)
    )
    assert first.confidence_intervals.roc_auc is not None
    assert first.paired_difference_intervals.roc_auc is None
    assert sum(item.prediction_count for item in first.calibration_bins) == (
        first.holdout_rows_eligible
    )


def _synthetic_populations() -> tuple[
    tuple[NflMoneylineModelingExample, ...],
    tuple[NflMoneylineModelingExample, ...],
]:
    training = []
    game_id = 1000
    for season in range(2018, 2025):
        for index in range(6):
            prior = 2 if index == 0 else 3 + index
            home_win = index % 2 == 0
            signal = 1.0 if home_win else -1.0
            values: list[float | None] = [float(prior)]
            values.extend(
                None if index == 1 and feature == 1 else signal * feature
                for feature in range(1, len(NFL_BASELINE_FEATURE_NAMES))
            )
            training.append(NflMoneylineModelingExample(
                game_id=game_id,
                kickoff=datetime(season, 9, 1, tzinfo=timezone.utc)
                + timedelta(days=index),
                season=season,
                season_type=NflSeasonType.REGULAR,
                home_win=home_win,
                home_prior_games=prior,
                away_prior_games=prior,
                feature_values=tuple(values),
            ))
            game_id += 1
    holdout = []
    for index in range(8):
        prior = 2 if index < 2 else index + 2
        home_win = index % 2 == 0
        signal = 10000.0 if home_win else -10000.0
        holdout.append(NflMoneylineModelingExample(
            game_id=game_id,
            kickoff=datetime(2025, 9, 1, tzinfo=timezone.utc)
            + timedelta(days=index),
            season=2025,
            season_type=NflSeasonType.REGULAR,
            home_win=home_win,
            home_prior_games=prior,
            away_prior_games=prior,
            feature_values=(float(prior), *(
                signal + feature
                for feature in range(1, len(NFL_BASELINE_FEATURE_NAMES))
            )),
        ))
        game_id += 1
    return tuple(training), tuple(holdout)


def _game(
    game_id: int,
    *,
    season: int,
    kickoff: datetime,
    season_type: NflSeasonType,
) -> NflGame:
    return NflGame(
        game_id=game_id,
        season=season,
        season_type=season_type,
        week=1,
        week_label="Postseason",
        scheduled_start_time=kickoff,
        home_team_id=10,
        away_team_id=20,
        status=NflGameStatus.FINAL,
        home_score=24,
        away_score=17,
        overtime=False,
        neutral_site=False,
    )


def _row(game: NflGame) -> dict[str, object]:
    row: dict[str, object] = {
        "target_game_id": game.game_id,
        "target_kickoff": game.scheduled_start_time,
        "feature_schema_version": NFL_MONEYLINE_FEATURE_SCHEMA_VERSION,
        "home_prior_games_used": 3,
        "away_prior_games_used": 3,
        "home_win": True,
    }
    for name in NFL_BASELINE_FEATURE_NAMES[1:]:
        suffix = name.removeprefix("matchup_").removesuffix("_difference")
        if suffix == "prior_games_used":
            continue
        row[f"home_{suffix}"] = 2.0
        row[f"away_{suffix}"] = 1.0
    return row
