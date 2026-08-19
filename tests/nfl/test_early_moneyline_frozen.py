import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import pytest

from sportsmodel.nfl.early_features import (
    NFL_EARLY_MONEYLINE_FEATURE_NAMES,
    NFLMoneylineRoute,
)
from sportsmodel.nfl.early_moneyline_baseline import (
    NFLEarlyMoneylineModelingExample,
)
from sportsmodel.nfl.early_moneyline_frozen import (
    FROZEN_NFL_EARLY_EVIDENCE_NOTICE,
    FROZEN_NFL_EARLY_FEATURE_NAMES,
    FROZEN_NFL_EARLY_NEXT_FORWARD_SEASON,
    FROZEN_NFL_EARLY_RETROSPECTIVE_LABEL,
    FROZEN_NFL_EARLY_SPECIFICATION,
    FROZEN_NFL_EARLY_SPECIFICATION_VERSION,
    FROZEN_NFL_FORWARD_EVALUATION_PROTOCOL,
    assert_committed_frozen_nfl_early_artifact,
    assert_frozen_nfl_early_specification,
    fit_frozen_nfl_early_candidate,
    frozen_nfl_early_artifact_to_dict,
    frozen_nfl_early_specification_fingerprint,
    predict_frozen_nfl_early_home_win_probability,
    select_frozen_nfl_moneyline_route,
)
from sportsmodel.nfl.moneyline_holdout import (
    FROZEN_NFL_BASELINE_SPECIFICATION,
    FROZEN_NFL_BASELINE_SPECIFICATION_VERSION,
    assert_frozen_nfl_baseline_specification,
)


ARTIFACT_PATH = Path("artifacts/nfl_moneyline_early_frozen_0.1.0.json")


def test_exact_frozen_four_feature_contract_and_specification() -> None:
    assert_frozen_nfl_early_specification()
    spec = FROZEN_NFL_EARLY_SPECIFICATION

    assert spec.specification_version == "nfl_moneyline_early_frozen_0.1.0"
    assert spec.feature_names == (
        "prior_season_games_played_difference",
        "prior_season_win_percentage_difference",
        "prior_season_average_point_differential_difference",
        "prior_season_average_turnover_differential_difference",
    )
    assert spec.feature_names == FROZEN_NFL_EARLY_FEATURE_NAMES
    assert spec.regularization_c == 1.0
    assert spec.solver == "lbfgs"
    assert spec.max_iterations == 5000
    assert spec.random_state == 42
    assert spec.training_seasons == tuple(range(2019, 2025))
    assert frozen_nfl_early_specification_fingerprint() == (
        "109d8bf693f67836d0acd39a631a50dccfdfaea61284aa9ef09349f2b71b9675"
    )


def test_current_features_and_neutral_site_do_not_enter_learned_x() -> None:
    original_examples = _examples()
    original = _fit(original_examples)
    changed = tuple(
        replace(
            item,
            minimum_current_prior_games=2 - item.minimum_current_prior_games,
            neutral_site=not item.neutral_site,
            feature_values=(
                *item.feature_values[:4],
                *tuple(
                    None if value is None else value + 5000
                    for value in item.feature_values[4:10]
                ),
                1.0 - item.feature_values[10],
            ),
        )
        for item in original_examples
    )
    refit = _fit(changed)

    assert original.coefficients == refit.coefficients
    assert original.intercept == refit.intercept
    assert original.imputer_statistics == refit.imputer_statistics
    assert original.scaler_means == refit.scaler_means
    assert original.feature_names == FROZEN_NFL_EARLY_FEATURE_NAMES
    assert set(original.feature_names).isdisjoint({
        name for name in NFL_EARLY_MONEYLINE_FEATURE_NAMES
        if name.startswith("current_season_")
    })
    assert "minimum_current_season_prior_games" not in original.feature_names
    assert "neutral_site" not in original.feature_names
    assert changed[0].neutral_site is not original_examples[0].neutral_site


@pytest.mark.parametrize(
    ("home_count", "away_count", "route", "model"),
    [
        (0, 0, NFLMoneylineRoute.EARLY, FROZEN_NFL_EARLY_SPECIFICATION_VERSION),
        (1, 1, NFLMoneylineRoute.EARLY, FROZEN_NFL_EARLY_SPECIFICATION_VERSION),
        (2, 2, NFLMoneylineRoute.EARLY, FROZEN_NFL_EARLY_SPECIFICATION_VERSION),
        (4, 2, NFLMoneylineRoute.EARLY, FROZEN_NFL_EARLY_SPECIFICATION_VERSION),
        (2, 4, NFLMoneylineRoute.EARLY, FROZEN_NFL_EARLY_SPECIFICATION_VERSION),
        (3, 3, NFLMoneylineRoute.MATURE, FROZEN_NFL_BASELINE_SPECIFICATION_VERSION),
        (4, 3, NFLMoneylineRoute.MATURE, FROZEN_NFL_BASELINE_SPECIFICATION_VERSION),
    ],
)
def test_frozen_routing_contract(home_count, away_count, route, model) -> None:
    decision = select_frozen_nfl_moneyline_route(home_count, away_count)

    assert decision.route is route
    assert decision.model_specification_version == model
    assert decision.home_current_prior_games == home_count
    assert decision.away_current_prior_games == away_count


def test_training_population_requires_every_season_2019_through_2024_only() -> None:
    examples = _examples()
    artifact = _fit(examples)

    assert artifact.training_seasons == (2019, 2020, 2021, 2022, 2023, 2024)
    assert artifact.training_row_count == 24

    without_2019 = tuple(item for item in examples if item.season != 2019)
    with pytest.raises(ValueError, match="2019-2024 only"):
        _fit(without_2019)
    with pytest.raises(ValueError, match="2019-2024 only"):
        _fit((*examples, replace(
            examples[-1], game_id=999, season=2025,
            kickoff=datetime(2025, 9, 1, tzinfo=timezone.utc),
        )))
    with pytest.raises(ValueError, match="2019-2024 only"):
        _fit((replace(
            examples[0], game_id=998, season=2018,
            kickoff=datetime(2018, 9, 1, tzinfo=timezone.utc),
        ), *examples))


def test_preprocessing_statistics_are_fit_from_training_rows() -> None:
    examples = _examples()
    artifact = _fit(examples)
    nonmissing = [
        item.feature_values[1]
        for item in examples
        if item.feature_values[1] is not None
    ]

    assert artifact.imputer_statistics[1] == median(nonmissing)
    assert len(artifact.imputer_statistics) == 4
    assert len(artifact.scaler_means) == 4
    assert len(artifact.scaler_scales) == 4
    assert len(artifact.coefficients) == 4


def test_repeated_fit_and_metadata_inference_are_deterministic() -> None:
    first = _fit(_examples())
    second = _fit(_examples())

    assert first == second
    assert first.model_fingerprint == second.model_fingerprint
    probability = predict_frozen_nfl_early_home_win_probability(
        first,
        (0.0, None, 1.5, -0.25),
    )
    assert probability == predict_frozen_nfl_early_home_win_probability(
        second,
        (0.0, None, 1.5, -0.25),
    )
    assert 0 < probability < 1


def test_committed_artifact_has_required_evidence_and_matches_known_fit_metadata() -> None:
    committed = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    assert committed["specification_version"] == (
        FROZEN_NFL_EARLY_SPECIFICATION_VERSION
    )
    assert committed["training_row_count"] == 285
    assert committed["training_seasons"] == list(range(2019, 2025))
    assert committed["feature_names"] == list(FROZEN_NFL_EARLY_FEATURE_NAMES)
    assert committed["regularization_c"] == 1.0
    assert committed["solver"] == "lbfgs"
    assert committed["max_iterations"] == 5000
    assert committed["random_state"] == 42
    assert committed["classification_threshold"] == 0.5
    assert committed["historical_evidence_status"] == (
        FROZEN_NFL_EARLY_EVIDENCE_NOTICE
    )
    assert committed["next_forward_evidence_season"] == 2026
    assert committed["retrospective_status"] == (
        FROZEN_NFL_EARLY_RETROSPECTIVE_LABEL
    )
    assert "holdout" not in committed["retrospective_status"].lower()
    assert "confirmation" not in committed["retrospective_status"].lower()


def test_committed_artifact_comparison_rejects_drift() -> None:
    artifact = _fit(_examples())
    committed = frozen_nfl_early_artifact_to_dict(artifact)
    assert_committed_frozen_nfl_early_artifact(artifact, committed)
    committed["intercept"] += 1

    with pytest.raises(RuntimeError, match="differs"):
        assert_committed_frozen_nfl_early_artifact(artifact, committed)


def test_forward_protocol_is_frozen_before_2026_results() -> None:
    protocol = FROZEN_NFL_FORWARD_EVALUATION_PROTOCOL

    assert protocol.first_forward_season == FROZEN_NFL_EARLY_NEXT_FORWARD_SEASON
    assert protocol.early_history_states == (0, 1, 2)
    assert set(("early", "mature")).issubset(protocol.required_route_breakouts)
    assert {
        "game_id",
        "target_kickoff",
        "home_current_prior_games",
        "away_current_prior_games",
        "route",
        "model_specification_version",
        "feature_schema_version",
        "feature_cutoff",
        "model_home_win_probability",
        "actual_result",
        "target_tied",
        "prediction_timestamp",
        "prediction_run_id",
    }.issubset(protocol.prediction_record_fields)
    assert "log_loss" in protocol.primary_probability_metrics
    assert any("before target outcomes" in rule for rule in protocol.evidence_rules)
    assert any("Do not tune" in rule for rule in protocol.evidence_rules)


def test_mature_phase2_frozen_specification_is_unchanged() -> None:
    assert_frozen_nfl_baseline_specification()

    assert FROZEN_NFL_BASELINE_SPECIFICATION.specification_version == (
        "nfl_moneyline_frozen_0.1.0"
    )
    assert len(FROZEN_NFL_BASELINE_SPECIFICATION.feature_names) == 19


def _fit(examples):
    return fit_frozen_nfl_early_candidate(
        examples,
        dataset_fingerprint="synthetic-dataset",
    )


def _examples() -> tuple[NFLEarlyMoneylineModelingExample, ...]:
    result = []
    game_id = 1
    for season in range(2019, 2025):
        start = datetime(season, 9, 1, tzinfo=timezone.utc)
        for index in range(4):
            prior_win = None if index == 0 else (index - 1) / 5
            result.append(NFLEarlyMoneylineModelingExample(
                game_id=game_id,
                kickoff=start + timedelta(days=index),
                season=season,
                home_win=index % 2 == season % 2,
                minimum_current_prior_games=index % 3,
                neutral_site=index == 3,
                feature_values=(
                    float(index - 1),
                    prior_win,
                    float((index - 2) * 3),
                    float((index % 3) - 1),
                    float(index - 2),
                    None if index == 0 else index / 10,
                    None if index == 0 else 20 + index,
                    None if index == 0 else 18 - index,
                    None if index == 0 else float(index - 1),
                    float(index % 3),
                    float(index == 3),
                ),
            ))
            game_id += 1
    return tuple(result)
