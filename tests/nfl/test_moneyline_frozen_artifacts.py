import json
from pathlib import Path

import pytest

from sportsmodel.nfl.moneyline_frozen import (
    EARLY_ARTIFACT_PATH,
    EARLY_FEATURE_NAMES,
    MATURE_ARTIFACT_PATH,
    MATURE_FEATURE_NAMES,
    fingerprint_payload,
    load_frozen_nfl_early_artifact,
    load_frozen_nfl_mature_artifact,
)


def test_committed_early_and_mature_artifacts_load_strictly() -> None:
    early = load_frozen_nfl_early_artifact()
    mature = load_frozen_nfl_mature_artifact()

    assert early.feature_names == EARLY_FEATURE_NAMES
    assert mature.feature_names == MATURE_FEATURE_NAMES
    assert len(early.feature_names) == 4
    assert len(mature.feature_names) == 19
    assert early.training_row_count == 285
    assert mature.training_row_count == 1604


@pytest.mark.parametrize(
    ("source", "loader"),
    [
        (EARLY_ARTIFACT_PATH, load_frozen_nfl_early_artifact),
        (MATURE_ARTIFACT_PATH, load_frozen_nfl_mature_artifact),
    ],
)
def test_model_fingerprint_mismatch_is_rejected(
    tmp_path, source, loader
) -> None:
    payload = _payload(source)
    payload["model_fingerprint"] = "0" * 64
    path = _write(tmp_path, payload)

    with pytest.raises(ValueError, match="model fingerprint mismatch"):
        loader(path)


@pytest.mark.parametrize(
    ("source", "loader"),
    [
        (EARLY_ARTIFACT_PATH, load_frozen_nfl_early_artifact),
        (MATURE_ARTIFACT_PATH, load_frozen_nfl_mature_artifact),
    ],
)
def test_ordered_feature_mismatch_is_rejected(
    tmp_path, source, loader
) -> None:
    payload = _payload(source)
    payload["feature_names"][0:2] = reversed(payload["feature_names"][0:2])
    _refresh_model_fingerprint(payload)

    with pytest.raises(ValueError, match="ordered feature names"):
        loader(_write(tmp_path, payload))


def test_missing_and_unknown_artifact_fields_are_rejected(tmp_path) -> None:
    missing = _payload(EARLY_ARTIFACT_PATH)
    del missing["intercept"]
    with pytest.raises(ValueError, match="fields mismatch"):
        load_frozen_nfl_early_artifact(_write(tmp_path, missing))

    unknown = _payload(EARLY_ARTIFACT_PATH)
    unknown["silent_default"] = 1
    with pytest.raises(ValueError, match="unknown"):
        load_frozen_nfl_early_artifact(_write(tmp_path, unknown))


def test_malformed_numeric_and_coefficient_count_are_rejected(tmp_path) -> None:
    malformed = _payload(EARLY_ARTIFACT_PATH)
    malformed["coefficients"][0] = "not-a-number"
    _refresh_model_fingerprint(malformed)
    with pytest.raises(ValueError, match="numeric"):
        load_frozen_nfl_early_artifact(_write(tmp_path, malformed))

    wrong_count = _payload(MATURE_ARTIFACT_PATH)
    wrong_count["coefficients"].pop()
    _refresh_model_fingerprint(wrong_count)
    with pytest.raises(ValueError, match="dimensionality"):
        load_frozen_nfl_mature_artifact(_write(tmp_path, wrong_count))


def test_artifacts_exclude_2025_from_training_and_holdout_report_identity() -> None:
    early = _payload(EARLY_ARTIFACT_PATH)
    mature = _payload(MATURE_ARTIFACT_PATH)

    assert 2025 not in early["training_seasons"]
    assert 2025 not in mature["training_seasons"]
    assert mature["evidence_status"]["2025"] == (
        "permanently exposed historical holdout"
    )
    assert mature["model_fingerprint"] != (
        "29a7a790b6039c12edd276ceabfafe72c4845bc6ac2310d7874ee5da5e715dd3"
    )
    assert "eligible_holdout_predictions" not in mature
    assert "model_metrics" not in mature


def _payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _refresh_model_fingerprint(payload: dict) -> None:
    material = dict(payload)
    del material["model_fingerprint"]
    payload["model_fingerprint"] = fingerprint_payload(material)


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
