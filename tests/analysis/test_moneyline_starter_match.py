import pytest

from sportsmodel.analysis.moneyline_starter_match import classify_starter_match


@pytest.mark.parametrize(
    ("predicted", "current", "status", "reason"),
    [
        ((10, 20), (10, 20), "matched", None),
        ((10, 20), (11, 20), "changed", "starter_changed_home"),
        ((10, 20), (10, 21), "changed", "starter_changed_away"),
        ((10, 20), (11, 21), "changed", "starter_changed_both"),
        ((10, 20), (None, 20), "unavailable", "starter_unavailable_home"),
        ((10, 20), (10, None), "unavailable", "starter_unavailable_away"),
        ((10, 20), (None, None), "unavailable", "starter_unavailable_both"),
        ((None, 20), (10, 20), "unavailable", "starter_unavailable_home"),
        ((None, None), (None, None), "unavailable", "starter_unavailable_both"),
    ],
)
def test_classifies_canonical_mlb_ids(
    predicted, current, status, reason
) -> None:
    result = classify_starter_match(
        predicted_home_mlb_id=predicted[0],
        predicted_away_mlb_id=predicted[1],
        current_home_mlb_id=current[0],
        current_away_mlb_id=current[1],
    )

    assert result.status == status
    assert result.reason == reason


def test_twins_braves_changed_away_preserves_prediction_values() -> None:
    probability = "0.5476526844"
    predicted = (671737, 700363)

    result = classify_starter_match(
        predicted_home_mlb_id=predicted[0],
        predicted_away_mlb_id=predicted[1],
        current_home_mlb_id=671737,
        current_away_mlb_id=999999,
    )

    assert result.status == "changed"
    assert result.reason == "starter_changed_away"
    assert probability == "0.5476526844"
    assert predicted == (671737, 700363)
