"""Immutable official-pregame qualification for NFL quote snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


NFL_SPORT_KEY = "americanfootball_nfl"
ODDS_API_PROVIDER_NAME = "odds_api"


class OfficialNflPregameEvidenceError(ValueError):
    """Base class for fail-closed official NFL evidence validation."""


class NflQuoteNotFoundError(OfficialNflPregameEvidenceError):
    pass


class MissingNflQuoteProvenanceError(OfficialNflPregameEvidenceError):
    pass


class MissingNflEventMappingError(OfficialNflPregameEvidenceError):
    pass


class OfficialNflSportMismatchError(OfficialNflPregameEvidenceError):
    pass


class IncompatibleNflEvidenceLinkageError(OfficialNflPregameEvidenceError):
    pass


class UnknownNflSelectionIdentityError(OfficialNflPregameEvidenceError):
    pass


class NflSelectionDoesNotBelongToGameError(OfficialNflPregameEvidenceError):
    pass


class NflObservationNotPregameError(OfficialNflPregameEvidenceError):
    pass


class NaiveNflEvidenceTimestampError(OfficialNflPregameEvidenceError):
    pass


class ConflictingOfficialNflEvidenceError(OfficialNflPregameEvidenceError):
    pass


@dataclass(frozen=True)
class OfficialNflQuoteSource:
    odds_market_snapshot_id: int
    odds_provider_event_observation_id: int | None
    nfl_odds_provider_event_mapping_id: int | None
    odds_ingestion_run_id: int | None
    sportsbook_provider_identity_id: int | None
    sportsbook_id: int | None
    snapshot_game_id: int
    mapped_game_id: int | None
    market_type: str
    provider_selection_name: str
    american_price: int
    line_value: Decimal | None
    snapshot_time: datetime
    snapshot_source_name: str
    snapshot_observed_at: datetime | None
    bookmaker_updated_at: datetime | None
    market_updated_at: datetime | None
    event_run_id: int | None
    event_source_name: str | None
    event_sport_key: str | None
    provider_commence_time: datetime | None
    event_observed_at: datetime | None
    run_sport: str | None
    run_source_name: str | None
    run_status: str | None
    response_received_at: datetime | None
    identity_sportsbook_id: int | None
    identity_provider_name: str | None
    mapping_provider_name: str | None
    mapping_sport_key: str | None
    canonical_home_team_id: int | None
    canonical_away_team_id: int | None
    provider_home_team_name: str | None
    provider_away_team_name: str | None
    current_home_team_id: int | None
    current_away_team_id: int | None
    current_canonical_kickoff: datetime | None


@dataclass(frozen=True)
class OfficialNflPregameEvidence:
    nfl_official_pregame_evidence_id: int
    odds_market_snapshot_id: int
    odds_provider_event_observation_id: int
    nfl_odds_provider_event_mapping_id: int
    odds_ingestion_run_id: int
    sportsbook_provider_identity_id: int
    sportsbook_id: int
    game_id: int
    canonical_selection_team_id: int
    provider_selection_name: str
    market_type: str
    american_price: int
    line_value: Decimal | None
    trusted_observed_at: datetime
    canonical_kickoff_at_qualification: datetime
    provider_commence_time: datetime
    bookmaker_updated_at: datetime | None
    market_updated_at: datetime | None
    qualified_at: datetime


def create_official_nfl_pregame_evidence(
    cursor: Any,
    *,
    odds_market_snapshot_id: int,
    canonical_selection_team_id: int,
) -> OfficialNflPregameEvidence:
    """Qualify one existing provenance-bearing quote as official NFL evidence.

    The trusted quote observation time must be strictly before the current
    canonical kickoff. The database repeats the critical validation and copies
    the qualifying kickoff and source facts into an immutable row.
    """

    existing = _load_existing_evidence(cursor, odds_market_snapshot_id)
    if existing is not None:
        if existing.canonical_selection_team_id != canonical_selection_team_id:
            raise ConflictingOfficialNflEvidenceError(
                "quote snapshot is already official for a different canonical selection"
            )
        return existing

    source = _load_quote_source(cursor, odds_market_snapshot_id)
    validate_official_nfl_quote_source(source, canonical_selection_team_id)

    cursor.execute(
        """
        INSERT INTO nfl_official_pregame_evidence (
            odds_market_snapshot_id,
            canonical_selection_team_id
        )
        VALUES (%s, %s)
        ON CONFLICT (odds_market_snapshot_id) DO NOTHING
        RETURNING
            nfl_official_pregame_evidence_id,
            odds_market_snapshot_id,
            odds_provider_event_observation_id,
            nfl_odds_provider_event_mapping_id,
            odds_ingestion_run_id,
            sportsbook_provider_identity_id,
            sportsbook_id,
            game_id,
            canonical_selection_team_id,
            provider_selection_name,
            market_type,
            american_price,
            line_value,
            trusted_observed_at,
            canonical_kickoff_at_qualification,
            provider_commence_time,
            bookmaker_updated_at,
            market_updated_at,
            qualified_at
        """,
        (odds_market_snapshot_id, canonical_selection_team_id),
    )
    inserted = cursor.fetchone()
    if inserted is not None:
        return _evidence_from_row(inserted)

    raced = _load_existing_evidence(cursor, odds_market_snapshot_id)
    if raced is None:
        raise RuntimeError("official NFL evidence disappeared during idempotent insert")
    if raced.canonical_selection_team_id != canonical_selection_team_id:
        raise ConflictingOfficialNflEvidenceError(
            "quote snapshot concurrently became official for another selection"
        )
    return raced


def validate_official_nfl_quote_source(
    source: OfficialNflQuoteSource,
    canonical_selection_team_id: int,
) -> None:
    """Validate the service-level official NFL quote contract without writes."""

    if (
        source.odds_provider_event_observation_id is None
        or source.odds_ingestion_run_id is None
        or source.sportsbook_provider_identity_id is None
        or source.sportsbook_id is None
        or source.snapshot_observed_at is None
    ):
        raise MissingNflQuoteProvenanceError(
            "official NFL evidence requires complete Phase 4A2 quote provenance"
        )
    if (
        source.nfl_odds_provider_event_mapping_id is None
        or source.mapped_game_id is None
    ):
        raise MissingNflEventMappingError(
            "official NFL evidence requires a Phase 4A3 canonical event mapping"
        )
    if (
        source.run_sport != NFL_SPORT_KEY
        or source.event_sport_key != NFL_SPORT_KEY
        or source.mapping_sport_key != NFL_SPORT_KEY
        or source.run_source_name != ODDS_API_PROVIDER_NAME
        or source.event_source_name != ODDS_API_PROVIDER_NAME
        or source.snapshot_source_name != ODDS_API_PROVIDER_NAME
        or source.mapping_provider_name != ODDS_API_PROVIDER_NAME
        or source.identity_provider_name != ODDS_API_PROVIDER_NAME
    ):
        raise OfficialNflSportMismatchError(
            "official NFL evidence requires coherent Odds API NFL source identity"
        )
    if source.run_status != "completed" or source.response_received_at is None:
        raise MissingNflQuoteProvenanceError(
            "official NFL evidence requires a completed provenance-bearing run"
        )
    if (
        source.event_run_id != source.odds_ingestion_run_id
        or source.event_observed_at != source.response_received_at
        or source.snapshot_observed_at != source.event_observed_at
        or source.snapshot_time != source.snapshot_observed_at
        or source.identity_sportsbook_id != source.sportsbook_id
    ):
        raise IncompatibleNflEvidenceLinkageError(
            "run, event, book, and observation provenance are incompatible"
        )
    if (
        source.snapshot_game_id != source.mapped_game_id
        or source.current_home_team_id != source.canonical_home_team_id
        or source.current_away_team_id != source.canonical_away_team_id
    ):
        raise IncompatibleNflEvidenceLinkageError(
            "quote, mapping, and canonical NFL game identities are incompatible"
        )
    if source.market_type != "h2h":
        raise UnknownNflSelectionIdentityError(
            "official NFL evidence supports only H2H selections"
        )

    if source.provider_selection_name == source.provider_home_team_name:
        expected_team_id = source.canonical_home_team_id
    elif source.provider_selection_name == source.provider_away_team_name:
        expected_team_id = source.canonical_away_team_id
    else:
        raise UnknownNflSelectionIdentityError(
            "provider selection does not match either mapped NFL team"
        )
    if canonical_selection_team_id != expected_team_id:
        raise NflSelectionDoesNotBelongToGameError(
            "canonical selection team does not match the provider selection and game"
        )

    required_timestamps = (
        ("snapshot_time", source.snapshot_time),
        ("snapshot_observed_at", source.snapshot_observed_at),
        ("event_observed_at", source.event_observed_at),
        ("response_received_at", source.response_received_at),
        ("provider_commence_time", source.provider_commence_time),
        ("current_canonical_kickoff", source.current_canonical_kickoff),
    )
    optional_timestamps = (
        ("bookmaker_updated_at", source.bookmaker_updated_at),
        ("market_updated_at", source.market_updated_at),
    )
    for field_name, value in required_timestamps:
        if value is None or value.tzinfo is None or value.utcoffset() is None:
            raise NaiveNflEvidenceTimestampError(
                f"{field_name} must be a timezone-aware timestamp"
            )
    for field_name, value in optional_timestamps:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise NaiveNflEvidenceTimestampError(
                f"{field_name} must be timezone-aware when present"
            )

    assert source.snapshot_observed_at is not None
    assert source.current_canonical_kickoff is not None
    if source.snapshot_observed_at >= source.current_canonical_kickoff:
        raise NflObservationNotPregameError(
            "trusted SportsModel observation time must be strictly before canonical kickoff"
        )


def _load_quote_source(cursor: Any, odds_market_snapshot_id: int) -> OfficialNflQuoteSource:
    cursor.execute(
        """
        SELECT
            snapshot.odds_market_snapshot_id,
            snapshot.odds_provider_event_observation_id,
            event.nfl_odds_provider_event_mapping_id,
            snapshot.odds_ingestion_run_id,
            snapshot.sportsbook_provider_identity_id,
            snapshot.sportsbook_id,
            snapshot.game_id,
            mapping.game_id,
            snapshot.market_type,
            snapshot.selection_name,
            snapshot.price,
            snapshot.line_value,
            snapshot.snapshot_time,
            snapshot.source_name,
            snapshot.observed_at,
            snapshot.bookmaker_updated_at,
            snapshot.market_updated_at,
            event.odds_ingestion_run_id,
            event.source_name,
            event.provider_sport_key,
            event.provider_commence_time,
            event.observed_at,
            run.sport,
            run.source_name,
            run.status,
            run.response_received_at,
            identity.sportsbook_id,
            identity.provider_name,
            mapping.provider_name,
            mapping.provider_sport_key,
            mapping.canonical_home_team_id,
            mapping.canonical_away_team_id,
            mapping.provider_home_team_name,
            mapping.provider_away_team_name,
            game.home_team_id,
            game.away_team_id,
            nfl.scheduled_start_time
        FROM odds_market_snapshots AS snapshot
        LEFT JOIN odds_provider_event_observations AS event
          ON event.odds_provider_event_observation_id
            = snapshot.odds_provider_event_observation_id
        LEFT JOIN odds_ingestion_runs AS run
          ON run.odds_ingestion_run_id = snapshot.odds_ingestion_run_id
        LEFT JOIN sportsbook_provider_identities AS identity
          ON identity.sportsbook_provider_identity_id
            = snapshot.sportsbook_provider_identity_id
        LEFT JOIN nfl_odds_provider_event_mappings AS mapping
          ON mapping.nfl_odds_provider_event_mapping_id
            = event.nfl_odds_provider_event_mapping_id
        LEFT JOIN games AS game ON game.game_id = mapping.game_id
        LEFT JOIN nfl_games AS nfl ON nfl.game_id = mapping.game_id
        WHERE snapshot.odds_market_snapshot_id = %s
        """,
        (odds_market_snapshot_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise NflQuoteNotFoundError(
            f"odds snapshot {odds_market_snapshot_id} does not exist"
        )
    return OfficialNflQuoteSource(*row)


def _load_existing_evidence(
    cursor: Any, odds_market_snapshot_id: int
) -> OfficialNflPregameEvidence | None:
    cursor.execute(
        """
        SELECT
            nfl_official_pregame_evidence_id,
            odds_market_snapshot_id,
            odds_provider_event_observation_id,
            nfl_odds_provider_event_mapping_id,
            odds_ingestion_run_id,
            sportsbook_provider_identity_id,
            sportsbook_id,
            game_id,
            canonical_selection_team_id,
            provider_selection_name,
            market_type,
            american_price,
            line_value,
            trusted_observed_at,
            canonical_kickoff_at_qualification,
            provider_commence_time,
            bookmaker_updated_at,
            market_updated_at,
            qualified_at
        FROM nfl_official_pregame_evidence
        WHERE odds_market_snapshot_id = %s
        """,
        (odds_market_snapshot_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _evidence_from_row(row)


def _evidence_from_row(row: tuple[Any, ...]) -> OfficialNflPregameEvidence:
    return OfficialNflPregameEvidence(*row)
