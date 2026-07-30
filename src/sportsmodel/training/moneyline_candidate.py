from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any

import sklearn

from sportsmodel.training.matchup_features import (
    MATCHUP_FEATURE_TRANSFORM_VERSION,
    MATCHUP_MODEL_ARTIFACT_FORMAT_VERSION,
    TrainedMatchupMoneylineModel,
    load_trained_matchup_moneyline_model,
    save_trained_matchup_moneyline_model,
    transform_to_matchup_difference_dataset,
)
from sportsmodel.training.moneyline_baseline import (
    MODEL_ARTIFACT_FORMAT_VERSION,
    MoneylineTrainingDataset,
    fit_moneyline_baseline,
)


@dataclass(frozen=True)
class MoneylineCandidateBuildResult:
    """
    Files and smoke-test details for one candidate build.
    """

    model_path: Path

    manifest_path: Path

    evaluation_path: Path

    training_rows: int

    smoke_game_id: int

    smoke_home_win_probability: float


def build_moneyline_candidate(
    dataset: MoneylineTrainingDataset,
    *,
    model_version: str,
    regularization_c: float,
    output_directory: Path,
    evaluation_report_path: Path,
    expected_feature_schema_version: str,
    source_dataset_path: Path | None = None,
    git_commit: str | None = None,
) -> MoneylineCandidateBuildResult:
    """
    Fit, persist, reload, and document a forward Moneyline candidate.
    """

    normalized_model_version = model_version.strip()

    if not normalized_model_version:
        raise ValueError("model_version cannot be blank.")

    if regularization_c <= 0:
        raise ValueError(
            "Regularization C must be greater than zero."
        )

    if (
        dataset.feature_schema_version
        != expected_feature_schema_version
    ):
        raise ValueError(
            "Dataset feature schema does not match the expected "
            "candidate schema: "
            f"{dataset.feature_schema_version} != "
            f"{expected_feature_schema_version}"
        )

    if not dataset.examples:
        raise ValueError(
            "Candidate training requires dataset examples."
        )

    if not evaluation_report_path.exists():
        raise FileNotFoundError(
            "Walk-forward evaluation report was not found: "
            f"{evaluation_report_path}"
        )

    matchup_dataset, transformer = (
        transform_to_matchup_difference_dataset(
            dataset
        )
    )

    fitted_model = fit_moneyline_baseline(
        matchup_dataset,
        regularization_c=regularization_c,
    )

    candidate_model = TrainedMatchupMoneylineModel(
        transformer=transformer,
        model=fitted_model,
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    model_path = output_directory / "model.joblib"
    manifest_path = output_directory / "manifest.json"
    evaluation_path = output_directory / "evaluation.json"

    save_trained_matchup_moneyline_model(
        candidate_model,
        model_path,
    )

    if (
        evaluation_report_path.resolve()
        != evaluation_path.resolve()
    ):
        shutil.copyfile(
            evaluation_report_path,
            evaluation_path,
        )

    reloaded_model = (
        load_trained_matchup_moneyline_model(
            model_path
        )
    )

    smoke_example = dataset.examples[-1]

    smoke_feature_mapping = dict(
        zip(
            dataset.feature_names,
            smoke_example.feature_values,
            strict=True,
        )
    )

    original_probability = (
        candidate_model.predict_home_win_probability(
            smoke_feature_mapping
        )
    )
    reloaded_probability = (
        reloaded_model.predict_home_win_probability(
            smoke_feature_mapping
        )
    )

    if abs(
        original_probability - reloaded_probability
    ) > 1e-12:
        raise RuntimeError(
            "Reloaded candidate probability does not match "
            "the in-memory model."
        )

    resolved_git_commit = (
        git_commit
        if git_commit is not None
        else _get_git_commit()
    )

    manifest: dict[str, Any] = {
        "model_version": normalized_model_version,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "git_commit": resolved_git_commit,
        "model_type": (
            "regularized_logistic_regression"
        ),
        "feature_representation": (
            "matchup_difference"
        ),
        "feature_schema_version": (
            dataset.feature_schema_version
        ),
        "matchup_feature_transform_version": (
            MATCHUP_FEATURE_TRANSFORM_VERSION
        ),
        "matchup_model_artifact_format_version": (
            MATCHUP_MODEL_ARTIFACT_FORMAT_VERSION
        ),
        "baseline_model_artifact_format_version": (
            MODEL_ARTIFACT_FORMAT_VERSION
        ),
        "regularization_c": regularization_c,
        "training": {
            "rows": fitted_model.training_rows,
            "start_time": (
                dataset.examples[0]
                .game_start_time
                .isoformat()
            ),
            "end_time": (
                fitted_model.training_end_time.isoformat()
            ),
            "home_win_rate": (
                sum(
                    example.home_team_won
                    for example in dataset.examples
                )
                / len(dataset.examples)
            ),
        },
        "features": {
            "raw_feature_count": len(
                dataset.feature_names
            ),
            "matchup_feature_count": len(
                transformer.output_feature_names
            ),
            "active_feature_count": len(
                fitted_model.active_feature_names
            ),
            "raw_feature_names": list(
                dataset.feature_names
            ),
            "matchup_feature_names": list(
                transformer.output_feature_names
            ),
            "active_feature_names": list(
                fitted_model.active_feature_names
            ),
            "dropped_all_missing_features": list(
                fitted_model
                .dropped_all_missing_features
            ),
            "dropped_constant_features": list(
                fitted_model
                .dropped_constant_features
            ),
            "dropped_duplicate_features": list(
                fitted_model
                .dropped_duplicate_features
            ),
        },
        "artifacts": {
            "model": _file_record(model_path),
            "evaluation": _file_record(
                evaluation_path
            ),
            "source_dataset": (
                None
                if source_dataset_path is None
                else _file_record(
                    source_dataset_path
                )
            ),
        },
        "smoke_test": {
            "game_id": smoke_example.game_id,
            "game_start_time": (
                smoke_example
                .game_start_time
                .isoformat()
            ),
            "home_win_probability": (
                reloaded_probability
            ),
        },
        "runtime": {
            "python_version": (
                platform.python_version()
            ),
            "scikit_learn_version": (
                sklearn.__version__
            ),
        },
        "evaluation_note": (
            "The serialized candidate is fitted on all available "
            "training rows. Historical performance is supplied by "
            "the separate copied walk-forward evaluation report."
        ),
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return MoneylineCandidateBuildResult(
        model_path=model_path,
        manifest_path=manifest_path,
        evaluation_path=evaluation_path,
        training_rows=fitted_model.training_rows,
        smoke_game_id=smoke_example.game_id,
        smoke_home_win_probability=(
            reloaded_probability
        ),
    )


def _file_record(path: Path) -> dict[str, Any]:
    """
    Return a path, size, and SHA-256 record for one artifact.
    """

    resolved_path = path.resolve()

    return {
        "path": str(resolved_path),
        "size_bytes": resolved_path.stat().st_size,
        "sha256": _calculate_sha256(
            resolved_path
        ),
    }


def _calculate_sha256(path: Path) -> str:
    """
    Calculate the SHA-256 digest of one file.
    """

    digest = sha256()

    with path.open("rb") as input_file:
        for chunk in iter(
            lambda: input_file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _get_git_commit() -> str:
    """
    Return the current Git commit when available.
    """

    try:
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "HEAD",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
    ):
        return "unavailable"

    return result.stdout.strip()
