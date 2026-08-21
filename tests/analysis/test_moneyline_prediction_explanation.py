from datetime import datetime, timezone
from decimal import Decimal
from math import exp, isclose
from types import SimpleNamespace

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from sportsmodel.analysis import moneyline_prediction_explanation as explanation
from sportsmodel.training.matchup_features import (
    MatchupFeatureTransformer,
    TrainedMatchupMoneylineModel,
)
from sportsmodel.training.moneyline_baseline import TrainedMoneylineBaseline


RAW_FEATURE_NAMES = (
    "home_batting_metric",
    "away_batting_metric",
    "home_pitching_metric",
    "away_pitching_metric",
    "home_bullpen_metric",
    "away_bullpen_metric",
    "home_starting_pitcher_metric",
    "away_starting_pitcher_metric",
    "park_factor",
)


def test_contributions_exactly_reconstruct_pipeline_logit() -> None:
    model = _model()
    raw = _raw_features()

    result = explanation.calculate_moneyline_contributions(model, raw)

    transformed = model.transformer.transform_values(
        tuple(None if raw[name] is None else float(raw[name]) for name in RAW_FEATURE_NAMES)
    )
    active = [np.nan if value is None else value for value in transformed]
    imputer = model.model.pipeline.named_steps["imputer"]
    scaler = model.model.pipeline.named_steps["scaler"]
    classifier = model.model.pipeline.named_steps["classifier"]
    imputed = imputer.transform([active])
    standardized = scaler.transform(imputed)
    expected_contributions = standardized[0] * classifier.coef_[0]
    expected_logit = float(classifier.intercept_[0] + expected_contributions.sum())
    expected_probability = 1.0 / (1.0 + exp(-expected_logit))

    assert np.allclose(
        [item.contribution for item in result.contributions],
        expected_contributions,
        atol=1e-15,
    )
    assert isclose(result.feature_logit_total, float(expected_contributions.sum()), abs_tol=1e-15)
    assert isclose(result.final_logit, expected_logit, abs_tol=1e-15)
    assert isclose(
        result.reconstructed_home_win_probability,
        expected_probability,
        abs_tol=1e-15,
    )


def test_missing_indicator_is_included_and_categorized() -> None:
    result = explanation.calculate_moneyline_contributions(
        _model(),
        _raw_features(),
    )

    assert result.transformed_missing_feature_names == (
        "matchup_starting_pitcher_metric_difference",
    )
    indicators = tuple(
        item for item in result.contributions if item.is_missing_indicator
    )
    assert len(indicators) == 1
    assert indicators[0].feature_name == (
        "missingindicator_matchup_starting_pitcher_metric_difference"
    )
    assert indicators[0].imputed_value == 1.0
    assert indicators[0].category == "starting_pitcher"


def test_direction_and_category_aggregation_cover_every_contribution() -> None:
    result = explanation.calculate_moneyline_contributions(
        _model(),
        _raw_features(),
    )
    totals = dict(result.category_totals)

    assert explanation.categorize_moneyline_feature(
        "matchup_batting_metric_difference"
    ) == "batting"
    assert explanation.categorize_moneyline_feature(
        "matchup_pitching_metric_difference"
    ) == "team_pitching"
    assert explanation.categorize_moneyline_feature(
        "matchup_bullpen_metric_difference"
    ) == "bullpen"
    assert explanation.categorize_moneyline_feature(
        "missingindicator_matchup_starting_pitcher_metric_difference"
    ) == "starting_pitcher"
    assert explanation.categorize_moneyline_feature("park_factor") == "other"
    assert set(totals) == set(explanation.CONTRIBUTION_CATEGORIES)
    assert isclose(sum(totals.values()), result.feature_logit_total, abs_tol=1e-15)


def test_probability_mismatch_marks_reconstruction_non_authoritative(
    monkeypatch,
) -> None:
    model = _model()
    raw = _raw_features()
    reconstructed = model.predict_home_win_probability(raw)
    stored = _stored_prediction(
        stored_probability=Decimal(str(reconstructed + 0.01))
    )
    monkeypatch.setattr(
        explanation,
        "_load_stored_prediction",
        lambda **arguments: stored,
    )
    monkeypatch.setattr(
        explanation,
        "_load_and_validate_associated_model",
        lambda **arguments: SimpleNamespace(model=model),
    )
    monkeypatch.setattr(
        explanation,
        "flatten_game_feature_vector",
        lambda vector: raw,
    )
    feature_service = SimpleNamespace(
        generate_for_game_record=lambda **arguments: SimpleNamespace(
            feature_schema_version="test-schema"
        )
    )

    result = explanation.explain_moneyline_prediction(
        prediction_id=429,
        feature_generation_service=feature_service,
    )

    assert result.authoritative is False
    assert abs(result.probability_delta) > result.reconstruction_tolerance
    assert result.contributions


def _model() -> TrainedMatchupMoneylineModel:
    transformer = MatchupFeatureTransformer.from_feature_names(RAW_FEATURE_NAMES)
    active_names = transformer.output_feature_names
    training_matrix = [
        [1.0, -1.0, 0.5, np.nan, 0.1],
        [-1.0, 1.0, -0.5, 0.4, -0.1],
        [0.5, 0.2, 1.0, 0.8, 0.3],
        [-0.5, -0.2, -1.0, np.nan, -0.3],
        [1.5, -0.8, 0.2, 0.1, 0.2],
        [-1.5, 0.8, -0.2, -0.1, -0.2],
    ]
    pipeline = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(strategy="median", add_indicator=True),
            ),
            ("scaler", StandardScaler()),
            (
                "classifier",
                LogisticRegression(solver="lbfgs", random_state=42),
            ),
        ]
    )
    pipeline.fit(training_matrix, [True, False, True, False, True, False])
    baseline = TrainedMoneylineBaseline(
        feature_schema_version="test-schema",
        active_feature_names=active_names,
        dropped_all_missing_features=(),
        dropped_constant_features=(),
        dropped_duplicate_features=(),
        regularization_c=1.0,
        training_rows=len(training_matrix),
        training_end_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        pipeline=pipeline,
    )
    return TrainedMatchupMoneylineModel(
        transformer=transformer,
        model=baseline,
    )


def _raw_features() -> dict[str, float | None]:
    return {
        "home_batting_metric": 3.0,
        "away_batting_metric": 1.0,
        "home_pitching_metric": 1.0,
        "away_pitching_metric": 2.0,
        "home_bullpen_metric": 2.5,
        "away_bullpen_metric": 2.0,
        "home_starting_pitcher_metric": None,
        "away_starting_pitcher_metric": 2.0,
        "park_factor": 0.25,
    }


def _stored_prediction(
    *,
    stored_probability: Decimal,
) -> explanation.StoredMoneylinePredictionExplanationInput:
    return explanation.StoredMoneylinePredictionExplanationInput(
        prediction_id=429,
        prediction_run_id=42,
        game_id=824072,
        mlb_game_id=824072,
        game_start_time=datetime(2026, 8, 21, 2, tzinfo=timezone.utc),
        prediction_time=datetime(2026, 8, 21, 1, 45, tzinfo=timezone.utc),
        home_team_id=10,
        away_team_id=20,
        home_team_name="Home Club",
        away_team_name="Away Club",
        home_starting_pitcher_id=730,
        away_starting_pitcher_id=438,
        home_starting_pitcher_mlb_id=702070,
        away_starting_pitcher_mlb_id=675512,
        home_starting_pitcher_name="Home Pitcher",
        away_starting_pitcher_name="Away Pitcher",
        persisted_missing_raw_value_count=1,
        stored_home_win_probability=stored_probability,
        model_version="test-model",
        feature_schema_version="test-schema",
        model_artifact_sha256="a" * 64,
        model_training_cutoff=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
