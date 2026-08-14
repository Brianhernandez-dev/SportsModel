from types import SimpleNamespace

import pytest

from sportsmodel.analysis.moneyline_overnight_review import (
    MODEL_LEAN_CHANGED,
    NEW_MORNING_VALUE,
    NO_VALUE,
    STILL_POLICY_BLOCKED,
    SURVIVED_TO_MORNING,
    VALUE_LOST_OVERNIGHT,
    build_moneyline_overnight_review,
    classify_moneyline_overnight_status,
)


@pytest.mark.parametrize(
    (
        "late_selection",
        "official_selection",
        "late_pass",
        "official_pass",
        "late_signal",
        "expected",
    ),
    (
        (
            "Minnesota Twins",
            "Minnesota Twins",
            True,
            True,
            True,
            SURVIVED_TO_MORNING,
        ),
        (
            "Minnesota Twins",
            "Minnesota Twins",
            True,
            False,
            True,
            VALUE_LOST_OVERNIGHT,
        ),
        (
            "Minnesota Twins",
            "Minnesota Twins",
            False,
            True,
            False,
            NEW_MORNING_VALUE,
        ),
        (
            "Minnesota Twins",
            "Baltimore Orioles",
            True,
            False,
            True,
            MODEL_LEAN_CHANGED,
        ),
        (
            "Minnesota Twins",
            "Minnesota Twins",
            False,
            False,
            True,
            STILL_POLICY_BLOCKED,
        ),
        (
            "Minnesota Twins",
            "Minnesota Twins",
            False,
            False,
            False,
            NO_VALUE,
        ),
    ),
)
def test_classifies_overnight_status(
    late_selection,
    official_selection,
    late_pass,
    official_pass,
    late_signal,
    expected,
):
    assert (
        classify_moneyline_overnight_status(
            late_night_selection_name=(
                late_selection
            ),
            official_selection_name=(
                official_selection
            ),
            late_night_policy_pass=late_pass,
            official_policy_pass=(
                official_pass
            ),
            late_night_value_signal=(
                late_signal
            ),
        )
        == expected
    )


def test_builds_value_lost_overnight_row():
    late = SimpleNamespace(
        game_id=1,
        game_start_time=None,
        away_team_name="Baltimore Orioles",
        home_team_name="Minnesota Twins",
        predicted_team_name="Minnesota Twins",
        model_probability=0.5326,
        price=-102,
        sportsbook_name="Book A",
        model_expected_value=0.0547,
        model_market_edge=0.0393,
        preview_policy_pass=True,
        preview_value_signal=True,
    )

    official = SimpleNamespace(
        game_id=1,
        game_start_time=None,
        away_team_name="Baltimore Orioles",
        home_team_name="Minnesota Twins",
        predicted_team_name="Minnesota Twins",
        model_probability=0.5100,
        price=-112,
        sportsbook_name="Book B",
        model_expected_value=-0.0481,
        model_market_edge=-0.0132,
        qualifies_as_paper_candidate=False,
        disqualification_reasons=(
            "model_expected_value_below_minimum",
            "model_market_edge_below_minimum",
        ),
    )

    review = build_moneyline_overnight_review(
        late_night_games=(late,),
        official_games=(official,),
    )

    assert len(review) == 1

    row = review[0]

    assert row.status == VALUE_LOST_OVERNIGHT
    assert row.late_night_price == -102
    assert row.official_price == -112
    assert row.late_night_policy_pass is True
    assert row.official_policy_pass is False
