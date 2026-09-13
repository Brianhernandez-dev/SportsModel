from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.ingest.game_matching import (
    CanonicalGameIdentityConflictError,
    get_or_create_canonical_game,
)


GAME_TIME = datetime(
    2026,
    7,
    12,
    17,
    0,
    tzinfo=timezone.utc,
)


class FakeCursor:
    def __init__(self, fetch_results):
        self.fetch_results = list(fetch_results)
        self.executions = []

    def execute(self, query, parameters=None):
        self.executions.append(
            (
                " ".join(query.split()),
                parameters,
            )
        )

    def fetchone(self):
        if not self.fetch_results:
            raise AssertionError(
                "Unexpected fetchone call."
            )

        return self.fetch_results.pop(0)


def test_existing_source_mapping_is_returned():
    cursor = FakeCursor(
        fetch_results=[
            (42, GAME_TIME, 10, 20),
            (0, None),
        ]
    )

    game_id = get_or_create_canonical_game(
        cursor,
        source_name="mlb_stats",
        external_game_id="12345",
        game_datetime=GAME_TIME,
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 42
    assert len(cursor.executions) == 2


def test_nearby_matching_game_is_reused():
    cursor = FakeCursor(
        fetch_results=[
            None,
            (1, 51),
        ]
    )

    game_id = get_or_create_canonical_game(
        cursor,
        source_name="mlb_stats",
        external_game_id="12345",
        game_datetime=GAME_TIME,
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 51
    assert len(cursor.executions) == 3

    lookup_parameters = cursor.executions[1][1]

    assert lookup_parameters == (
        10,
        20,
        GAME_TIME - timedelta(minutes=15),
        GAME_TIME + timedelta(minutes=15),
        "mlb_stats",
    )

    source_insert_parameters = (
        cursor.executions[2][1]
    )

    assert source_insert_parameters == (
        51,
        "mlb_stats",
        "12345",
    )


def test_new_game_is_created_when_no_match_exists():
    cursor = FakeCursor(
        fetch_results=[
            None,
            (0, None),
            (0, None),
            (75,),
        ]
    )

    game_id = get_or_create_canonical_game(
        cursor,
        source_name="odds_api",
        external_game_id="event-1",
        game_datetime=GAME_TIME,
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 75
    assert len(cursor.executions) == 5

    insert_parameters = cursor.executions[3][1]

    assert insert_parameters == (
        GAME_TIME,
        10,
        20,
    )


def test_home_and_away_orientation_is_preserved():
    cursor = FakeCursor(
        fetch_results=[
            None,
            (0, None),
            (0, None),
            (90,),
        ]
    )

    get_or_create_canonical_game(
        cursor,
        source_name="mlb_stats",
        external_game_id="12345",
        game_datetime=GAME_TIME,
        home_team_id=20,
        away_team_id=10,
    )

    lookup_parameters = cursor.executions[1][1]

    assert lookup_parameters[0] == 20
    assert lookup_parameters[1] == 10


def test_custom_tolerance_is_used():
    cursor = FakeCursor(
        fetch_results=[
            None,
            (1, 51),
        ]
    )

    tolerance = timedelta(minutes=5)

    get_or_create_canonical_game(
        cursor,
        source_name="mlb_stats",
        external_game_id="12345",
        game_datetime=GAME_TIME,
        home_team_id=10,
        away_team_id=20,
        tolerance=tolerance,
    )

    lookup_parameters = cursor.executions[1][1]

    assert lookup_parameters[2] == (
        GAME_TIME - tolerance
    )
    assert lookup_parameters[3] == (
        GAME_TIME + tolerance
    )


def test_external_identifier_is_converted_to_string():
    cursor = FakeCursor(
        fetch_results=[
            None,
            (1, 51),
        ]
    )

    get_or_create_canonical_game(
        cursor,
        source_name="mlb_stats",
        external_game_id=824814,
        game_datetime=GAME_TIME,
        home_team_id=10,
        away_team_id=20,
    )

    source_lookup_parameters = (
        cursor.executions[0][1]
    )

    assert source_lookup_parameters == (
        "mlb_stats",
        "824814",
    )


def test_unique_same_date_source_game_survives_schedule_drift() -> None:
    cursor = FakeCursor(
        fetch_results=[
            None,
            (0, None),
            (1, 51),
        ]
    )

    game_id = get_or_create_canonical_game(
        cursor,
        source_name="odds_api",
        external_game_id="event-1",
        game_datetime=GAME_TIME + timedelta(hours=2),
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 51
    assert "AT TIME ZONE 'America/Los_Angeles'" in cursor.executions[2][0]
    assert "EXISTS" in cursor.executions[2][0]
    assert len(cursor.executions) == 4


def test_same_date_doubleheader_ambiguity_fails_closed() -> None:
    cursor = FakeCursor(
        fetch_results=[
            None,
            (0, None),
            (2, 51),
        ]
    )

    with pytest.raises(
        CanonicalGameIdentityConflictError,
        match="doubleheader or schedule identity is ambiguous",
    ):
        get_or_create_canonical_game(
            cursor,
            source_name="odds_api",
            external_game_id="event-1",
            game_datetime=GAME_TIME,
            home_team_id=10,
            away_team_id=20,
        )


def test_multiple_nearby_games_fail_closed() -> None:
    cursor = FakeCursor(
        fetch_results=[
            None,
            (2, 51),
        ]
    )

    with pytest.raises(
        CanonicalGameIdentityConflictError,
        match="Multiple nearby canonical games",
    ):
        get_or_create_canonical_game(
            cursor,
            source_name="odds_api",
            external_game_id="event-1",
            game_datetime=GAME_TIME,
            home_team_id=10,
            away_team_id=20,
        )


def test_stale_mapping_conflict_is_not_silently_trusted() -> None:
    cursor = FakeCursor(
        fetch_results=[
            (75, GAME_TIME, 10, 20),
            (1, 51),
        ]
    )

    with pytest.raises(
        CanonicalGameIdentityConflictError,
        match="maps to 75, candidate=51",
    ):
        get_or_create_canonical_game(
            cursor,
            source_name="odds_api",
            external_game_id="event-1",
            game_datetime=GAME_TIME,
            home_team_id=10,
            away_team_id=20,
        )


def test_existing_mapping_with_reversed_orientation_fails_closed() -> None:
    cursor = FakeCursor(
        fetch_results=[
            (75, GAME_TIME, 20, 10),
        ]
    )

    with pytest.raises(
        CanonicalGameIdentityConflictError,
        match="home/away identity",
    ):
        get_or_create_canonical_game(
            cursor,
            source_name="odds_api",
            external_game_id="event-1",
            game_datetime=GAME_TIME,
            home_team_id=10,
            away_team_id=20,
        )


def test_existing_mapping_allows_unambiguous_reschedule() -> None:
    cursor = FakeCursor(
        fetch_results=[
            (75, GAME_TIME, 10, 20),
            (0, None),
        ]
    )

    game_id = get_or_create_canonical_game(
        cursor,
        source_name="mlb_stats",
        external_game_id="12345",
        game_datetime=GAME_TIME + timedelta(hours=3),
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 75
