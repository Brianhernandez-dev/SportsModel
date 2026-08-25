from decimal import Decimal
from types import SimpleNamespace

import pytest

from sportsmodel.analysis.moneyline_prediction_explanation import (
    MoneylineFeatureContribution,
)
from sportsmodel.dashboard.moneyline_prediction_explanation_presenter import (
    humanize_moneyline_feature_name,
    present_moneyline_prediction_explanation,
)


def test_authoritative_home_selection_uses_supplied_category_directions() -> None:
    presentation = present_moneyline_prediction_explanation(
        _explanation(predicted_team_id=10),
    )

    assert presentation.authoritative is True
    assert [
        (lean.label, lean.direction_team_name, lean.total)
        for lean in presentation.category_leans
    ] == [
        ("Starting pitcher", "Home Club", 0.2),
        ("Batting", "Away Club", -0.1),
        ("Team pitching", None, 0.00001),
        ("Bullpen", "Away Club", -0.2),
    ]
    assert presentation.category_leans[2].direction == "neutral"
    assert [reason.feature_name for reason in presentation.selected_team_reasons] == [
        "matchup_batting_alpha_difference",
        "matchup_batting_beta_difference",
    ]
    assert presentation.selected_team_reasons[0].contribution == 0.3


def test_away_selection_reverses_selected_and_opponent_rankings() -> None:
    presentation = present_moneyline_prediction_explanation(
        _explanation(predicted_team_id=20),
    )

    assert presentation.selected_team_name == "Away Club"
    assert presentation.opponent_team_name == "Home Club"
    assert [reason.contribution for reason in presentation.selected_team_reasons] == [
        -0.4,
        -0.2,
    ]
    assert [reason.contribution for reason in presentation.opponent_reasons] == [
        0.3,
        0.3,
    ]


def test_top_n_validation_and_tie_breaking_are_deterministic() -> None:
    explanation = _explanation(predicted_team_id=10)

    first = present_moneyline_prediction_explanation(explanation, top_n=1)
    second = present_moneyline_prediction_explanation(explanation, top_n=1)

    assert first.selected_team_reasons == second.selected_team_reasons
    assert first.selected_team_reasons[0].feature_name.endswith("alpha_difference")
    with pytest.raises(ValueError, match="between 1 and 5"):
        present_moneyline_prediction_explanation(explanation, top_n=6)


def test_non_authoritative_result_fails_closed() -> None:
    presentation = present_moneyline_prediction_explanation(
        _explanation(predicted_team_id=10, authoritative=False),
    )

    assert presentation.authoritative is False
    assert "rankings are withheld" in presentation.authority_message
    assert presentation.category_leans == ()
    assert presentation.selected_team_reasons == ()
    assert presentation.opponent_reasons == ()
    assert presentation.advanced_feature_rows == ()


def test_missing_input_messages_distinguish_active_from_inactive() -> None:
    inactive = present_moneyline_prediction_explanation(
        _explanation(predicted_team_id=10),
    )
    active = present_moneyline_prediction_explanation(
        _explanation(
            predicted_team_id=10,
            active_missing=("matchup_starting_pitcher_whip_last_5_difference",),
            inactive_missing=(),
        ),
    )

    assert inactive.active_input_message == "Active model inputs: Complete."
    assert inactive.inactive_input_message == (
        "2 unavailable raw fields were inactive and did not affect this prediction."
    )
    assert active.active_input_message == (
        "Active model inputs: 1 unavailable input was handled by the frozen "
        "production model's imputation pipeline."
    )
    assert active.inactive_input_message is None


def test_feature_labels_are_readable_and_intercept_is_neutral() -> None:
    indicator = humanize_moneyline_feature_name(
        "missingindicator_matchup_starting_pitcher_whip_last_5_difference"
    )
    presentation = present_moneyline_prediction_explanation(
        _explanation(predicted_team_id=10),
    )

    assert indicator == (
        "Starting pitcher WHIP last 5 (missing-data indicator)"
    )
    assert presentation.intercept_label == "Model intercept"
    assert "home-field advantage" not in presentation.intercept_label.lower()
    assert "hfa" not in presentation.intercept_label.lower()


def _explanation(
    *,
    predicted_team_id: int,
    authoritative: bool = True,
    active_missing: tuple[str, ...] = (),
    inactive_missing: tuple[str, ...] = (
        "matchup_schedule_days_since_previous_game_difference",
    ),
):
    predicted_home = predicted_team_id == 10
    prediction = SimpleNamespace(
        home_team_id=10,
        away_team_id=20,
        home_team_name="Home Club",
        away_team_name="Away Club",
        predicted_team_id=predicted_team_id,
        predicted_team_name="Home Club" if predicted_home else "Away Club",
        opponent_team_name="Away Club" if predicted_home else "Home Club",
        stored_predicted_probability=Decimal("0.53"),
    )
    contributions = (
        _contribution("matchup_batting_beta_difference", 0.3, "batting"),
        _contribution("matchup_batting_alpha_difference", 0.3, "batting"),
        _contribution("matchup_pitching_whip_last_10_difference", -0.4, "team_pitching"),
        _contribution("matchup_bullpen_walks_difference", -0.2, "bullpen"),
    )
    return SimpleNamespace(
        prediction=prediction,
        authoritative=authoritative,
        active_missing_feature_names=active_missing,
        inactive_missing_feature_names=inactive_missing,
        raw_missing_feature_names=(
            "home_schedule_days_since_previous_game",
            "away_schedule_days_since_previous_game",
        ),
        category_totals=(
            ("batting", -0.1),
            ("team_pitching", 0.00001),
            ("bullpen", -0.2),
            ("starting_pitcher", 0.2),
            ("other", 0.0),
        ),
        contributions=contributions,
    )


def _contribution(
    name: str,
    value: float,
    category: str,
) -> MoneylineFeatureContribution:
    return MoneylineFeatureContribution(
        feature_name=name,
        category=category,
        imputed_value=1.0,
        standardized_value=2.0,
        coefficient=value / 2,
        contribution=value,
        is_missing_indicator=name.startswith("missingindicator_"),
    )
