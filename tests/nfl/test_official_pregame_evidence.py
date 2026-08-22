from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sportsmodel.nfl.official_pregame_evidence import (
    IncompatibleNflEvidenceLinkageError,
    MissingNflEventMappingError,
    MissingNflQuoteProvenanceError,
    NaiveNflEvidenceTimestampError,
    NflObservationNotPregameError,
    NflSelectionDoesNotBelongToGameError,
    OfficialNflQuoteSource,
    OfficialNflSportMismatchError,
    UnknownNflSelectionIdentityError,
    validate_official_nfl_quote_source,
)


KICKOFF = datetime(2026, 9, 11, 0, 20, tzinfo=timezone.utc)
OBSERVED = KICKOFF - timedelta(seconds=1)


def _source(**changes) -> OfficialNflQuoteSource:
    source = OfficialNflQuoteSource(
        odds_market_snapshot_id=1,
        odds_provider_event_observation_id=2,
        nfl_odds_provider_event_mapping_id=3,
        odds_ingestion_run_id=4,
        sportsbook_provider_identity_id=5,
        sportsbook_id=6,
        snapshot_game_id=7,
        mapped_game_id=7,
        market_type="h2h",
        provider_selection_name="Kansas City Chiefs",
        american_price=-145,
        line_value=Decimal("0"),
        snapshot_time=OBSERVED,
        snapshot_source_name="odds_api",
        snapshot_observed_at=OBSERVED,
        bookmaker_updated_at=OBSERVED - timedelta(seconds=2),
        market_updated_at=OBSERVED - timedelta(seconds=3),
        event_run_id=4,
        event_source_name="odds_api",
        event_sport_key="americanfootball_nfl",
        provider_commence_time=KICKOFF,
        event_observed_at=OBSERVED,
        run_sport="americanfootball_nfl",
        run_source_name="odds_api",
        run_status="completed",
        response_received_at=OBSERVED,
        identity_sportsbook_id=6,
        identity_provider_name="odds_api",
        mapping_provider_name="odds_api",
        mapping_sport_key="americanfootball_nfl",
        canonical_home_team_id=10,
        canonical_away_team_id=20,
        provider_home_team_name="Kansas City Chiefs",
        provider_away_team_name="Denver Broncos",
        current_home_team_id=10,
        current_away_team_id=20,
        current_canonical_kickoff=KICKOFF,
    )
    return replace(source, **changes)


def test_observation_one_second_before_kickoff_is_eligible() -> None:
    validate_official_nfl_quote_source(_source(), 10)


@pytest.mark.parametrize(
    "observed_at",
    [KICKOFF, KICKOFF + timedelta(seconds=1)],
)
def test_observation_at_or_after_kickoff_is_rejected(observed_at) -> None:
    source = _source(
        snapshot_time=observed_at,
        snapshot_observed_at=observed_at,
        event_observed_at=observed_at,
        response_received_at=observed_at,
    )

    with pytest.raises(NflObservationNotPregameError):
        validate_official_nfl_quote_source(source, 10)


def test_early_provider_update_cannot_make_late_observation_eligible() -> None:
    late = KICKOFF + timedelta(seconds=1)
    source = _source(
        snapshot_time=late,
        snapshot_observed_at=late,
        event_observed_at=late,
        response_received_at=late,
        bookmaker_updated_at=KICKOFF - timedelta(hours=1),
        market_updated_at=KICKOFF - timedelta(hours=1),
    )

    with pytest.raises(NflObservationNotPregameError):
        validate_official_nfl_quote_source(source, 10)


def test_provider_commence_drift_does_not_replace_canonical_kickoff() -> None:
    validate_official_nfl_quote_source(
        _source(provider_commence_time=KICKOFF + timedelta(minutes=10)),
        10,
    )


@pytest.mark.parametrize(
    ("selection_name", "selection_team_id"),
    [("Kansas City Chiefs", 10), ("Denver Broncos", 20)],
)
def test_valid_home_and_away_canonical_selections(selection_name, selection_team_id) -> None:
    validate_official_nfl_quote_source(
        _source(provider_selection_name=selection_name),
        selection_team_id,
    )


def test_third_provider_selection_is_rejected() -> None:
    with pytest.raises(UnknownNflSelectionIdentityError):
        validate_official_nfl_quote_source(
            _source(provider_selection_name="Las Vegas Raiders"),
            10,
        )


def test_wrong_canonical_selection_team_is_rejected() -> None:
    with pytest.raises(NflSelectionDoesNotBelongToGameError):
        validate_official_nfl_quote_source(_source(), 20)


def test_wrong_canonical_game_linkage_is_rejected() -> None:
    with pytest.raises(IncompatibleNflEvidenceLinkageError):
        validate_official_nfl_quote_source(_source(snapshot_game_id=999), 10)


def test_missing_provider_event_mapping_is_rejected() -> None:
    with pytest.raises(MissingNflEventMappingError):
        validate_official_nfl_quote_source(
            _source(
                nfl_odds_provider_event_mapping_id=None,
                mapped_game_id=None,
            ),
            10,
        )


def test_missing_phase_4a2_provenance_is_rejected() -> None:
    with pytest.raises(MissingNflQuoteProvenanceError):
        validate_official_nfl_quote_source(
            _source(odds_provider_event_observation_id=None),
            10,
        )


def test_sport_mismatch_is_rejected() -> None:
    with pytest.raises(OfficialNflSportMismatchError):
        validate_official_nfl_quote_source(_source(run_sport="baseball_mlb"), 10)


def test_conflicting_source_observation_facts_are_rejected() -> None:
    with pytest.raises(IncompatibleNflEvidenceLinkageError):
        validate_official_nfl_quote_source(
            _source(event_observed_at=OBSERVED - timedelta(seconds=1)),
            10,
        )


def test_kickoff_changed_before_qualification_uses_current_value() -> None:
    with pytest.raises(NflObservationNotPregameError):
        validate_official_nfl_quote_source(
            _source(current_canonical_kickoff=OBSERVED),
            10,
        )


def test_naive_timestamp_is_rejected() -> None:
    naive = OBSERVED.replace(tzinfo=None)
    source = _source(
        snapshot_time=naive,
        snapshot_observed_at=naive,
        event_observed_at=naive,
        response_received_at=naive,
    )

    with pytest.raises(NaiveNflEvidenceTimestampError):
        validate_official_nfl_quote_source(source, 10)
