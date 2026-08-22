from datetime import datetime, timezone

import pytest

from sportsmodel.ingest.odds_api_parser import OddsApiEvent
from sportsmodel.ingest.odds_provenance import (
    ProviderEventConflictError,
    ProviderIdentityConflictError,
    create_provider_event_observation,
    resolve_provider_sportsbook,
)


OBSERVED_AT = datetime(
    2026,
    9,
    10,
    22,
    tzinfo=timezone.utc,
)
EVENT = OddsApiEvent(
    event_id="provider-event-1",
    sport_key="americanfootball_nfl",
    commence_time=datetime(
        2026,
        9,
        11,
        0,
        20,
        tzinfo=timezone.utc,
    ),
    home_team="Kansas City Chiefs",
    away_team="Denver Broncos",
    bookmakers=(),
)


class ScriptedCursor:
    def __init__(self, rows) -> None:
        self.rows = list(rows)
        self.queries = []

    def execute(self, query, parameters) -> None:
        self.queries.append((query, parameters))

    def fetchone(self):
        return self.rows.pop(0)


def test_existing_provider_key_is_identity_when_title_changes() -> None:
    cursor = ScriptedCursor([(41, 7)])

    identity = resolve_provider_sportsbook(
        cursor,
        provider_name="odds_api",
        provider_bookmaker_key="fanduel",
        bookmaker_title="FanDuel Sportsbook",
    )

    assert identity.sportsbook_provider_identity_id == 41
    assert identity.sportsbook_id == 7
    assert len(cursor.queries) == 1
    assert cursor.queries[0][1] == ("odds_api", "fanduel")


def test_same_display_title_cannot_acquire_conflicting_provider_key() -> None:
    cursor = ScriptedCursor(
        [
            None,
            (7,),
            ("fanduel",),
        ]
    )

    with pytest.raises(
        ProviderIdentityConflictError,
        match="already mapped",
    ):
        resolve_provider_sportsbook(
            cursor,
            provider_name="odds_api",
            provider_bookmaker_key="draftkings",
            bookmaker_title="FanDuel",
        )


def test_provider_identity_rejects_blank_key_before_sql() -> None:
    cursor = ScriptedCursor([])

    with pytest.raises(ValueError, match="provider_bookmaker_key"):
        resolve_provider_sportsbook(
            cursor,
            provider_name="odds_api",
            provider_bookmaker_key=" ",
            bookmaker_title="FanDuel",
        )

    assert cursor.queries == []


def test_event_observation_exact_replay_is_idempotent() -> None:
    cursor = ScriptedCursor(
        [
            None,
            (
                51,
                "odds_api",
                EVENT.sport_key,
                EVENT.commence_time,
                EVENT.home_team,
                EVENT.away_team,
                OBSERVED_AT,
                None,
            ),
        ]
    )

    assert create_provider_event_observation(
        cursor,
        ingestion_run_id=20,
        provider_name="odds_api",
        event=EVENT,
        observed_at=OBSERVED_AT,
    ) == 51


def test_event_observation_conflicting_replay_fails_closed() -> None:
    cursor = ScriptedCursor(
        [
            None,
            (
                51,
                "odds_api",
                EVENT.sport_key,
                EVENT.commence_time,
                "Different Home",
                EVENT.away_team,
                OBSERVED_AT,
                None,
            ),
        ]
    )

    with pytest.raises(
        ProviderEventConflictError,
        match="conflicts with its existing observation",
    ):
        create_provider_event_observation(
            cursor,
            ingestion_run_id=20,
            provider_name="odds_api",
            event=EVENT,
            observed_at=OBSERVED_AT,
        )
