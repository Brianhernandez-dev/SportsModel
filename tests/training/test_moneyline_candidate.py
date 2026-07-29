from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from sportsmodel.training import (
    MoneylineTrainingDataset,
    MoneylineTrainingExample,
    build_moneyline_candidate,
    load_trained_matchup_moneyline_model,
)


def build_dataset() -> MoneylineTrainingDataset:
    start_time = datetime(
        2026,
        4,
        1,
        17,
        0,
        tzinfo=timezone.utc,
    )

    examples = tuple(
        MoneylineTrainingExample(
            game_id=index + 1,
            game_start_time=(
                start_time
                + timedelta(days=index)
            ),
            home_team_won=(
                index in {
                    2,
                    4,
                    5,
                }
            ),
            feature_values=(
                float(index + 2),
                float(index % 3),
                1.0,
                1.0,
            ),
        )
        for index in range(6)
    )

    return MoneylineTrainingDataset(
        feature_schema_version="1.2.0",
        feature_names=(
            "home_example_metric",
            "away_example_metric",
            "home_constant_metric",
            "away_constant_metric",
        ),
        examples=examples,
    )


def test_build_moneyline_candidate(
    tmp_path: Path,
) -> None:
    evaluation_path = (
        tmp_path / "walk_forward.json"
    )
    evaluation_path.write_text(
        json.dumps(
            {
                "experiment": "walk_forward",
                "folds": 3,
            }
        ),
        encoding="utf-8",
    )

    output_directory = (
        tmp_path / "candidate"
    )

    result = build_moneyline_candidate(
        build_dataset(),
        model_version="test_moneyline_v1",
        regularization_c=0.001,
        output_directory=output_directory,
        evaluation_report_path=(
            evaluation_path
        ),
        expected_feature_schema_version="1.2.0",
        git_commit="test-commit",
    )

    assert result.training_rows == 6
    assert result.model_path.exists()
    assert result.manifest_path.exists()
    assert result.evaluation_path.exists()
    assert (
        result.evaluation_path.read_bytes()
        == evaluation_path.read_bytes()
    )

    manifest = json.loads(
        result.manifest_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        manifest["model_version"]
        == "test_moneyline_v1"
    )
    assert manifest["git_commit"] == "test-commit"
    assert (
        manifest["feature_schema_version"]
        == "1.2.0"
    )
    assert (
        manifest["training"]["rows"]
        == 6
    )
    assert (
        manifest["features"]["raw_feature_count"]
        == 4
    )
    assert (
        manifest["features"][
            "matchup_feature_count"
        ]
        == 2
    )

    loaded_model = (
        load_trained_matchup_moneyline_model(
            result.model_path
        )
    )

    probability = (
        loaded_model.predict_home_win_probability(
            {
                "home_example_metric": 8.0,
                "away_example_metric": 4.0,
                "home_constant_metric": 1.0,
                "away_constant_metric": 1.0,
            }
        )
    )

    assert 0.0 <= probability <= 1.0


def test_build_moneyline_candidate_rejects_schema_mismatch(
    tmp_path: Path,
) -> None:
    evaluation_path = (
        tmp_path / "walk_forward.json"
    )
    evaluation_path.write_text(
        "{}",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="feature schema",
    ):
        build_moneyline_candidate(
            build_dataset(),
            model_version="test",
            regularization_c=0.001,
            output_directory=(
                tmp_path / "candidate"
            ),
            evaluation_report_path=(
                evaluation_path
            ),
            expected_feature_schema_version="9.9.9",
            git_commit="test-commit",
        )
