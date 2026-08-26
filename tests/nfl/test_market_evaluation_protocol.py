import json
from pathlib import Path

from sportsmodel.nfl.moneyline_frozen import fingerprint_payload


PROTOCOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "nfl_moneyline_market_evaluation_0.1.0.json"
)
ARCHITECTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "architecture"
    / "nfl_phase_4_market_layer_audit.md"
)


def _protocol() -> dict:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def test_protocol_artifact_has_reproducible_identity() -> None:
    protocol = _protocol()
    fingerprint = protocol.pop("protocol_fingerprint")

    assert protocol["protocol_version"] == (
        "nfl_moneyline_market_evaluation_0.1.0"
    )
    assert PROTOCOL_PATH.name == (
        f"{protocol['protocol_version']}.json"
    )
    assert fingerprint == fingerprint_payload(protocol)

    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    assert protocol["protocol_version"] in architecture
    assert fingerprint in architecture


def test_protocol_freezes_prediction_and_market_timing() -> None:
    protocol = _protocol()
    prediction = protocol["prediction_eligibility"]
    snapshot = protocol["snapshot_eligibility"]
    timing = protocol["timing"]

    assert prediction["allowed_run_type"] == "official"
    assert prediction["allowed_run_status"] == "completed"
    assert prediction["allowed_routes"] == ["early", "mature"]
    assert prediction["allowed_prediction_protocol_versions"] == [
        "nfl_moneyline_forward_0.1.0"
    ]
    assert prediction["preview_debug_failed_partial_or_ad_hoc"] == (
        "ineligible"
    )
    assert snapshot == {
        "market_type": "h2h",
        "odds_run_source_name": "odds_api",
        "odds_run_status": "completed",
        "snapshot_role": "entry",
        "sport_key": "americanfootball_nfl",
        "use_only_official_pregame_evidence": True,
    }
    assert timing["interpretation"] == (
        "entry_decision_after_completed_official_prediction"
    )
    assert timing["maximum_prediction_to_market_observation_seconds"] == 900
    assert timing["maximum_market_observation_to_evaluation_seconds"] == 300
    assert timing["same_odds_ingestion_run_required"] is True
    assert timing["same_trusted_observed_at_required"] is True
    assert timing["evaluation_created_at_at_or_after_trusted_observation"] is True
    assert timing["evaluation_created_at_strictly_before_kickoff"] is True
    assert timing["canonical_game_must_be_unplayed_at_evaluation"] is True


def test_protocol_freezes_contributor_consensus_and_best_price_rules() -> None:
    protocol = _protocol()
    contributors = protocol["contributor_selection"]
    consensus = protocol["consensus"]
    best_price = protocol["best_price"]

    assert contributors["provider_identity"] == (
        "sportsbook_provider_identity_id"
    )
    assert contributors["allow_mixed_odds_runs"] is False
    assert contributors["maximum_market_update_lag_seconds"] == 300
    assert contributors["paired_rows_must_share_market_updated_at"] is True
    assert contributors["duplicate_provider_or_selection_rule"] == (
        "evaluation_impossible"
    )
    assert consensus["minimum_complete_provider_books"] == 5
    assert consensus["include_offering_book"] is True
    assert consensus["official_method"] == (
        "equal_weight_mean_of_per_book_no_vig_probabilities"
    )
    assert best_price["eligible_set"] == (
        "exact_consensus_contributor_set"
    )
    assert best_price["tie_break"] == (
        "lowest_sportsbook_provider_identity_id"
    )


def test_protocol_freezes_precision_idempotency_and_run_281_status() -> None:
    protocol = _protocol()

    assert protocol["numeric_contract"] == {
        "derived_decimal_quantum": "0.0000000000000001",
        "persisted_decimal_places": 16,
        "rounding": "ROUND_HALF_EVEN",
        "working_decimal_precision": 28,
    }
    assert protocol["idempotency"]["same_exact_evidence"] == (
        "return_existing_immutable_evaluation"
    )
    assert protocol["idempotency"]["different_evidence_same_identity"] == (
        "reject_conflict"
    )
    assert protocol["run_281_classification"] == {
        "future_official_clv_or_paper_reference": False,
        "market_only_capture_validation": True,
        "official_evaluation_eligible": False,
        "reason": "no_completed_official_prediction_existed_before_capture",
    }


def test_protocol_contains_no_result_tuned_policy() -> None:
    serialized = json.dumps(_protocol(), sort_keys=True).lower()

    for forbidden in (
        "betting_result",
        "win_rate",
        "return_on_investment",
        "profit_threshold",
    ):
        assert forbidden not in serialized
