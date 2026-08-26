from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sportsmodel.nfl.market_evaluation import (
    MATURE_SPECIFICATION_FINGERPRINT,
    OfficialMarketEvaluationError,
    _EvidenceSource,
    _OddsRunSource,
    _PredictionSource,
    _select_contributors,
    _source_graph_fingerprint,
    _validate_evaluation_clock,
    _validate_odds_run_source,
    _validate_prediction_source,
)
from sportsmodel.nfl.moneyline_frozen import (
    EARLY_FEATURE_SCHEMA_VERSION,
    EARLY_MODEL_FINGERPRINT,
    EARLY_SPECIFICATION_FINGERPRINT,
    EARLY_SPECIFICATION_VERSION,
    MATURE_FEATURE_SCHEMA_VERSION,
    MATURE_MODEL_FINGERPRINT,
    MATURE_SPECIFICATION_VERSION,
)


RECEIPT = datetime(2099, 9, 10, 19, 45, tzinfo=timezone.utc)
KICKOFF = datetime(2099, 9, 10, 20, tzinfo=timezone.utc)


def _prediction(**changes) -> _PredictionSource:
    source = _PredictionSource(
        prediction_id=10,
        prediction_run_id=20,
        run_type="official",
        protocol_version="nfl_moneyline_forward_0.1.0",
        game_id=30,
        target_kickoff=KICKOFF,
        prediction_created_at=RECEIPT - timedelta(minutes=10),
        home_team_id=40,
        away_team_id=50,
        selected_route="early",
        routing_contract_version="nfl_moneyline_routing_0.1.0",
        model_specification_version=EARLY_SPECIFICATION_VERSION,
        feature_schema_version=EARLY_FEATURE_SCHEMA_VERSION,
        specification_fingerprint=EARLY_SPECIFICATION_FINGERPRINT,
        model_fingerprint=EARLY_MODEL_FINGERPRINT,
        model_home_win_probability=Decimal("0.6000000000000000"),
        predicted_side="home",
        run_status="completed",
        run_completed_at=RECEIPT - timedelta(minutes=1),
        early_model_specification_version=EARLY_SPECIFICATION_VERSION,
        early_feature_schema_version=EARLY_FEATURE_SCHEMA_VERSION,
        early_specification_fingerprint=EARLY_SPECIFICATION_FINGERPRINT,
        early_model_fingerprint=EARLY_MODEL_FINGERPRINT,
        mature_model_specification_version=MATURE_SPECIFICATION_VERSION,
        mature_feature_schema_version=MATURE_FEATURE_SCHEMA_VERSION,
        mature_specification_fingerprint=MATURE_SPECIFICATION_FINGERPRINT,
        mature_model_fingerprint=MATURE_MODEL_FINGERPRINT,
        current_kickoff=KICKOFF,
        current_game_status="unplayed",
        current_home_team_id=40,
        current_away_team_id=50,
    )
    return replace(source, **changes)


def _odds(**changes) -> _OddsRunSource:
    source = _OddsRunSource(
        odds_ingestion_run_id=60,
        sport="americanfootball_nfl",
        source_name="odds_api",
        snapshot_role="entry",
        status="completed",
        request_started_at=RECEIPT - timedelta(seconds=1),
        response_received_at=RECEIPT,
    )
    return replace(source, **changes)


def _evidence(
    books: int,
    *,
    prediction: _PredictionSource | None = None,
    odds: _OddsRunSource | None = None,
) -> tuple[_EvidenceSource, ...]:
    prediction = prediction or _prediction()
    odds = odds or _odds()
    assert odds.response_received_at is not None
    rows = []
    for index in range(books):
        provider_id = 100 + index
        market_time = odds.response_received_at - timedelta(seconds=10 + index)
        rows.extend(
            (
                _EvidenceSource(
                    evidence_id=1000 + index * 2,
                    odds_ingestion_run_id=odds.odds_ingestion_run_id,
                    provider_identity_id=provider_id,
                    game_id=prediction.game_id,
                    selection_team_id=prediction.home_team_id,
                    american_price=-110 + index,
                    trusted_observed_at=odds.response_received_at,
                    canonical_kickoff=prediction.target_kickoff,
                    bookmaker_updated_at=market_time,
                    market_updated_at=market_time,
                ),
                _EvidenceSource(
                    evidence_id=1001 + index * 2,
                    odds_ingestion_run_id=odds.odds_ingestion_run_id,
                    provider_identity_id=provider_id,
                    game_id=prediction.game_id,
                    selection_team_id=prediction.away_team_id,
                    american_price=-105 - index,
                    trusted_observed_at=odds.response_received_at,
                    canonical_kickoff=prediction.target_kickoff,
                    bookmaker_updated_at=market_time,
                    market_updated_at=market_time,
                ),
            )
        )
    return tuple(rows)


@pytest.mark.parametrize("route", ["early", "mature"])
def test_official_early_and_mature_prediction_identity_is_eligible(route) -> None:
    prediction = _prediction()
    if route == "mature":
        prediction = replace(
            prediction,
            selected_route="mature",
            model_specification_version=MATURE_SPECIFICATION_VERSION,
            feature_schema_version=MATURE_FEATURE_SCHEMA_VERSION,
            specification_fingerprint=MATURE_SPECIFICATION_FINGERPRINT,
            model_fingerprint=MATURE_MODEL_FINGERPRINT,
        )
    _validate_prediction_source(
        prediction,
        enforce_current_eligibility=True,
    )


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"run_type": "preview"}, "prediction_ineligible"),
        ({"run_status": "running", "run_completed_at": None}, "prediction_ineligible"),
        ({"run_status": "failed", "run_completed_at": None}, "prediction_ineligible"),
        ({"protocol_version": "unknown"}, "prediction_ineligible"),
        ({"model_fingerprint": "f" * 64}, "prediction_identity_unknown"),
        ({"selected_route": "debug"}, "prediction_identity_unknown"),
        ({"current_game_status": "final"}, "game_already_played"),
    ],
)
def test_prediction_ineligibility_fails_closed(changes, code) -> None:
    with pytest.raises(OfficialMarketEvaluationError) as captured:
        _validate_prediction_source(
            _prediction(**changes),
            enforce_current_eligibility=True,
        )
    assert captured.value.code == code


@pytest.mark.parametrize(
    ("prediction_age", "accepted"),
    [
        (timedelta(microseconds=-1), False),
        (timedelta(seconds=0), False),
        (timedelta(seconds=900), True),
        (timedelta(seconds=900, microseconds=1), False),
    ],
)
def test_prediction_to_receipt_boundaries(prediction_age, accepted) -> None:
    prediction = _prediction(
        prediction_created_at=RECEIPT - prediction_age,
    )
    if accepted:
        _validate_odds_run_source(
            prediction,
            _odds(),
            enforce_current_eligibility=True,
        )
    else:
        with pytest.raises(OfficialMarketEvaluationError):
            _validate_odds_run_source(
                prediction,
                _odds(),
                enforce_current_eligibility=True,
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"sport": "baseball_mlb"},
        {"source_name": "manual"},
        {"snapshot_role": "manual"},
        {"status": "running"},
        {"request_started_at": None},
        {"response_received_at": None},
    ],
)
def test_odds_run_identity_must_be_completed_nfl_odds_api_entry(changes) -> None:
    with pytest.raises(OfficialMarketEvaluationError) as captured:
        _validate_odds_run_source(
            _prediction(),
            _odds(**changes),
            enforce_current_eligibility=True,
        )
    assert captured.value.code == "odds_run_ineligible"


@pytest.mark.parametrize(
    ("evaluation_time", "accepted"),
    [
        (RECEIPT - timedelta(microseconds=1), False),
        (RECEIPT, True),
        (RECEIPT + timedelta(seconds=300), True),
        (RECEIPT + timedelta(seconds=300, microseconds=1), False),
        (KICKOFF, False),
        (KICKOFF + timedelta(microseconds=1), False),
    ],
)
def test_database_evaluation_clock_boundaries(evaluation_time, accepted) -> None:
    if accepted:
        _validate_evaluation_clock(
            prediction=_prediction(),
            odds_run=_odds(),
            evaluation_created_at=evaluation_time,
        )
    else:
        with pytest.raises(OfficialMarketEvaluationError):
            _validate_evaluation_clock(
                prediction=_prediction(),
                odds_run=_odds(),
                evaluation_created_at=evaluation_time,
            )


@pytest.mark.parametrize("book_count", [5, 6, 9])
def test_complete_provider_counts_are_selected_deterministically(book_count) -> None:
    contributors, exclusions = _select_contributors(
        prediction=_prediction(),
        odds_run=_odds(),
        evidence=_evidence(book_count),
    )
    assert len(contributors) == book_count
    assert exclusions == ()
    assert tuple(
        item.source.provider_identity_id for item in contributors
    ) == tuple(range(100, 100 + book_count))


def test_incomplete_and_stale_providers_are_excluded() -> None:
    rows = list(_evidence(7))
    rows.pop()
    stale = rows[8]
    rows[8] = replace(
        stale,
        market_updated_at=RECEIPT - timedelta(seconds=301),
    )
    rows[9] = replace(
        rows[9],
        market_updated_at=RECEIPT - timedelta(seconds=301),
    )
    contributors, exclusions = _select_contributors(
        prediction=_prediction(),
        odds_run=_odds(),
        evidence=tuple(rows),
    )
    assert len(contributors) == 5
    assert {(item.provider_identity_id, item.reason_code) for item in exclusions} == {
        (104, "stale_market"),
        (106, "incomplete_market"),
    }


def test_duplicate_provider_selection_fails_whole_graph() -> None:
    rows = _evidence(5)
    with pytest.raises(OfficialMarketEvaluationError) as captured:
        _select_contributors(
            prediction=_prediction(),
            odds_run=_odds(),
            evidence=rows + (replace(rows[0], evidence_id=9999),),
        )
    assert captured.value.code == "ambiguous_provider_market"


def test_cross_context_and_future_provider_timestamp_fail_whole_graph() -> None:
    rows = list(_evidence(5))
    rows[0] = replace(rows[0], game_id=999)
    with pytest.raises(OfficialMarketEvaluationError) as cross_context:
        _select_contributors(
            prediction=_prediction(),
            odds_run=_odds(),
            evidence=tuple(rows),
        )
    assert cross_context.value.code == "source_graph_identity_conflict"

    rows = list(_evidence(5))
    rows[0] = replace(
        rows[0],
        bookmaker_updated_at=RECEIPT + timedelta(seconds=1),
    )
    with pytest.raises(OfficialMarketEvaluationError) as future_timestamp:
        _select_contributors(
            prediction=_prediction(),
            odds_run=_odds(),
            evidence=tuple(rows),
        )
    assert future_timestamp.value.code == "future_provider_timestamp"


def test_source_graph_fingerprint_is_stable_and_evidence_sensitive() -> None:
    contributors, exclusions = _select_contributors(
        prediction=_prediction(),
        odds_run=_odds(),
        evidence=_evidence(5),
    )
    kwargs = {
        "prediction": _prediction(),
        "odds_run": _odds(),
        "contributors": contributors,
        "exclusions": exclusions,
        "best_evidence_id": contributors[0].source.home_evidence_id,
        "best_provider_identity_id": contributors[0].source.provider_identity_id,
    }
    first = _source_graph_fingerprint(**kwargs)
    assert first == _source_graph_fingerprint(**kwargs)
    changed = dict(kwargs)
    changed["best_evidence_id"] = contributors[1].source.home_evidence_id
    assert first != _source_graph_fingerprint(**changed)
