from datetime import datetime, timedelta, timezone

from sportsmodel.ingest.game_matching import (
    DEFAULT_GAME_TIME_TOLERANCE,
    get_or_create_canonical_game,
)


class FakeCursor:
    def __init__(
        self,
        fetch_results,
    ) -> None:
        self.fetch_results = iter(fetch_results)
        self.executions: list[
            tuple[str, tuple]
        ] = []

    def execute(
        self,
        query: str,
        parameters: tuple,
    ) -> None:
        self.executions.append(
            (
                query,
                parameters,
            )
        )

    def fetchone(self):
        return next(self.fetch_results)


def test_candidate_query_excludes_same_source_mapping() -> None:
    game_datetime = datetime(
        2025,
        4,
        24,
        18,
        15,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        [
            None,
            None,
            (
                9001,
            ),
        ]
    )

    game_id = get_or_create_canonical_game(
        cursor,
        source_name="mlb_stats",
        external_game_id="778195",
        game_datetime=game_datetime,
        home_team_id=10,
        away_team_id=20,
    )

    assert game_id == 9001
    assert len(cursor.executions) == 4

    candidate_query, candidate_parameters = (
        cursor.executions[1]
    )

    assert "NOT EXISTS" in candidate_query
    assert (
        "existing_mapping.source_name = %s"
        in candidate_query
    )

    assert candidate_parameters == (
        10,
        20,
        (
            game_datetime
            - DEFAULT_GAME_TIME_TOLERANCE
        ),
        (
            game_datetime
            + DEFAULT_GAME_TIME_TOLERANCE
        ),
        "mlb_stats",
        game_datetime,
    )

    source_insert_query, source_insert_parameters = (
        cursor.executions[3]
    )

    assert "INSERT INTO game_sources" in source_insert_query
    assert source_insert_parameters == (
        9001,
        "mlb_stats",
        "778195",
    )


def test_existing_source_mapping_still_has_priority() -> None:
    cursor = FakeCursor(
        [
            (
                500,
            ),
        ]
    )

    game_id = get_or_create_canonical_game(
        cursor,
        source_name="mlb_stats",
        external_game_id="778195",
        game_datetime=datetime(
            2025,
            4,
            24,
            18,
            15,
            tzinfo=timezone.utc,
        ),
        home_team_id=10,
        away_team_id=20,
        tolerance=timedelta(
            minutes=15
        ),
    )

    assert game_id == 500
    assert len(cursor.executions) == 1
