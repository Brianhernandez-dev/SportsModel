from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sportsmodel.ingest.odds_api_parser import OddsApiEvent


class ProviderIdentityConflictError(RuntimeError):
    """Raised when one provider identity points at conflicting books."""


class ProviderEventConflictError(RuntimeError):
    """Raised when a run/event identity is replayed with different facts."""


@dataclass(frozen=True)
class ProviderSportsbookIdentity:
    sportsbook_provider_identity_id: int
    sportsbook_id: int


def resolve_provider_sportsbook(
    cursor: Any,
    *,
    provider_name: str,
    provider_bookmaker_key: str,
    bookmaker_title: str,
) -> ProviderSportsbookIdentity:
    """
    Resolve a stable provider bookmaker key to one shared sportsbook.

    The first exact-title observation may attach an existing historical
    sportsbook row to the provider key. Later title changes do not rename the
    sportsbook or change identity; the observed title belongs on the quote.
    """

    provider_name = _required_text(provider_name, "provider_name")
    provider_bookmaker_key = _required_text(
        provider_bookmaker_key,
        "provider_bookmaker_key",
    )
    bookmaker_title = _required_text(
        bookmaker_title,
        "bookmaker_title",
    )

    cursor.execute(
        """
        SELECT
            identity.sportsbook_provider_identity_id,
            identity.sportsbook_id
        FROM sportsbook_provider_identities AS identity
        WHERE identity.provider_name = %s
          AND identity.provider_bookmaker_key = %s;
        """,
        (provider_name, provider_bookmaker_key),
    )
    existing_identity = cursor.fetchone()
    if existing_identity is not None:
        return ProviderSportsbookIdentity(
            sportsbook_provider_identity_id=existing_identity[0],
            sportsbook_id=existing_identity[1],
        )

    cursor.execute(
        """
        INSERT INTO sportsbooks (name)
        VALUES (%s)
        ON CONFLICT (name) DO NOTHING;
        """,
        (bookmaker_title,),
    )
    cursor.execute(
        """
        SELECT sportsbook_id
        FROM sportsbooks
        WHERE name = %s;
        """,
        (bookmaker_title,),
    )
    sportsbook_row = cursor.fetchone()
    if sportsbook_row is None:
        raise ProviderIdentityConflictError(
            "Sportsbook title could not be resolved after insert."
        )
    sportsbook_id = sportsbook_row[0]

    cursor.execute(
        """
        SELECT provider_bookmaker_key
        FROM sportsbook_provider_identities
        WHERE sportsbook_id = %s
          AND provider_name = %s;
        """,
        (sportsbook_id, provider_name),
    )
    existing_book_key = cursor.fetchone()
    if (
        existing_book_key is not None
        and existing_book_key[0] != provider_bookmaker_key
    ):
        raise ProviderIdentityConflictError(
            f"Sportsbook {sportsbook_id} is already mapped to provider "
            f"key {existing_book_key[0]!r}, not "
            f"{provider_bookmaker_key!r}."
        )

    cursor.execute(
        """
        INSERT INTO sportsbook_provider_identities (
            provider_name,
            provider_bookmaker_key,
            sportsbook_id
        )
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING sportsbook_provider_identity_id;
        """,
        (
            provider_name,
            provider_bookmaker_key,
            sportsbook_id,
        ),
    )
    inserted_identity = cursor.fetchone()
    if inserted_identity is not None:
        return ProviderSportsbookIdentity(
            sportsbook_provider_identity_id=inserted_identity[0],
            sportsbook_id=sportsbook_id,
        )

    cursor.execute(
        """
        SELECT
            sportsbook_provider_identity_id,
            sportsbook_id
        FROM sportsbook_provider_identities
        WHERE provider_name = %s
          AND provider_bookmaker_key = %s;
        """,
        (provider_name, provider_bookmaker_key),
    )
    raced_identity = cursor.fetchone()
    if raced_identity is None or raced_identity[1] != sportsbook_id:
        raise ProviderIdentityConflictError(
            "Provider bookmaker identity conflicts with the resolved "
            "sportsbook."
        )
    return ProviderSportsbookIdentity(
        sportsbook_provider_identity_id=raced_identity[0],
        sportsbook_id=raced_identity[1],
    )


def create_provider_event_observation(
    cursor: Any,
    *,
    ingestion_run_id: int,
    provider_name: str,
    event: OddsApiEvent,
    observed_at: datetime,
) -> int:
    """
    Persist one provider event as observed in one response/run.

    Replaying the same run/event is idempotent only when all retained provider
    facts match exactly. A conflicting replay fails closed.
    """

    cursor.execute(
        """
        INSERT INTO odds_provider_event_observations (
            odds_ingestion_run_id,
            source_name,
            provider_sport_key,
            external_event_id,
            provider_commence_time,
            provider_home_team_name,
            provider_away_team_name,
            observed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (
            odds_ingestion_run_id,
            external_event_id
        ) DO NOTHING
        RETURNING odds_provider_event_observation_id;
        """,
        (
            ingestion_run_id,
            provider_name,
            event.sport_key,
            event.event_id,
            event.commence_time,
            event.home_team,
            event.away_team,
            observed_at,
        ),
    )
    inserted = cursor.fetchone()
    if inserted is not None:
        return inserted[0]

    cursor.execute(
        """
        SELECT
            odds_provider_event_observation_id,
            source_name,
            provider_sport_key,
            provider_commence_time,
            provider_home_team_name,
            provider_away_team_name,
            observed_at
        FROM odds_provider_event_observations
        WHERE odds_ingestion_run_id = %s
          AND external_event_id = %s;
        """,
        (ingestion_run_id, event.event_id),
    )
    existing = cursor.fetchone()
    expected = (
        provider_name,
        event.sport_key,
        event.commence_time,
        event.home_team,
        event.away_team,
        observed_at,
    )
    if existing is None or tuple(existing[1:]) != expected:
        raise ProviderEventConflictError(
            f"Provider event {event.event_id!r} conflicts with its "
            f"existing observation in ingestion run {ingestion_run_id}."
        )
    return existing[0]


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text.")
    return value
