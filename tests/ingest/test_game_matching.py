from datetime import datetime, timedelta, timezone

from sportsmodel.ingest.game_matching import (
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
            (42,),
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
    assert len(cursor.executions) == 1


def test_nearby_matching_game_is_reused():
    cursor = FakeCursor(
        fetch_results=[
            None,
            (51,),
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
        GAME_TIME,
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
            None,
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
    assert len(cursor.executions) == 4

    insert_parameters = cursor.executions[2][1]

    assert insert_parameters == (
        GAME_TIME,
        10,
        20,
    )


def test_home_and_away_orientation_is_preserved():
    cursor = FakeCursor(
        fetch_results=[
            None,
            None,
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
            (51,),
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
            (51,),
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