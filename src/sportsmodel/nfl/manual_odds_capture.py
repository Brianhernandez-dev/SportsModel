"""Manual, one-request NFL Odds API capture orchestration.

The transport is injected so the complete workflow can be rehearsed offline.
This module never retries a provider request. Raw capture and official pregame
qualification stop before any market analytics or betting logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Any, Callable, Mapping

import requests

from sportsmodel.ingest.odds_api_parser import (
    OddsApiEvent,
    parse_odds_api_h2h_response,
)
from sportsmodel.ingest.odds_provenance import (
    create_provider_event_observation,
    resolve_provider_sportsbook,
)
from sportsmodel.nfl.odds_identity import (
    ResolvedNflOddsEvent,
    resolve_and_persist_nfl_odds_event,
)
from sportsmodel.nfl.official_pregame_evidence import (
    NflObservationNotPregameError,
    create_official_nfl_pregame_evidence,
)


NFL_SPORT_KEY = "americanfootball_nfl"
PROVIDER_NAME = "odds_api"
REGIONS = "us"
MARKETS = "h2h"
ODDS_FORMAT = "american"
SNAPSHOT_ROLE = "entry"
MINIMUM_SCHEMA_VERSION = 30
REQUEST_PATH = f"/v4/sports/{NFL_SPORT_KEY}/odds"
ODDS_API_URL = f"https://api.the-odds-api.com/v4/sports/{NFL_SPORT_KEY}/odds"


class NflCaptureError(RuntimeError):
    """Base class for a fail-closed manual NFL capture error."""


class NflCaptureSchemaError(NflCaptureError):
    pass


class NflCaptureScheduleError(NflCaptureError):
    pass


class DuplicateNflCaptureReservationError(NflCaptureError):
    pass


class NflProviderResponseError(NflCaptureError):
    pass


class NflCaptureProcessingError(NflCaptureError):
    def __init__(self, ingestion_run_id: int, stage: str, cause: Exception) -> None:
        self.ingestion_run_id = ingestion_run_id
        self.stage = stage
        super().__init__(
            f"NFL capture run {ingestion_run_id} failed during {stage}: "
            f"{type(cause).__name__}: {cause}"
        )


class NflCaptureQualificationError(NflCaptureError):
    def __init__(self, ingestion_run_id: int, cause: Exception) -> None:
        self.ingestion_run_id = ingestion_run_id
        super().__init__(
            f"NFL capture run {ingestion_run_id} retained raw evidence but "
            f"official qualification failed: {type(cause).__name__}: {cause}. "
            "Retry qualification from the retained snapshots; do not call the "
            "provider again."
        )


@dataclass(frozen=True)
class NflProviderRequest:
    sport_key: str
    regions: str
    markets: str
    odds_format: str
    commence_time_from: datetime
    commence_time_to: datetime


@dataclass(frozen=True)
class NflProviderResponse:
    status_code: int
    headers: Mapping[str, str]
    body: str


@dataclass(frozen=True)
class NflCaptureAudit:
    odds_ingestion_run_id: int
    target_date: date
    status_code: int
    remaining_requests: int | None
    used_requests: int | None
    games_returned: int
    games_processed: int
    provider_event_observation_ids: tuple[int, ...]
    provider_event_mapping_ids: tuple[int, ...]
    sportsbook_provider_identity_ids: tuple[int, ...]
    raw_snapshot_ids: tuple[int, ...]
    official_pregame_evidence_ids: tuple[int, ...]
    official_pregame_skipped: int

    @property
    def selections_inserted(self) -> int:
        return len(self.raw_snapshot_ids)


ProviderCall = Callable[[NflProviderRequest], NflProviderResponse]


def utc_target_date_window(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def call_odds_api_once(
    request: NflProviderRequest,
    *,
    api_key: str,
) -> NflProviderResponse:
    """Make exactly one HTTP invocation with no retry configuration."""

    if not api_key:
        raise ValueError("Odds API key must be present for live capture")
    _validate_request_contract(request)
    response = requests.get(
        ODDS_API_URL,
        params={
            "apiKey": api_key,
            "regions": request.regions,
            "markets": request.markets,
            "oddsFormat": request.odds_format,
            "commenceTimeFrom": _format_api_timestamp(request.commence_time_from),
            "commenceTimeTo": _format_api_timestamp(request.commence_time_to),
        },
        timeout=30,
        allow_redirects=False,
    )
    return NflProviderResponse(
        status_code=response.status_code,
        headers=dict(response.headers),
        body=response.text,
    )


def validate_nfl_capture_schema(cursor: Any) -> int:
    cursor.execute("SELECT MAX(version) FROM schema_migrations")
    highest = cursor.fetchone()[0]
    if highest is None or int(highest) < MINIMUM_SCHEMA_VERSION:
        raise NflCaptureSchemaError(
            f"NFL capture requires schema migration {MINIMUM_SCHEMA_VERSION:03d}; "
            f"highest applied is {highest!r}"
        )
    cursor.execute(
        """
        SELECT
            to_regclass('public.nfl_odds_provider_event_mappings'),
            to_regclass('public.nfl_official_pregame_evidence')
        """
    )
    if any(value is None for value in cursor.fetchone()):
        raise NflCaptureSchemaError(
            "NFL capture requires Phase 4A3 and Phase 4A4 production tables"
        )
    return int(highest)


def validate_nfl_capture_schedule(
    cursor: Any,
    *,
    commence_time_from: datetime,
    commence_time_to: datetime,
) -> tuple[int, ...]:
    _require_aware(commence_time_from, "commence_time_from")
    _require_aware(commence_time_to, "commence_time_to")
    if commence_time_from >= commence_time_to:
        raise ValueError("NFL capture window must be a non-empty half-open interval")
    cursor.execute(
        """
        SELECT nfl.game_id
        FROM nfl_games AS nfl
        JOIN games AS game ON game.game_id = nfl.game_id
        WHERE nfl.status = 'unplayed'
          AND nfl.scheduled_start_time >= %s
          AND nfl.scheduled_start_time < %s
          AND nfl.scheduled_start_time > clock_timestamp()
          AND game.home_team_id <> game.away_team_id
        ORDER BY nfl.scheduled_start_time, nfl.game_id
        """,
        (commence_time_from, commence_time_to),
    )
    game_ids = tuple(int(row[0]) for row in cursor.fetchall())
    if not game_ids:
        raise NflCaptureScheduleError(
            "no future unplayed canonical NFL games exist in the requested UTC window"
        )
    return game_ids


def reserve_nfl_capture_run(
    connection: Any,
    *,
    target_date: date,
    request: NflProviderRequest,
) -> int:
    """Reserve the unique NFL entry capture before any provider invocation."""

    _validate_request_contract(request, target_date=target_date)
    with connection.cursor() as cursor:
        validate_nfl_capture_schema(cursor)
        validate_nfl_capture_schedule(
            cursor,
            commence_time_from=request.commence_time_from,
            commence_time_to=request.commence_time_to,
        )
        cursor.execute(
            """
            INSERT INTO odds_ingestion_runs (
                sport,
                source_name,
                target_date,
                snapshot_role,
                request_path,
                request_regions,
                request_markets,
                request_odds_format,
                request_commence_time_from,
                request_commence_time_to,
                request_started_at,
                status
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                clock_timestamp(), 'running'
            )
            ON CONFLICT DO NOTHING
            RETURNING odds_ingestion_run_id
            """,
            (
                NFL_SPORT_KEY,
                PROVIDER_NAME,
                target_date,
                SNAPSHOT_ROLE,
                REQUEST_PATH,
                REGIONS,
                MARKETS,
                ODDS_FORMAT,
                request.commence_time_from,
                request.commence_time_to,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        connection.rollback()
        raise DuplicateNflCaptureReservationError(
            f"an active or completed NFL entry capture already exists for {target_date}"
        )
    connection.commit()
    return int(row[0])


def execute_manual_nfl_capture(
    connection: Any,
    *,
    target_date: date,
    provider_call: ProviderCall,
) -> NflCaptureAudit:
    """Execute one reserved NFL H2H capture and never retry the provider call."""

    window_start, window_end = utc_target_date_window(target_date)
    request = NflProviderRequest(
        sport_key=NFL_SPORT_KEY,
        regions=REGIONS,
        markets=MARKETS,
        odds_format=ODDS_FORMAT,
        commence_time_from=window_start,
        commence_time_to=window_end - timedelta(seconds=1),
    )
    run_id = reserve_nfl_capture_run(
        connection,
        target_date=target_date,
        request=request,
    )

    try:
        response = provider_call(request)
    except Exception as error:
        _mark_run_failed(connection, run_id, error, stage="provider_call")
        raise NflCaptureProcessingError(run_id, "provider_call", error) from error

    remaining_requests = _quota_header(response.headers, "x-requests-remaining")
    used_requests = _quota_header(response.headers, "x-requests-used")
    try:
        observed_at = _record_response_once(
            connection,
            ingestion_run_id=run_id,
            status_code=response.status_code,
            remaining_requests=remaining_requests,
            used_requests=used_requests,
        )
    except Exception as error:
        _mark_run_failed(
            connection,
            run_id,
            error,
            stage="response_persistence",
            status_code=response.status_code,
            remaining_requests=remaining_requests,
            used_requests=used_requests,
        )
        raise NflCaptureProcessingError(
            run_id,
            "response_persistence",
            error,
        ) from error

    if response.status_code != 200:
        error = NflProviderResponseError(
            f"Odds API response status was {response.status_code}"
        )
        _mark_run_failed(
            connection,
            run_id,
            error,
            stage="provider_response",
            status_code=response.status_code,
            remaining_requests=remaining_requests,
            used_requests=used_requests,
        )
        raise NflCaptureProcessingError(run_id, "provider_response", error)

    try:
        payload = json.loads(response.body)
        events = parse_odds_api_h2h_response(
            payload,
            expected_sport_key=NFL_SPORT_KEY,
        )
        _validate_response_window(events, request)
    except Exception as error:
        _mark_run_failed(
            connection,
            run_id,
            error,
            stage="parse",
            status_code=response.status_code,
            remaining_requests=remaining_requests,
            used_requests=used_requests,
            games_returned=(len(payload) if isinstance(payload, list) else 0)
            if "payload" in locals()
            else 0,
        )
        raise NflCaptureProcessingError(run_id, "parse", error) from error

    try:
        persisted = _persist_capture_payload(
            connection,
            ingestion_run_id=run_id,
            events=events,
            observed_at=observed_at,
            status_code=response.status_code,
            remaining_requests=remaining_requests,
            used_requests=used_requests,
        )
    except Exception as error:
        connection.rollback()
        _mark_run_failed(
            connection,
            run_id,
            error,
            stage="persistence",
            status_code=response.status_code,
            remaining_requests=remaining_requests,
            used_requests=used_requests,
            games_returned=len(events),
        )
        raise NflCaptureProcessingError(run_id, "persistence", error) from error

    try:
        evidence_ids: list[int] = []
        pregame_skipped = 0
        with connection.cursor() as cursor:
            for snapshot_id, selection_team_id in persisted.snapshot_selections:
                try:
                    evidence = create_official_nfl_pregame_evidence(
                        cursor,
                        odds_market_snapshot_id=snapshot_id,
                        canonical_selection_team_id=selection_team_id,
                    )
                except NflObservationNotPregameError:
                    pregame_skipped += 1
                    continue
                evidence_ids.append(evidence.nfl_official_pregame_evidence_id)
        connection.commit()
    except Exception as error:
        connection.rollback()
        raise NflCaptureQualificationError(run_id, error) from error

    return NflCaptureAudit(
        odds_ingestion_run_id=run_id,
        target_date=target_date,
        status_code=response.status_code,
        remaining_requests=remaining_requests,
        used_requests=used_requests,
        games_returned=len(events),
        games_processed=len(persisted.event_observation_ids),
        provider_event_observation_ids=persisted.event_observation_ids,
        provider_event_mapping_ids=persisted.mapping_ids,
        sportsbook_provider_identity_ids=persisted.sportsbook_identity_ids,
        raw_snapshot_ids=tuple(item[0] for item in persisted.snapshot_selections),
        official_pregame_evidence_ids=tuple(evidence_ids),
        official_pregame_skipped=pregame_skipped,
    )


@dataclass(frozen=True)
class _PersistedCapture:
    event_observation_ids: tuple[int, ...]
    mapping_ids: tuple[int, ...]
    sportsbook_identity_ids: tuple[int, ...]
    snapshot_selections: tuple[tuple[int, int], ...]


def _persist_capture_payload(
    connection: Any,
    *,
    ingestion_run_id: int,
    events: tuple[OddsApiEvent, ...],
    observed_at: datetime,
    status_code: int,
    remaining_requests: int | None,
    used_requests: int | None,
) -> _PersistedCapture:
    event_ids: list[int] = []
    mapping_ids: set[int] = set()
    sportsbook_ids: set[int] = set()
    snapshot_selections: list[tuple[int, int]] = []

    with connection.cursor() as cursor:
        for event in events:
            resolution = resolve_and_persist_nfl_odds_event(cursor, event)
            assert resolution.provider_event_mapping_id is not None
            mapping_ids.add(resolution.provider_event_mapping_id)
            event_observation_id = create_provider_event_observation(
                cursor,
                ingestion_run_id=ingestion_run_id,
                provider_name=PROVIDER_NAME,
                event=event,
                observed_at=observed_at,
                nfl_provider_event_mapping_id=resolution.provider_event_mapping_id,
            )
            event_ids.append(event_observation_id)

            for bookmaker in event.bookmakers:
                identity = resolve_provider_sportsbook(
                    cursor,
                    provider_name=PROVIDER_NAME,
                    provider_bookmaker_key=bookmaker.bookmaker_key,
                    bookmaker_title=bookmaker.title,
                )
                sportsbook_ids.add(identity.sportsbook_provider_identity_id)
                market = bookmaker.markets[0]
                for outcome in market.outcomes:
                    selection_team_id = _canonical_selection_team_id(
                        resolution,
                        outcome.selection_name,
                    )
                    cursor.execute(
                        """
                        INSERT INTO odds_market_snapshots (
                            odds_ingestion_run_id,
                            odds_provider_event_observation_id,
                            game_id,
                            sportsbook_provider_identity_id,
                            sportsbook_id,
                            market_type,
                            selection_name,
                            line_value,
                            price,
                            snapshot_time,
                            source_name,
                            bookmaker_title_at_observation,
                            bookmaker_updated_at,
                            market_updated_at,
                            observed_at
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s
                        )
                        RETURNING odds_market_snapshot_id
                        """,
                        (
                            ingestion_run_id,
                            event_observation_id,
                            resolution.game_id,
                            identity.sportsbook_provider_identity_id,
                            identity.sportsbook_id,
                            market.market_key,
                            outcome.selection_name,
                            outcome.line_value,
                            outcome.american_price,
                            observed_at,
                            PROVIDER_NAME,
                            bookmaker.title,
                            bookmaker.last_update,
                            market.last_update,
                            observed_at,
                        ),
                    )
                    snapshot_selections.append(
                        (int(cursor.fetchone()[0]), selection_team_id)
                    )

        cursor.execute(
            """
            UPDATE odds_ingestion_runs
            SET completed_at = clock_timestamp(),
                status = 'completed',
                status_code = %s,
                remaining_requests = %s,
                used_requests = %s,
                games_returned = %s,
                games_processed = %s,
                selections_inserted = %s,
                selections_skipped = 0,
                error_message = NULL
            WHERE odds_ingestion_run_id = %s
              AND status = 'running'
            """,
            (
                status_code,
                remaining_requests,
                used_requests,
                len(events),
                len(event_ids),
                len(snapshot_selections),
                ingestion_run_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("NFL capture run could not transition to completed")
    connection.commit()
    return _PersistedCapture(
        event_observation_ids=tuple(event_ids),
        mapping_ids=tuple(sorted(mapping_ids)),
        sportsbook_identity_ids=tuple(sorted(sportsbook_ids)),
        snapshot_selections=tuple(snapshot_selections),
    )


def _record_response_once(
    connection: Any,
    *,
    ingestion_run_id: int,
    status_code: int,
    remaining_requests: int | None,
    used_requests: int | None,
) -> datetime:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE odds_ingestion_runs
            SET response_received_at = clock_timestamp(),
                status_code = %s,
                remaining_requests = %s,
                used_requests = %s
            WHERE odds_ingestion_run_id = %s
              AND status = 'running'
              AND response_received_at IS NULL
            RETURNING response_received_at
            """,
            (
                status_code,
                remaining_requests,
                used_requests,
                ingestion_run_id,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        connection.rollback()
        raise RuntimeError("NFL provider response metadata was already recorded")
    connection.commit()
    return row[0]


def _mark_run_failed(
    connection: Any,
    ingestion_run_id: int,
    error: Exception,
    *,
    stage: str,
    status_code: int | None = None,
    remaining_requests: int | None = None,
    used_requests: int | None = None,
    games_returned: int = 0,
) -> None:
    connection.rollback()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE odds_ingestion_runs
            SET completed_at = clock_timestamp(),
                status = 'failed',
                status_code = COALESCE(status_code, %s),
                remaining_requests = COALESCE(remaining_requests, %s),
                used_requests = COALESCE(used_requests, %s),
                games_returned = %s,
                games_processed = 0,
                selections_inserted = 0,
                selections_skipped = 0,
                error_message = %s
            WHERE odds_ingestion_run_id = %s
              AND status = 'running'
            """,
            (
                status_code,
                remaining_requests,
                used_requests,
                games_returned,
                f"{stage}: {type(error).__name__}: {error}"[:2000],
                ingestion_run_id,
            ),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError(
                f"NFL capture run {ingestion_run_id} could not be marked failed"
            )
    connection.commit()


def _canonical_selection_team_id(
    resolution: ResolvedNflOddsEvent,
    provider_selection_name: str,
) -> int:
    if provider_selection_name == resolution.home_selection.provider_selection_name:
        return resolution.home_selection.team_id
    if provider_selection_name == resolution.away_selection.provider_selection_name:
        return resolution.away_selection.team_id
    raise ValueError(
        f"provider selection {provider_selection_name!r} has no canonical NFL identity"
    )


def _validate_response_window(
    events: tuple[OddsApiEvent, ...],
    request: NflProviderRequest,
) -> None:
    for event in events:
        if not (
            request.commence_time_from
            <= event.commence_time
            <= request.commence_time_to
        ):
            raise ValueError(
                f"provider event {event.event_id!r} is outside the requested window"
            )


def _validate_request_contract(
    request: NflProviderRequest,
    *,
    target_date: date | None = None,
) -> None:
    expected = (NFL_SPORT_KEY, REGIONS, MARKETS, ODDS_FORMAT)
    actual = (
        request.sport_key,
        request.regions,
        request.markets,
        request.odds_format,
    )
    if actual != expected:
        raise ValueError(
            "manual NFL capture requires exactly "
            f"sport={NFL_SPORT_KEY}, regions={REGIONS}, markets={MARKETS}, "
            f"odds_format={ODDS_FORMAT}"
        )
    _require_aware(request.commence_time_from, "commence_time_from")
    _require_aware(request.commence_time_to, "commence_time_to")
    if target_date is not None:
        expected_start, expected_end = utc_target_date_window(target_date)
        if (
            request.commence_time_from != expected_start
            or request.commence_time_to != expected_end - timedelta(seconds=1)
        ):
            raise ValueError(
                "manual NFL capture request window must match the target UTC date"
            )


def _quota_header(headers: Mapping[str, str], name: str) -> int | None:
    normalized = {key.lower(): value for key, value in headers.items()}
    value = normalized.get(name.lower())
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _format_api_timestamp(value: datetime) -> str:
    _require_aware(value, "provider request timestamp")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
