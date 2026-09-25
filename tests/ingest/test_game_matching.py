from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.ingest.game_matching import (
    CanonicalGameIdentityConflictError,
    get_or_create_authoritative_source_game,
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


class FakeAuthoritativeCursor(FakeCursor):
    def __init__(self, *, existing_sources, fetch_results=()):
        super().__init__(fetch_results=fetch_results)
        self.existing_sources = list(existing_sources)

    def fetchall(self):
        return self.existing_sources


def test_authoritative_mapping_ignores_unrelated_nearby_identity() -> None:
    cursor = FakeAuthoritativeCursor(
        existing_sources=[
            (42, 10, 20),
        ]
    )

    game_id = get_or_create_authoritative_source_game(
        cursor,
        source_name="mlb_stats",
        external_game_id="12345",
        game_datetime=GAME_TIME,
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 42
    assert len(cursor.executions) == 1
    assert "candidate" not in cursor.executions[0][0]


def test_authoritative_mapping_orientation_conflict_fails_closed() -> None:
    cursor = FakeAuthoritativeCursor(
        existing_sources=[
            (42, 20, 10),
        ]
    )

    with pytest.raises(
        CanonicalGameIdentityConflictError,
        match="authoritative source mapping conflicts",
    ):
        get_or_create_authoritative_source_game(
            cursor,
            source_name="mlb_stats",
            external_game_id="12345",
            game_datetime=GAME_TIME,
            home_team_id=10,
            away_team_id=20,
        )


def test_duplicate_authoritative_source_identity_fails_closed() -> None:
    cursor = FakeAuthoritativeCursor(
        existing_sources=[
            (42, 10, 20),
            (43, 10, 20),
        ]
    )

    with pytest.raises(
        CanonicalGameIdentityConflictError,
        match="Multiple canonical games share the authoritative source",
    ):
        get_or_create_authoritative_source_game(
            cursor,
            source_name="mlb_stats",
            external_game_id="12345",
            game_datetime=GAME_TIME,
            home_team_id=10,
            away_team_id=20,
        )


def test_unmapped_authoritative_source_uses_strict_doubleheader_matching() -> None:
    cursor = FakeAuthoritativeCursor(
        existing_sources=[],
        fetch_results=[
            None,
            (0, None),
            (2, 51),
        ],
    )

    with pytest.raises(
        CanonicalGameIdentityConflictError,
        match="doubleheader or schedule identity is ambiguous",
    ):
        get_or_create_authoritative_source_game(
            cursor,
            source_name="mlb_stats",
            external_game_id="12345",
            game_datetime=GAME_TIME,
            home_team_id=10,
            away_team_id=20,
        )


def test_unmapped_authoritative_source_uses_strict_unique_match() -> None:
    cursor = FakeAuthoritativeCursor(
        existing_sources=[],
        fetch_results=[
            None,
            (1, 51),
        ],
    )

    game_id = get_or_create_authoritative_source_game(
        cursor,
        source_name="mlb_stats",
        external_game_id="12345",
        game_datetime=GAME_TIME,
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 51
    assert len(cursor.executions) == 4


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
    assert len(cursor.executions) == 6

    insert_parameters = cursor.executions[4][1]

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
    assert "AT TIME ZONE 'America/Los_Angeles'" in cursor.executions[3][0]
    assert "EXISTS" in cursor.executions[3][0]
    assert len(cursor.executions) == 5


def test_same_date_doubleheader_ambiguity_fails_closed() -> None:
    cursor = FakeCursor(
        fetch_results=[
            None,
            (0, None),
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
            (0, None),
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


def test_replacement_odds_event_uses_unique_nearby_mlb_identity() -> None:
    cursor = FakeCursor(
        fetch_results=[
            None,
            (1, 11297),
        ]
    )

    game_id = get_or_create_canonical_game(
        cursor,
        source_name="odds_api",
        external_game_id="cc3886440708c8649f6f878183416628",
        game_datetime=GAME_TIME + timedelta(minutes=1),
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 11297
    assert len(cursor.executions) == 3
    authoritative_query, parameters = cursor.executions[1]
    assert "authoritative_source.source_name = %s" in authoritative_query
    assert "NOT EXISTS" not in authoritative_query
    assert parameters == (
        10,
        20,
        GAME_TIME - timedelta(minutes=14),
        GAME_TIME + timedelta(minutes=16),
        "mlb_stats",
    )
    assert cursor.executions[2][1] == (
        11297,
        "odds_api",
        "cc3886440708c8649f6f878183416628",
    )


def test_replacement_odds_event_with_two_nearby_mlb_games_fails_closed() -> None:
    cursor = FakeCursor(
        fetch_results=[
            None,
            (2, 11297),
        ]
    )

    with pytest.raises(
        CanonicalGameIdentityConflictError,
        match="Multiple nearby MLB-authoritative games",
    ):
        get_or_create_canonical_game(
            cursor,
            source_name="odds_api",
            external_game_id="replacement-event",
            game_datetime=GAME_TIME,
            home_team_id=10,
            away_team_id=20,
        )


def test_replacement_allowance_requires_mlb_authority() -> None:
    cursor = FakeCursor(
        fetch_results=[
            None,
            (0, None),
            (1, 61),
        ]
    )

    game_id = get_or_create_canonical_game(
        cursor,
        source_name="odds_api",
        external_game_id="ordinary-event",
        game_datetime=GAME_TIME,
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 61
    assert "authoritative_source.source_name = %s" in cursor.executions[1][0]
    assert "NOT EXISTS" in cursor.executions[2][0]


def test_replacement_allowance_does_not_reuse_out_of_window_identity() -> None:
    cursor = FakeCursor(
        fetch_results=[
            None,
            (0, None),
            (0, None),
            (0, None),
            (75,),
        ]
    )

    game_id = get_or_create_canonical_game(
        cursor,
        source_name="odds_api",
        external_game_id="out-of-window-event",
        game_datetime=GAME_TIME + timedelta(hours=5),
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 75


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
