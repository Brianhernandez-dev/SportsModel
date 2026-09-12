from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sportsmodel.database.nfl_historical_probability_evidence_repository import (
    _build_source_trace,
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
