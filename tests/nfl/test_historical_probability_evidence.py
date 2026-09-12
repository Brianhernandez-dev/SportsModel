from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import sportsmodel.nfl.historical_probability_evidence as evidence_module
import sportsmodel.nfl.historical_probability_evidence_cli as evidence_cli

from sportsmodel.nfl.historical_probability_evidence import (
    EARLY_FEATURE_NAMES,
    FORBIDDEN_OUTPUT_FIELDS,
    GAME_IDENTITY_FIELDS,
    HISTORICAL_FOLDS,
    MATURE_FEATURE_NAMES,
    PROBABILITY_OUTPUT_FIELDS,
    ForwardExposure,
    HistoricalEvidenceInput,
    HistoricalScoreTarget,
    HistoricalTrainingRecord,
    build_historical_evidence,
    evidence_package_documents,
    historical_evidence_protocol,
    reconcile_optional_2025_holdout,
    record_deterministic_rerun_pass,
    validate_evidence_package,
    write_historical_evidence_package,
)
from sportsmodel.nfl.moneyline_routing import (
    NFLMoneylineRoute,
    select_nfl_moneyline_route,
)


NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_frozen_feature_families_and_fixed_folds_are_exact() -> None:
    assert len(EARLY_FEATURE_NAMES) == 4
    assert "neutral_site" not in EARLY_FEATURE_NAMES
    assert len(MATURE_FEATURE_NAMES) == 19
    assert HISTORICAL_FOLDS == (
        _fold("early_oof_2021", "early", (2019, 2020), 2021),
        _fold("early_oof_2022", "early", (2019, 2020, 2021), 2022),
        _fold("early_oof_2023", "early", (2019, 2020, 2021, 2022), 2023),
        _fold("early_oof_2024", "early", (2019, 2020, 2021, 2022, 2023), 2024),
        _fold("mature_oof_2022", "mature", tuple(range(2018, 2022)), 2022),
        _fold("mature_oof_2023", "mature", tuple(range(2018, 2023)), 2023),
        _fold("mature_oof_2024", "mature", tuple(range(2018, 2024)), 2024),
    )
    assert all(fold.score_season not in fold.training_seasons for fold in HISTORICAL_FOLDS)


def test_score_target_is_structurally_outcome_free_and_uses_identity_neutral_site() -> None:
    names = {item.name for item in fields(HistoricalScoreTarget)}
    assert not names.intersection(FORBIDDEN_OUTPUT_FIELDS)
    target = _score_target(2021, NFLMoneylineRoute.EARLY, 9001)
    assert target.neutral_site
    assert target.feature_names == EARLY_FEATURE_NAMES
    assert len(target.feature_values) == 4


def test_tied_target_membership_is_explicitly_outcome_blind() -> None:
    target = _score_target(2021, NFLMoneylineRoute.EARLY, 9010)
    source = replace(_source(), score_targets=(target,))
    bundle = build_historical_evidence(source, enforce_expected_counts=False)

    assert [row["canonical_game_id"] for row in bundle.probabilities] == [9010]
    assert not {item.name for item in fields(target)}.intersection({
        "home_score", "away_score", "home_win", "target_tied", "target_tie"
    })


@pytest.mark.parametrize("width", [5, 11])
def test_legacy_early_feature_substitution_is_rejected(width: int) -> None:
    source = _source()
    early = next(item for item in source.score_targets if item.route is NFLMoneylineRoute.EARLY)
    changed = replace(
        early,
        feature_names=tuple(f"feature_{index}" for index in range(width)),
        feature_values=tuple(float(index) for index in range(width)),
    )
    with pytest.raises(ValueError, match="frozen feature order"):
        build_historical_evidence(
            replace(source, score_targets=(changed, *source.score_targets[1:])),
            enforce_expected_counts=False,
        )


def test_routing_boundary_uses_actual_three_three_counts() -> None:
    assert select_nfl_moneyline_route(2, 99) is NFLMoneylineRoute.EARLY
    assert select_nfl_moneyline_route(99, 2) is NFLMoneylineRoute.EARLY
    assert select_nfl_moneyline_route(3, 3) is NFLMoneylineRoute.MATURE
    changed = replace(
        _score_target(2022, NFLMoneylineRoute.MATURE, 9900),
        away_current_prior_games=2,
    )
    with pytest.raises(ValueError, match="3/3"):
        build_historical_evidence(
            replace(_source(), score_targets=(changed,)),
            enforce_expected_counts=False,
        )


def test_probability_population_is_outcome_blind_and_deterministic() -> None:
    source = _source()
    first = build_historical_evidence(source, enforce_expected_counts=False)
    second = build_historical_evidence(source, enforce_expected_counts=False)

    assert first == second
    assert len(first.probabilities) == len(source.score_targets)
    assert tuple(first.probabilities[0]) == PROBABILITY_OUTPUT_FIELDS
    assert tuple(first.game_identity[0]) == GAME_IDENTITY_FIELDS
    assert all(row["score_season"] < 2026 for row in first.probabilities)
    assert all(
        row["evidence_classification"] in {
            "DEVELOPMENT_OOF", "EXPOSED_MODEL_HOLDOUT"
        }
        for row in first.probabilities
    )
    assert first.validation_summary["market_and_outcome_denylist"]


def test_score_values_do_not_affect_training_only_preprocessing() -> None:
    source = _source()
    first = build_historical_evidence(source, enforce_expected_counts=False)
    changed_targets = tuple(
        replace(
            item,
            feature_values=tuple(
                None if value is None else value + 10000
                for value in item.feature_values
            ),
        )
        for item in source.score_targets
    )
    second = build_historical_evidence(
        replace(source, score_targets=changed_targets),
        enforce_expected_counts=False,
    )
    assert first.model_fingerprints == second.model_fingerprints
    assert first.training_set_fingerprints == second.training_set_fingerprints
    assert first.probabilities != second.probabilities


def test_fold_metadata_forbids_policy_selection_and_tuning() -> None:
    bundle = build_historical_evidence(_source(), enforce_expected_counts=False)
    assert all(not row["policy_selection"] for row in bundle.folds)
    assert all(not row["hyperparameter_tuning"] for row in bundle.folds)
    assert all("SimpleImputer" in row["preprocessing"] for row in bundle.folds)
    oof = [
        row for row in bundle.model_fingerprints
        if not row["fit_free_committed_artifact"]
    ]
    assert len({row["model_fingerprint"] for row in oof}) == len(oof)


def test_train_score_identity_overlap_fails_closed() -> None:
    source = _source()
    changed = replace(
        source.score_targets[0],
        canonical_game_id=source.training_records[0].canonical_game_id,
    )
    with pytest.raises(ValueError, match="overlap"):
        build_historical_evidence(
            replace(source, score_targets=(changed, *source.score_targets[1:])),
            enforce_expected_counts=False,
        )


def test_locked_population_counts_are_enforced_by_default() -> None:
    with pytest.raises(ValueError, match="1,187-row"):
        build_historical_evidence(_source())


def test_source_kickoff_must_be_strictly_before_feature_cutoff() -> None:
    source = _source()
    target = source.score_targets[0]
    changed = replace(target, source_trace={
        "channels": [{"games": [{"kickoff": target.kickoff}]}]
    })
    with pytest.raises(ValueError, match="strictly before"):
        build_historical_evidence(
            replace(source, score_targets=(changed, *source.score_targets[1:])),
            enforce_expected_counts=False,
        )


@pytest.mark.parametrize(
    "kickoff",
    [datetime(2020, 1, 1), "2020-01-01T00:00:00", "not-a-timestamp", None],
)
def test_source_kickoff_naive_malformed_or_unknown_representation_fails_closed(
    kickoff,
) -> None:
    source = _source()
    target = source.score_targets[0]
    changed = replace(target, source_trace={"kickoff": kickoff})
    with pytest.raises(ValueError, match="source kickoff"):
        build_historical_evidence(
            replace(source, score_targets=(changed, *source.score_targets[1:])),
            enforce_expected_counts=False,
        )


def test_per_row_source_snapshot_must_match_actual_trace_dependencies() -> None:
    source = _source()
    target = source.score_targets[0]
    changed = replace(
        target,
        source_trace={
            **target.source_trace,
            "target_game": {
                "game_observations": [{
                    "ingestion_run_id": 1,
                    "observed_at": target.source_snapshot_as_of,
                    "raw_row_sha256": "a" * 64,
                }],
            },
        },
        source_snapshot_as_of=target.source_snapshot_as_of + timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="differs from actual source trace"):
        build_historical_evidence(
            replace(source, score_targets=(changed, *source.score_targets[1:])),
            enforce_expected_counts=False,
        )


def test_market_or_outcome_field_in_source_trace_fails_closed() -> None:
    source = _source()
    target = source.score_targets[0]
    changed = replace(target, source_trace={"home_score": 21})
    with pytest.raises(ValueError, match="forbidden"):
        build_historical_evidence(
            replace(source, score_targets=(changed, *source.score_targets[1:])),
            enforce_expected_counts=False,
        )


def test_forward_2026_evidence_is_registry_only() -> None:
    bundle = build_historical_evidence(_source(), enforce_expected_counts=False)
    assert all(row["score_season"] != 2026 for row in bundle.probabilities)
    assert bundle.exposure_registry["classification"] == "EXPOSED_FORWARD"
    assert bundle.exposure_registry["rows"][0]["evidence_classification"] == "EXPOSED_FORWARD"


def test_2026_probability_target_is_rejected() -> None:
    source = _source()
    with pytest.raises(ValueError, match=r"2026\+"):
        build_historical_evidence(
            replace(source, score_targets=(*source.score_targets, _score_target(
                2026, NFLMoneylineRoute.EARLY, 9999
            ))),
            enforce_expected_counts=False,
        )


def test_package_manifest_detects_missing_extra_and_hash_mismatch(tmp_path: Path) -> None:
    bundle = _verified_bundle()
    package = tmp_path / "package"
    write_historical_evidence_package(
        bundle, package, repository_root=tmp_path / "repository"
    )
    validate_evidence_package(package)

    probabilities = package / "probabilities.csv"
    original = probabilities.read_bytes()
    probabilities.write_bytes(original + b"tamper")
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_evidence_package(package)
    probabilities.write_bytes(original)

    extra = package / "extra.txt"
    extra.write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="file set mismatch"):
        validate_evidence_package(package)
    extra.unlink()

    probabilities.unlink()
    with pytest.raises(ValueError, match="file set mismatch"):
        validate_evidence_package(package)


def test_output_inside_repository_is_refused_without_override(tmp_path: Path) -> None:
    bundle = build_historical_evidence(_source(), enforce_expected_counts=False)
    repository = tmp_path / "repository"
    repository.mkdir()
    with pytest.raises(ValueError, match="inside the repository"):
        write_historical_evidence_package(
            bundle, repository / "audit_exports" / "package",
            repository_root=repository,
        )


def test_exporter_documents_have_no_odds_or_market_dependency() -> None:
    bundle = build_historical_evidence(_source(), enforce_expected_counts=False)
    documents = evidence_package_documents(bundle)
    probability_header = documents["probabilities.csv"].splitlines()[0].decode()
    assert "odds" not in probability_header
    assert "market" not in probability_header
    assert "actual_" not in probability_header
    assert bundle.holdout_reconciliation is None


def test_deterministic_rerun_is_unverified_until_two_renders_match(
    tmp_path: Path,
) -> None:
    bundle = build_historical_evidence(_source(), enforce_expected_counts=False)
    assert bundle.deterministic_rerun["status"] == "UNVERIFIED"
    assert bundle.deterministic_rerun["passed"] is False
    assert bundle.package_metadata["overall_validation_result"] == "UNVERIFIED"
    with pytest.raises(ValueError, match="deterministic rerun PASS"):
        write_historical_evidence_package(
            bundle, tmp_path / "package", repository_root=tmp_path / "repository"
        )

    render_sha = _render_sha(bundle)
    verified = record_deterministic_rerun_pass(
        bundle,
        first_render_sha256=render_sha,
        second_render_sha256=render_sha,
    )
    assert verified.deterministic_rerun == {
        **bundle.deterministic_rerun,
        "status": "PASS",
        "passed": True,
        "first_render_sha256": render_sha,
        "second_render_sha256": render_sha,
    }
    assert verified.package_metadata["overall_validation_result"] == "PASS"


def test_cli_records_pass_only_after_two_render_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = []
    source = object()
    unverified = SimpleNamespace(probabilities=(object(),))
    verified = SimpleNamespace(probabilities=(object(),))
    connection = _FakeConnection()

    monkeypatch.setattr(evidence_cli, "_repository_revision", lambda: "8" * 40)
    monkeypatch.setattr(
        evidence_cli,
        "load_historical_evidence_input",
        lambda cursor, repository_revision: source,
    )

    def build(received):
        assert received is source
        events.append("build")
        return unverified

    def render(received):
        assert received is unverified
        events.append("render")
        return {"protocol.json": b"same"}

    def record(received, *, first_render_sha256, second_render_sha256):
        assert received is unverified
        assert first_render_sha256 == second_render_sha256
        events.append("record-pass")
        return verified

    def write(received, *args, **kwargs):
        assert received is verified
        events.append("write")
        return {"manifest_payload_sha256": "f" * 64}

    monkeypatch.setattr(evidence_cli, "build_historical_evidence", build)
    monkeypatch.setattr(evidence_cli, "evidence_package_documents", render)
    monkeypatch.setattr(evidence_cli, "record_deterministic_rerun_pass", record)
    monkeypatch.setattr(evidence_cli, "write_historical_evidence_package", write)

    assert evidence_cli.main(
        [
            "--output-dir",
            str(tmp_path / "package"),
            "--allow-repository-output",
        ],
        connection_factory=lambda: connection,
    ) == 0
    assert events == ["build", "build", "render", "render", "record-pass", "write"]


def test_package_provenance_and_protocol_fingerprint_are_durable(
    tmp_path: Path,
) -> None:
    bundle = _verified_bundle()
    protocol = historical_evidence_protocol()
    fingerprint = protocol.pop("protocol_fingerprint")
    from sportsmodel.nfl.moneyline_frozen import fingerprint_payload

    assert fingerprint == fingerprint_payload(protocol)
    metadata = bundle.package_metadata
    assert metadata["repository_revision"] == "8" * 40
    assert metadata["protocol_fingerprint"] == fingerprint
    assert metadata["effective_database_identity"]["database"] == "sportsmodel_fixture"
    assert metadata["postgresql_server_identity"]["server_version_num"] == "160004"
    assert metadata["read_only_transaction_snapshot"]["snapshot_id"] == "1:2:"
    assert metadata["source_snapshot_metadata_version"] == (
        "nfl_historical_source_snapshot_metadata_0.2.0"
    )
    assert metadata["loaded_source_snapshot_as_of"] == "2026-07-31T00:00:00.000000Z"
    assert metadata["evidence_dependency_source_snapshot_as_of"] == (
        "2026-07-31T00:00:00.000000Z"
    )
    assert metadata["expected_canonical_row_count"] == 1187
    assert metadata["actual_canonical_row_count"] == len(bundle.probabilities)
    assert metadata["overall_validation_result"] == "PASS"
    assert "source_snapshot_as_of" not in metadata

    package = tmp_path / "package"
    manifest = write_historical_evidence_package(
        bundle, package, repository_root=tmp_path / "repository"
    )
    assert manifest["package_metadata"] == metadata


def test_later_2026_loaded_snapshot_does_not_advance_evidence_dependencies() -> None:
    source = _source()
    row_snapshot = NOW - timedelta(days=1)
    training_snapshot = NOW
    later_2026_snapshot = NOW + timedelta(days=1)
    target = source.score_targets[0]
    target = replace(
        target,
        source_trace={
            **target.source_trace,
            "target_game": {
                "game_observations": [{
                    "canonical_game_id": target.canonical_game_id,
                    "ingestion_run_id": 1,
                    "observed_at": row_snapshot,
                    "raw_row_sha256": "a" * 64,
                }],
            },
        },
        source_snapshot_as_of=row_snapshot,
    )
    source = replace(
        source,
        loaded_source_snapshot_as_of=later_2026_snapshot,
        score_targets=(target, *source.score_targets[1:]),
        source_snapshot_metadata=(
            {
                "ingestion_run_id": 1,
                "source_name": "fixture",
                "source_asset": "historical.csv",
                "source_file_sha256": "1" * 64,
                "retrieved_at": row_snapshot,
                "completed_at": row_snapshot,
                "loaded_game_observation_count": 1,
                "loaded_statistics_observation_count": 1,
                "loaded_observation_count": 2,
                "loaded_source_snapshot_as_of": training_snapshot,
                "training_reconstruction_observation_count": 1,
                "training_reconstruction_source_snapshot_as_of": training_snapshot,
            },
            {
                "ingestion_run_id": 10,
                "source_name": "2026-only-fixture",
                "source_asset": "2026-games.csv",
                "source_file_sha256": "2" * 64,
                "retrieved_at": later_2026_snapshot,
                "completed_at": later_2026_snapshot,
                "loaded_game_observation_count": 1,
                "loaded_statistics_observation_count": 0,
                "loaded_observation_count": 1,
                "loaded_source_snapshot_as_of": later_2026_snapshot,
                "training_reconstruction_observation_count": 0,
                "training_reconstruction_source_snapshot_as_of": None,
            },
        ),
    )

    bundle = build_historical_evidence(source, enforce_expected_counts=False)

    snapshots = bundle.source_snapshots
    assert "source_snapshot_as_of" not in snapshots
    assert snapshots["loaded_source_snapshot_as_of"] == (
        "2026-08-02T00:00:00.000000Z"
    )
    assert snapshots["evidence_dependency_source_snapshot_as_of"] == (
        "2026-08-01T00:00:00.000000Z"
    )
    assert {row["source_snapshot_as_of"] for row in bundle.probabilities} == {
        "2026-07-31T00:00:00.000000Z"
    }
    by_run = {
        item["ingestion_run_id"]: item for item in snapshots["snapshots"]
    }
    assert by_run[1]["contribution_classifications"] == [
        "probability_row_trace_contributor",
        "training_reconstruction_contributor",
    ]
    assert by_run[1]["probability_row_trace_reference_count"] == 1
    assert by_run[1]["probability_row_trace_unique_observation_count"] == 1
    assert by_run[1]["probability_row_trace_source_snapshot_as_of"] == (
        "2026-07-31T00:00:00.000000Z"
    )
    assert by_run[10]["contribution_classifications"] == [
        "unrelated_loaded_context"
    ]
    assert by_run[10]["probability_row_trace_reference_count"] == 0
    assert by_run[10]["probability_row_trace_source_snapshot_as_of"] is None
    assert by_run[10]["training_reconstruction_observation_count"] == 0
    assert bundle.package_metadata["loaded_source_snapshot_as_of"] == (
        snapshots["loaded_source_snapshot_as_of"]
    )
    assert bundle.package_metadata[
        "evidence_dependency_source_snapshot_as_of"
    ] == snapshots["evidence_dependency_source_snapshot_as_of"]


def test_optional_2025_holdout_reconciliation_passes_by_canonical_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = build_historical_evidence(_source(), enforce_expected_counts=False)
    probabilities = tuple(
        {
            "canonical_game_id": 10000 + index,
            "home_win_probability": "0.5000000000000000",
            "score_season": 2025,
            "selected_route": "mature",
        }
        for index in range(236)
    )
    report = {
        "eligible_holdout_predictions": [
            {"game_id": 10000 + index, "model_home_win_probability": 0.5}
            for index in range(236)
        ]
    }
    report_path = tmp_path / "holdout.json"
    content = (json.dumps(report, sort_keys=True) + "\n").encode()
    report_path.write_bytes(content)
    monkeypatch.setattr(
        evidence_module,
        "HOLDOUT_RECONCILIATION_SHA256",
        sha256(content).hexdigest(),
    )

    result = reconcile_optional_2025_holdout(
        replace(bundle, probabilities=probabilities), report_path
    )
    assert result["legacy_non_tie_rows_compared"] == 236
    assert result["passed"] is True


def _fold(fold_id, route, seasons, score_season):
    from sportsmodel.nfl.historical_probability_evidence import HistoricalFold

    return HistoricalFold(fold_id, NFLMoneylineRoute(route), seasons, score_season)


def _source() -> HistoricalEvidenceInput:
    training = []
    game_id = 1
    for route, first_season, names in (
        (NFLMoneylineRoute.EARLY, 2019, EARLY_FEATURE_NAMES),
        (NFLMoneylineRoute.MATURE, 2018, MATURE_FEATURE_NAMES),
    ):
        for season in range(first_season, 2025):
            for index in range(4):
                training.append(HistoricalTrainingRecord(
                    canonical_game_id=game_id,
                    kickoff=datetime(season, 9, 1, tzinfo=timezone.utc) + timedelta(days=index),
                    season=season,
                    route=route,
                    feature_names=names,
                    feature_values=tuple(
                        None if index == 0 and feature_index == 1
                        else float(index + feature_index + (season % 3))
                        for feature_index in range(len(names))
                    ),
                    home_win=(index + season) % 2 == 0,
                ))
                game_id += 1
    score_targets = (
        *(
            _score_target(season, NFLMoneylineRoute.EARLY, 8000 + season)
            for season in range(2021, 2026)
        ),
        *(
            _score_target(season, NFLMoneylineRoute.MATURE, 9000 + season)
            for season in range(2022, 2026)
        ),
    )
    return HistoricalEvidenceInput(
        reconstruction_as_of=NOW,
        loaded_source_snapshot_as_of=NOW - timedelta(days=1),
        repository_revision="8" * 40,
        database_identity={
            "database": "sportsmodel_fixture",
            "user": "fixture",
            "configured_host": "127.0.0.1",
            "configured_port": 55432,
        },
        server_identity={
            "server_address": "127.0.0.1",
            "server_port": 55432,
            "postgresql_version": "PostgreSQL fixture",
            "server_version_num": "160004",
            "in_recovery": False,
        },
        transaction_snapshot={
            "transaction_isolation": "repeatable read",
            "transaction_read_only": True,
            "snapshot_id": "1:2:",
            "transaction_id_if_assigned": None,
        },
        training_records=tuple(training),
        score_targets=score_targets,
        forward_exposures=(ForwardExposure(
            canonical_game_id=12026,
            prediction_run_id=10,
            prediction_id=20,
            prediction_created_at=NOW + timedelta(days=40),
            route=NFLMoneylineRoute.EARLY,
            model_specification_version="nfl_moneyline_early_frozen_0.1.0",
            model_fingerprint="a" * 64,
        ),),
    )


def _score_target(season, route, game_id):
    names = EARLY_FEATURE_NAMES if route is NFLMoneylineRoute.EARLY else MATURE_FEATURE_NAMES
    kickoff = datetime(season, 10, 1, tzinfo=timezone.utc)
    return HistoricalScoreTarget(
        canonical_game_id=game_id,
        kickoff=kickoff,
        season=season,
        season_type="regular",
        week=4,
        week_label="Week 4",
        home_team_id=1,
        away_team_id=2,
        home_team="HOME",
        away_team="AWAY",
        neutral_site=True,
        home_current_prior_games=2 if route is NFLMoneylineRoute.EARLY else 3,
        away_current_prior_games=2 if route is NFLMoneylineRoute.EARLY else 3,
        route=route,
        feature_names=names,
        feature_values=tuple(float(index) for index in range(len(names))),
        source_trace={
            "channels": [{
                "side": "home",
                "channel": "history",
                "games": [{
                    "canonical_game_id": game_id - 1,
                    "kickoff": kickoff - timedelta(days=7),
                }],
            }],
        },
        source_snapshot_as_of=NOW - timedelta(days=1),
        source_name="fixture",
        external_game_id=f"fixture-{game_id}",
    )


def _verified_bundle():
    bundle = build_historical_evidence(_source(), enforce_expected_counts=False)
    render_sha = _render_sha(bundle)
    return record_deterministic_rerun_pass(
        bundle,
        first_render_sha256=render_sha,
        second_render_sha256=render_sha,
    )


def _render_sha(bundle):
    from sportsmodel.nfl.moneyline_frozen import fingerprint_payload

    return fingerprint_payload({
        path: content.decode("utf-8")
        for path, content in sorted(evidence_package_documents(bundle).items())
    })


class _FakeConnection:
    def set_session(self, **kwargs):
        assert kwargs == {"isolation_level": "REPEATABLE READ", "readonly": True}

    def cursor(self):
        return _FakeCursor()

    def rollback(self):
        pass

    def close(self):
        pass


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
