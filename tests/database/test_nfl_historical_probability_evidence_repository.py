from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sportsmodel.database.nfl_historical_probability_evidence_repository import (
    _annotate_training_reconstruction_contributions,
    _build_source_trace,
    _derive_training_reconstruction_dependencies,
    _load_forward_exposures,
    _reject_latest_timestamp_ambiguity,
)


NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_equally_latest_distinct_source_rows_fail_closed() -> None:
    observations = (
        {"observed_at": NOW, "raw_row_sha256": "a" * 64},
        {"observed_at": NOW, "raw_row_sha256": "b" * 64},
    )
    with pytest.raises(ValueError, match="equally-latest"):
        _reject_latest_timestamp_ambiguity(observations, "game 1")


def test_ordered_correction_lineage_is_deterministic() -> None:
    observations = (
        {"observed_at": NOW - timedelta(days=1), "raw_row_sha256": "a" * 64},
        {"observed_at": NOW, "raw_row_sha256": "b" * 64},
    )
    _reject_latest_timestamp_ambiguity(observations, "game 1")


def test_training_reconstruction_contributions_exclude_unrelated_loaded_context(
) -> None:
    earlier = NOW - timedelta(days=1)
    later = NOW + timedelta(days=1)
    snapshots = (
        {"ingestion_run_id": 1},
        {"ingestion_run_id": 2},
        {"ingestion_run_id": 10},
    )
    game_dependency_ids, statistics_dependency_game_ids = (
        _derive_training_reconstruction_dependencies(
            mature_rows=({"target_game_id": 1},),
            mature_traces=(SimpleNamespace(
                target_game_id=1,
                source_game_ids=(2,),
            ),),
            early_rows=(),
        )
    )
    annotated = _annotate_training_reconstruction_contributions(
        snapshots,
        game_observations={
            1: ({"ingestion_run_id": 1, "observed_at": earlier},),
            2: ({"ingestion_run_id": 2, "observed_at": NOW},),
            3: ({"ingestion_run_id": 10, "observed_at": later},),
        },
        stats_observations={
            (1, 100): ({"ingestion_run_id": 10, "observed_at": later},),
            (2, 100): ({"ingestion_run_id": 2, "observed_at": NOW},),
            (2, 200): ({"ingestion_run_id": 2, "observed_at": NOW},),
        },
        game_dependency_ids=game_dependency_ids,
        statistics_dependency_game_ids=statistics_dependency_game_ids,
    )

    by_run = {item["ingestion_run_id"]: item for item in annotated}
    assert game_dependency_ids == {1, 2}
    assert statistics_dependency_game_ids == {2}
    assert by_run[1]["training_reconstruction_observation_count"] == 1
    assert by_run[1]["training_reconstruction_source_snapshot_as_of"] == earlier
    assert by_run[2]["training_reconstruction_observation_count"] == 3
    assert by_run[2]["training_reconstruction_source_snapshot_as_of"] == NOW
    assert by_run[10]["training_reconstruction_observation_count"] == 0
    assert by_run[10]["training_reconstruction_source_snapshot_as_of"] is None


def test_exact_dependencies_include_early_upstream_but_not_unused_trace() -> None:
    game_dependency_ids, statistics_dependency_game_ids = (
        _derive_training_reconstruction_dependencies(
            mature_rows=({"target_game_id": 1},),
            mature_traces=(
                SimpleNamespace(target_game_id=1, source_game_ids=(2,)),
                SimpleNamespace(target_game_id=99, source_game_ids=(3,)),
            ),
            early_rows=({
                "target_game_id": 4,
                "home_prior_season_source_game_ids": (5,),
                "away_prior_season_source_game_ids": (),
                "home_current_season_source_game_ids": (6,),
                "away_current_season_source_game_ids": (),
            },),
        )
    )

    assert game_dependency_ids == {1, 2, 4, 5, 6}
    assert statistics_dependency_game_ids == {2, 5, 6}


def test_source_trace_preserves_observation_lineage_without_raw_payload() -> None:
    source_game = SimpleNamespace(
        game_id=10,
        kickoff=NOW - timedelta(days=7),
        season=2025,
        season_type="regular",
    )
    inference = SimpleNamespace(source_trace=(SimpleNamespace(
        side="home", channel="current_season_routing", games=(source_game,)
    ),))
    target_observation = _observation("target", NOW - timedelta(days=2))
    target_observation.update({
        "anomaly_state": "accepted_override",
        "override_provenance": {"ticket": "fixture-approval"},
    })
    source_observation = _observation("source", NOW - timedelta(days=1))
    home_stats_observation = {
        **_observation("stats", NOW),
        "canonical_game_id": 10,
        "canonical_team_id": 1,
        "provider_team_external_id": "home-team",
        "raw_row_sha256": "h" * 64,
    }
    away_stats_observation = {
        **_observation("stats-away", NOW),
        "canonical_game_id": 10,
        "canonical_team_id": 2,
        "provider_team_external_id": "away-team",
        "raw_row_sha256": "a" * 64,
    }

    trace, snapshot_as_of = _build_source_trace(
        game_id=20,
        inference=inference,
        game_observations={20: (target_observation,), 10: (source_observation,)},
        stats_observations={
            (10, 1): (home_stats_observation,),
            (10, 2): (away_stats_observation,),
        },
    )

    assert snapshot_as_of == NOW
    assert trace["channels"][0]["games"][0]["kickoff"] < NOW
    serialized = repr(trace)
    assert "raw_payload" not in serialized
    assert "home_score" not in serialized
    assert "raw_row_sha256" in serialized
    target_trace = trace["target_game"]["game_observations"][0]
    assert target_trace["anomaly_state"] == "accepted_override"
    assert target_trace["override_provenance"] == {"ticket": "fixture-approval"}
    statistics = trace["channels"][0]["games"][0]["statistics_observations"]
    assert {
        (
            item["canonical_game_id"],
            item["canonical_team_id"],
            item["provider_team_external_id"],
            item["source_name"],
            item["raw_row_sha256"],
            item["ingestion_run_id"],
            item["source_asset"],
            item["source_file_sha256"],
        )
        for item in statistics
    } == {
        (10, 1, "home-team", "fixture", "h" * 64, 1, "fixture.csv", "f" * 64),
        (10, 2, "away-team", "fixture", "a" * 64, 1, "fixture.csv", "f" * 64),
    }


def test_forward_exposure_query_selects_only_authoritative_official_runs() -> None:
    cursor = _RecordingCursor()
    assert _load_forward_exposures(cursor) == ()
    normalized = " ".join(cursor.query.lower().split())
    assert "run.run_type = 'official'" in normalized
    assert "prediction.run_type = 'official'" in normalized


def _observation(label, observed_at):
    return {
        "source_name": "fixture",
        "external_game_id": label,
        "raw_row_sha256": label[0] * 64,
        "observed_at": observed_at,
        "provider_updated_at": None,
        "ingestion_run_id": 1,
        "source_asset": "fixture.csv",
        "source_file_sha256": "f" * 64,
        "retrieved_at": observed_at,
        "completed_at": observed_at,
    }


class _RecordingCursor:
    query = ""

    def execute(self, query, parameters=None):
        self.query = query

    def fetchall(self):
        return []
