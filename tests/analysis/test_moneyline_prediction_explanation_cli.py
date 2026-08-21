from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sportsmodel.analysis import moneyline_prediction_explanation_cli as cli


def test_non_authoritative_output_omits_rankings_and_labels_warning(
    capsys,
) -> None:
    explanation = type("Explanation", (), {})()
    explanation.prediction = SimpleNamespace(
        prediction_id=429,
        prediction_run_id=34,
        away_team_name="Away Club",
        home_team_name="Home Club",
        away_team_id=20,
        home_team_id=10,
        game_id=8379,
        mlb_game_id=824072,
        prediction_time=datetime(2026, 8, 21, 1, 45, tzinfo=timezone.utc),
        game_start_time=datetime(2026, 8, 22, 0, 10, tzinfo=timezone.utc),
        home_starting_pitcher_name="Home Pitcher",
        away_starting_pitcher_name="Away Pitcher",
        home_starting_pitcher_id=730,
        away_starting_pitcher_id=438,
        home_starting_pitcher_mlb_id=702070,
        away_starting_pitcher_mlb_id=675512,
        model_version="test-model",
        feature_schema_version="test-schema",
        model_artifact_sha256="a" * 64,
        model_training_cutoff=datetime(2026, 7, 1, tzinfo=timezone.utc),
        stored_home_win_probability=0.50,
        persisted_missing_raw_value_count=1,
    )
    explanation.authoritative = False
    explanation.reconstruction_tolerance = 1e-9
    explanation.probability_delta = 0.01
    explanation.raw_feature_count = 108
    explanation.raw_missing_feature_names = ("home_example",)
    explanation.transformed_missing_feature_names = ("matchup_example",)
    explanation.regenerated_missing_raw_value_count = 1
    explanation.reconstructed_home_win_probability = 0.51

    cli.print_explanation(explanation)

    output = capsys.readouterr().out
    assert "NON-AUTHORITATIVE RECONSTRUCTION" in output
    assert "contribution rankings are not shown" in output
    assert "TOP 15 TOWARD" not in output


def test_direction_labels_use_matchup_team_names() -> None:
    assert cli._direction_text(
        0.1,
        home_name="Home Club",
        away_name="Away Club",
    ) == "toward Home Club"
    assert cli._direction_text(
        -0.1,
        home_name="Home Club",
        away_name="Away Club",
    ) == "toward Away Club"


def test_parser_requires_positive_integer_prediction_id() -> None:
    parser = cli.build_parser()

    assert parser.parse_args(["--prediction-id", "429"]).prediction_id == 429
    for invalid in ("0", "-1", "not-an-integer"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--prediction-id", invalid])
    with pytest.raises(SystemExit):
        parser.parse_args([])
