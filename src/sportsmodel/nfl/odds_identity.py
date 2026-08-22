"""Strict, offline NFL identity resolution for parsed Odds API events.

This module maps provider team names and event metadata to identities that
already exist in the canonical NFL tables.  It deliberately does not create
teams or games, fetch odds, determine pregame eligibility, or calculate any
market-derived value.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from sportsmodel.ingest.odds_api_parser import OddsApiEvent


ODDS_API_PROVIDER_NAME = "odds_api"
NFL_ODDS_SPORT_KEY = "americanfootball_nfl"
NFL_ODDS_KICKOFF_TOLERANCE = timedelta(minutes=15)


class NflKickoffMatchKind(StrEnum):
    EXACT = "exact"
    ACCEPTABLE_DRIFT = "acceptable_drift"


@dataclass(frozen=True)
class CanonicalNflProviderTeam:
    team_id: int
    current_abbreviation: str
    provider_team_name: str


@dataclass(frozen=True)
class CanonicalNflSelection:
    provider_selection_name: str
    team_id: int
    side: str


@dataclass(frozen=True)
class ResolvedNflOddsEvent:
    provider_event_mapping_id: int | None
    provider_name: str
    provider_sport_key: str
    external_event_id: str
    game_id: int
    canonical_home_team_id: int
    canonical_away_team_id: int
    provider_home_team_name: str
    provider_away_team_name: str
    canonical_kickoff: datetime
    provider_commence_time: datetime
    kickoff_drift_seconds: float
    kickoff_match_kind: NflKickoffMatchKind
    home_selection: CanonicalNflSelection
    away_selection: CanonicalNflSelection


@dataclass(frozen=True)
class _CanonicalGameCandidate:
    game_id: int
    scheduled_start_time: datetime
    home_team_id: int
    away_team_id: int
    status: str


@dataclass(frozen=True)
class _ExistingMapping:
    mapping_id: int
    game_id: int
    canonical_home_team_id: int
    canonical_away_team_id: int
    provider_home_team_name: str
    provider_away_team_name: str
    canonical_kickoff: datetime
    current_kickoff: datetime
    status: str
    current_home_team_id: int
    current_away_team_id: int


class NflOddsIdentityError(ValueError):
    """Base class for a fail-closed NFL provider identity error."""


class UnsupportedNflOddsSportError(NflOddsIdentityError):
    pass


class UnknownNflTeamIdentityError(NflOddsIdentityError):
    pass


class AmbiguousNflTeamIdentityError(NflOddsIdentityError):
    pass


class SameNflTeamIdentityError(NflOddsIdentityError):
    pass


class CanonicalNflGameNotFoundError(NflOddsIdentityError):
    pass


class AmbiguousNflGameMatchError(NflOddsIdentityError):
    pass


class ReversedNflMatchupError(NflOddsIdentityError):
    pass


class UnacceptableNflKickoffDriftError(NflOddsIdentityError):
    pass


class CanonicalNflGameStatusError(NflOddsIdentityError):
    pass


class MalformedNflProviderKickoffError(NflOddsIdentityError):
    pass


class NflProviderEventConflictError(NflOddsIdentityError):
    pass


class NflSelectionIdentityError(NflOddsIdentityError):
    pass


def resolve_nfl_odds_event(cursor: Any, event: OddsApiEvent) -> ResolvedNflOddsEvent:
    """Resolve one parsed NFL event to existing canonical identities.

    Resolution is exact for provider team names and home/away orientation.  A
    canonical kickoff may differ from the provider commence time by at most 15
    minutes.  Exact matches and accepted drift are distinguished in the result.
    """

    if event.sport_key != NFL_ODDS_SPORT_KEY:
        raise UnsupportedNflOddsSportError(
            f"NFL identity resolution does not support sport_key={event.sport_key!r}"
        )
    if event.commence_time.tzinfo is None or event.commence_time.utcoffset() is None:
        raise MalformedNflProviderKickoffError(
            "NFL provider commence_time must be timezone-aware"
        )
    if event.home_team == event.away_team:
        raise SameNflTeamIdentityError("provider home and away team names are identical")

    home_team = _load_provider_team(cursor, event.home_team)
    away_team = _load_provider_team(cursor, event.away_team)
    if home_team.team_id == away_team.team_id:
        raise SameNflTeamIdentityError(
            "provider home and away team names resolve to the same canonical team"
        )

    home_selection, away_selection = _canonical_selections(event, home_team, away_team)
    existing_mapping = _load_existing_mapping(cursor, event)
    if existing_mapping is not None:
        return _resolve_existing_mapping(
            event,
            home_team,
            away_team,
            home_selection,
            away_selection,
            existing_mapping,
        )

    candidates = _load_matchup_candidates(cursor, home_team.team_id, away_team.team_id)
    match = _choose_canonical_game(event, home_team, away_team, candidates)
    drift_seconds = _kickoff_drift_seconds(
        event.commence_time, match.scheduled_start_time
    )
    return ResolvedNflOddsEvent(
        provider_event_mapping_id=None,
        provider_name=ODDS_API_PROVIDER_NAME,
        provider_sport_key=event.sport_key,
        external_event_id=event.event_id,
        game_id=match.game_id,
        canonical_home_team_id=home_team.team_id,
        canonical_away_team_id=away_team.team_id,
        provider_home_team_name=event.home_team,
        provider_away_team_name=event.away_team,
        canonical_kickoff=match.scheduled_start_time,
        provider_commence_time=event.commence_time,
        kickoff_drift_seconds=drift_seconds,
        kickoff_match_kind=_match_kind(drift_seconds),
        home_selection=home_selection,
        away_selection=away_selection,
    )


def persist_nfl_provider_event_mapping(
    cursor: Any, resolution: ResolvedNflOddsEvent
) -> ResolvedNflOddsEvent:
    """Persist an immutable, idempotent provider-event-to-game mapping."""

    if resolution.provider_sport_key != NFL_ODDS_SPORT_KEY:
        raise UnsupportedNflOddsSportError(
            "only americanfootball_nfl mappings may be persisted"
        )

    cursor.execute(
        """
        INSERT INTO nfl_odds_provider_event_mappings (
            provider_name,
            provider_sport_key,
            external_event_id,
            game_id,
            canonical_home_team_id,
            canonical_away_team_id,
            provider_home_team_name,
            provider_away_team_name,
            canonical_kickoff,
            first_provider_commence_time
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (provider_name, provider_sport_key, external_event_id) DO NOTHING
        RETURNING nfl_odds_provider_event_mapping_id
        """,
        (
            resolution.provider_name,
            resolution.provider_sport_key,
            resolution.external_event_id,
            resolution.game_id,
            resolution.canonical_home_team_id,
            resolution.canonical_away_team_id,
            resolution.provider_home_team_name,
            resolution.provider_away_team_name,
            resolution.canonical_kickoff,
            resolution.provider_commence_time,
        ),
    )
    inserted = cursor.fetchone()
    if inserted is not None:
        return replace(resolution, provider_event_mapping_id=int(inserted[0]))

    cursor.execute(
        """
        SELECT
            nfl_odds_provider_event_mapping_id,
            game_id,
            canonical_home_team_id,
            canonical_away_team_id,
            provider_home_team_name,
            provider_away_team_name,
            canonical_kickoff
        FROM nfl_odds_provider_event_mappings
        WHERE provider_name = %s
          AND provider_sport_key = %s
          AND external_event_id = %s
        """,
        (
            resolution.provider_name,
            resolution.provider_sport_key,
            resolution.external_event_id,
        ),
    )
    existing = cursor.fetchone()
    if existing is None:
        raise RuntimeError("provider event mapping disappeared during idempotent insert")

    expected = (
        resolution.game_id,
        resolution.canonical_home_team_id,
        resolution.canonical_away_team_id,
        resolution.provider_home_team_name,
        resolution.provider_away_team_name,
        resolution.canonical_kickoff,
    )
    if tuple(existing[1:]) != expected:
        raise NflProviderEventConflictError(
            "provider event ID is already bound to different canonical identity data"
        )
    return replace(resolution, provider_event_mapping_id=int(existing[0]))


def resolve_and_persist_nfl_odds_event(
    cursor: Any, event: OddsApiEvent
) -> ResolvedNflOddsEvent:
    resolution = resolve_nfl_odds_event(cursor, event)
    if resolution.provider_event_mapping_id is not None:
        return resolution
    return persist_nfl_provider_event_mapping(cursor, resolution)


def _load_provider_team(cursor: Any, provider_team_name: str) -> CanonicalNflProviderTeam:
    cursor.execute(
        """
        SELECT nts.team_id, ntp.current_abbreviation, nts.source_team_name
        FROM nfl_team_sources AS nts
        JOIN nfl_team_profiles AS ntp ON ntp.team_id = nts.team_id
        WHERE nts.source_name = %s
          AND nts.external_team_id = %s
          AND ntp.is_active = TRUE
        """,
        (ODDS_API_PROVIDER_NAME, provider_team_name),
    )
    rows = cursor.fetchall()
    if not rows:
        raise UnknownNflTeamIdentityError(
            f"unknown exact Odds API NFL team identity: {provider_team_name!r}"
        )
    if len(rows) != 1:
        raise AmbiguousNflTeamIdentityError(
            f"ambiguous Odds API NFL team identity: {provider_team_name!r}"
        )
    row = rows[0]
    return CanonicalNflProviderTeam(
        team_id=int(row[0]),
        current_abbreviation=str(row[1]),
        provider_team_name=str(row[2]),
    )


def _load_existing_mapping(cursor: Any, event: OddsApiEvent) -> _ExistingMapping | None:
    cursor.execute(
        """
        SELECT
            m.nfl_odds_provider_event_mapping_id,
            m.game_id,
            m.canonical_home_team_id,
            m.canonical_away_team_id,
            m.provider_home_team_name,
            m.provider_away_team_name,
            m.canonical_kickoff,
            ng.scheduled_start_time,
            ng.status,
            g.home_team_id,
            g.away_team_id
        FROM nfl_odds_provider_event_mappings AS m
        JOIN games AS g ON g.game_id = m.game_id
        JOIN nfl_games AS ng ON ng.game_id = m.game_id
        WHERE m.provider_name = %s
          AND m.provider_sport_key = %s
          AND m.external_event_id = %s
        """,
        (ODDS_API_PROVIDER_NAME, event.sport_key, event.event_id),
    )
    rows = cursor.fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise NflProviderEventConflictError("provider event ID has ambiguous mappings")
    row = rows[0]
    return _ExistingMapping(
        mapping_id=int(row[0]),
        game_id=int(row[1]),
        canonical_home_team_id=int(row[2]),
        canonical_away_team_id=int(row[3]),
        provider_home_team_name=str(row[4]),
        provider_away_team_name=str(row[5]),
        canonical_kickoff=row[6],
        current_kickoff=row[7],
        status=str(row[8]),
        current_home_team_id=int(row[9]),
        current_away_team_id=int(row[10]),
    )


def _load_matchup_candidates(
    cursor: Any, home_team_id: int, away_team_id: int
) -> tuple[_CanonicalGameCandidate, ...]:
    cursor.execute(
        """
        SELECT
            g.game_id,
            ng.scheduled_start_time,
            g.home_team_id,
            g.away_team_id,
            ng.status
        FROM games AS g
        JOIN nfl_games AS ng ON ng.game_id = g.game_id
        WHERE (g.home_team_id = %s AND g.away_team_id = %s)
           OR (g.home_team_id = %s AND g.away_team_id = %s)
        ORDER BY ng.scheduled_start_time, g.game_id
        """,
        (home_team_id, away_team_id, away_team_id, home_team_id),
    )
    return tuple(
        _CanonicalGameCandidate(
            game_id=int(row[0]),
            scheduled_start_time=row[1],
            home_team_id=int(row[2]),
            away_team_id=int(row[3]),
            status=str(row[4]),
        )
        for row in cursor.fetchall()
    )


def _choose_canonical_game(
    event: OddsApiEvent,
    home_team: CanonicalNflProviderTeam,
    away_team: CanonicalNflProviderTeam,
    candidates: tuple[_CanonicalGameCandidate, ...],
) -> _CanonicalGameCandidate:
    oriented = tuple(
        candidate
        for candidate in candidates
        if candidate.home_team_id == home_team.team_id
        and candidate.away_team_id == away_team.team_id
    )
    reversed_candidates = tuple(
        candidate
        for candidate in candidates
        if candidate.home_team_id == away_team.team_id
        and candidate.away_team_id == home_team.team_id
    )
    accepted = tuple(
        candidate
        for candidate in oriented
        if candidate.status == "unplayed"
        and _within_kickoff_tolerance(event.commence_time, candidate.scheduled_start_time)
    )
    if len(accepted) > 1:
        raise AmbiguousNflGameMatchError(
            "multiple unplayed canonical NFL games match provider teams and kickoff tolerance"
        )
    if len(accepted) == 1:
        return accepted[0]

    if any(
        _within_kickoff_tolerance(event.commence_time, candidate.scheduled_start_time)
        for candidate in reversed_candidates
    ):
        raise ReversedNflMatchupError(
            "provider home/away orientation is reversed relative to the canonical NFL game"
        )
    if any(
        _within_kickoff_tolerance(event.commence_time, candidate.scheduled_start_time)
        for candidate in oriented
    ):
        raise CanonicalNflGameStatusError(
            "matching canonical NFL game is not in unplayed status"
        )
    if oriented:
        nearest = min(
            oriented,
            key=lambda candidate: abs(
                _kickoff_drift_seconds(
                    event.commence_time, candidate.scheduled_start_time
                )
            ),
        )
        drift = _kickoff_drift_seconds(event.commence_time, nearest.scheduled_start_time)
        raise UnacceptableNflKickoffDriftError(
            f"nearest oriented canonical NFL game has {drift}-second kickoff drift; "
            f"maximum is {int(NFL_ODDS_KICKOFF_TOLERANCE.total_seconds())} seconds"
        )
    if reversed_candidates:
        raise ReversedNflMatchupError(
            "provider home/away orientation is reversed relative to canonical NFL games"
        )
    raise CanonicalNflGameNotFoundError(
        "no existing canonical NFL game matches the provider teams"
    )


def _resolve_existing_mapping(
    event: OddsApiEvent,
    home_team: CanonicalNflProviderTeam,
    away_team: CanonicalNflProviderTeam,
    home_selection: CanonicalNflSelection,
    away_selection: CanonicalNflSelection,
    mapping: _ExistingMapping,
) -> ResolvedNflOddsEvent:
    if (
        mapping.provider_home_team_name != event.home_team
        or mapping.provider_away_team_name != event.away_team
        or mapping.canonical_home_team_id != home_team.team_id
        or mapping.canonical_away_team_id != away_team.team_id
        or mapping.current_home_team_id != home_team.team_id
        or mapping.current_away_team_id != away_team.team_id
    ):
        raise NflProviderEventConflictError(
            "provider event ID is already bound to different team identities"
        )
    if mapping.status != "unplayed":
        raise CanonicalNflGameStatusError(
            "mapped canonical NFL game is no longer in unplayed status"
        )
    drift_seconds = _kickoff_drift_seconds(
        event.commence_time, mapping.current_kickoff
    )
    if abs(drift_seconds) > NFL_ODDS_KICKOFF_TOLERANCE.total_seconds():
        raise NflProviderEventConflictError(
            "provider event ID commence time moved outside the canonical kickoff tolerance"
        )
    return ResolvedNflOddsEvent(
        provider_event_mapping_id=mapping.mapping_id,
        provider_name=ODDS_API_PROVIDER_NAME,
        provider_sport_key=event.sport_key,
        external_event_id=event.event_id,
        game_id=mapping.game_id,
        canonical_home_team_id=home_team.team_id,
        canonical_away_team_id=away_team.team_id,
        provider_home_team_name=event.home_team,
        provider_away_team_name=event.away_team,
        canonical_kickoff=mapping.current_kickoff,
        provider_commence_time=event.commence_time,
        kickoff_drift_seconds=drift_seconds,
        kickoff_match_kind=_match_kind(drift_seconds),
        home_selection=home_selection,
        away_selection=away_selection,
    )


def _canonical_selections(
    event: OddsApiEvent,
    home_team: CanonicalNflProviderTeam,
    away_team: CanonicalNflProviderTeam,
) -> tuple[CanonicalNflSelection, CanonicalNflSelection]:
    market_count = 0
    for bookmaker in event.bookmakers:
        if len(bookmaker.markets) != 1:
            raise NflSelectionIdentityError(
                "each NFL bookmaker must contain exactly one H2H market"
            )
        for market in bookmaker.markets:
            market_count += 1
            if market.market_key != "h2h":
                raise NflSelectionIdentityError(
                    "NFL canonical selection resolution supports only h2h markets"
                )
            names = [outcome.selection_name for outcome in market.outcomes]
            if (
                len(names) != 2
                or names.count(event.home_team) != 1
                or names.count(event.away_team) != 1
            ):
                raise NflSelectionIdentityError(
                    "each NFL h2h market must contain exactly one home and one away selection"
                )
    if market_count == 0:
        raise NflSelectionIdentityError(
            "NFL event has no h2h market from which to resolve canonical selections"
        )
    return (
        CanonicalNflSelection(event.home_team, home_team.team_id, "home"),
        CanonicalNflSelection(event.away_team, away_team.team_id, "away"),
    )


def _kickoff_drift_seconds(provider_time: datetime, canonical_time: datetime) -> float:
    if canonical_time.tzinfo is None or canonical_time.utcoffset() is None:
        raise MalformedNflProviderKickoffError(
            "canonical NFL kickoff must be timezone-aware"
        )
    return (provider_time - canonical_time).total_seconds()


def _within_kickoff_tolerance(provider_time: datetime, canonical_time: datetime) -> bool:
    return abs(provider_time - canonical_time) <= NFL_ODDS_KICKOFF_TOLERANCE


def _match_kind(drift_seconds: float) -> NflKickoffMatchKind:
    if drift_seconds == 0:
        return NflKickoffMatchKind.EXACT
    return NflKickoffMatchKind.ACCEPTABLE_DRIFT
