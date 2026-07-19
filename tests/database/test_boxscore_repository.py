from typing import Any

import pytest

from sportsmodel.database.boxscore_repository import save_parsed_boxscore
from sportsmodel.models.parsed_boxscore import ParsedBoxScore
from sportsmodel.models.player_game_pitching_statistics import (
    PitchingDecision,
    PlayerGamePitchingStatistics,
)
from sportsmodel.models.team_game_statistics import TeamGameStatistics


class FakeCursor:
    def __init__(
        self,
        *,
        game_rowcount: int = 1,
        fail_on_execute_number: int | None = None,
    ) -> None:
        self.game_rowcount = game_rowcount
        self.fail_on_execute_number = fail_on_execute_number

        self.executions: list[
            tuple[str, tuple[Any, ...] | None]
        ] = []

        self.rowcount = 0

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        return None

    def execute(
        self,
        query: str,
        parameters: tuple[Any, ...] | None = None,
    ) -> None:
        execute_number = len(self.executions) + 1

        if execute_number == self.fail_on_execute_number:
            raise RuntimeError("database failure")

        self.executions.append(
            (
                query,
                parameters,
            )
        )

        if execute_number == 1:
            self.rowcount = self.game_rowcount
        else:
            self.rowcount = 1


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.fake_cursor = cursor

        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _build_team_statistics(
    *,
    team_id: int,
    is_home: bool,
    runs: int,
    runs_allowed: int,
) -> TeamGameStatistics:
    return TeamGameStatistics(
        game_id=10,
        team_id=team_id,
        is_home=is_home,
        runs=runs,
        hits=8,
        errors=0,
        at_bats=34,
        plate_appearances=38,
        doubles=2,
        triples=0,
        home_runs=1,
        walks=3,
        intentional_walks=0,
        strikeouts=9,
        hit_by_pitch=1,
        sacrifice_flies=0,
        stolen_bases=1,
        caught_stealing=0,
        pitching_outs=27,
        runs_allowed=runs_allowed,
        earned_runs_allowed=runs_allowed,
        hits_allowed=7,
        home_runs_allowed=1,
        walks_allowed=2,
        strikeouts_recorded=8,
        left_on_base=7,
        double_plays=1,
        source_name="mlb_stats_api",
    )


def _build_pitcher_statistics(
    *,
    baseball_player_id: int,
    team_id: int,
    appearance_order: int,
    is_starter: bool,
    decision: PitchingDecision | None = None,
    save_recorded: bool = False,
) -> PlayerGamePitchingStatistics:
    return PlayerGamePitchingStatistics(
        game_id=10,
        team_id=team_id,
        baseball_player_id=baseball_player_id,
        appearance_order=appearance_order,
        is_starter=is_starter,
        pitching_outs=18 if is_starter else 3,
        batters_faced=24 if is_starter else 4,
        hits_allowed=5 if is_starter else 1,
        runs_allowed=2 if is_starter else 0,
        earned_runs_allowed=2 if is_starter else 0,
        home_runs_allowed=1 if is_starter else 0,
        walks_allowed=2 if is_starter else 0,
        intentional_walks_allowed=0,
        strikeouts=6 if is_starter else 1,
        hit_batters=0,
        pitches_thrown=92 if is_starter else 14,
        strikes_thrown=61 if is_starter else 10,
        decision=decision,
        save_recorded=save_recorded,
        hold_recorded=False,
        blown_save_recorded=False,
        source_name="mlb_stats_api",
    )


def _build_parsed_boxscore() -> ParsedBoxScore:
    away_team_statistics = _build_team_statistics(
        team_id=101,
        is_home=False,
        runs=2,
        runs_allowed=4,
    )

    home_team_statistics = _build_team_statistics(
        team_id=102,
        is_home=True,
        runs=4,
        runs_allowed=2,
    )

    winning_pitcher = _build_pitcher_statistics(
        baseball_player_id=1001,
        team_id=102,
        appearance_order=1,
        is_starter=True,
        decision=PitchingDecision.WIN,
    )

    saving_pitcher = _build_pitcher_statistics(
        baseball_player_id=1002,
        team_id=102,
        appearance_order=2,
        is_starter=False,
        decision=PitchingDecision.SAVE,
        save_recorded=True,
    )

    losing_pitcher = _build_pitcher_statistics(
        baseball_player_id=2001,
        team_id=101,
        appearance_order=1,
        is_starter=True,
        decision=PitchingDecision.LOSS,
    )

    return ParsedBoxScore(
        game_id=10,
        game_pk=777159,
        game_number=1,
        double_header=False,
        team_statistics=(
            away_team_statistics,
            home_team_statistics,
        ),
        pitcher_statistics=(
            winning_pitcher,
            saving_pitcher,
            losing_pitcher,
        ),
    )


def test_save_parsed_boxscore_commits_all_statistics() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)

    parsed_boxscore = _build_parsed_boxscore()

    save_parsed_boxscore(
        parsed_boxscore,
        connection_factory=lambda: connection,
    )

    assert len(cursor.executions) == 6

    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True


def test_save_parsed_boxscore_maps_game_parameters() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)

    parsed_boxscore = _build_parsed_boxscore()

    save_parsed_boxscore(
        parsed_boxscore,
        connection_factory=lambda: connection,
    )

    game_query, game_parameters = cursor.executions[0]

    assert "UPDATE games" in game_query
    assert game_parameters == (
        1,
        "single",
        10,
    )


def test_save_parsed_boxscore_maps_team_parameters() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)

    parsed_boxscore = _build_parsed_boxscore()

    save_parsed_boxscore(
        parsed_boxscore,
        connection_factory=lambda: connection,
    )

    team_query, team_parameters = cursor.executions[1]

    assert "INSERT INTO team_game_statistics" in team_query
    assert team_parameters == (
        10,
        101,
        False,
        2,
        8,
        0,
        34,
        38,
        2,
        0,
        1,
        3,
        0,
        9,
        1,
        0,
        1,
        0,
        27,
        4,
        4,
        7,
        1,
        2,
        8,
        7,
        1,
        "mlb_stats_api",
    )


def test_save_parsed_boxscore_maps_pitcher_parameters() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)

    parsed_boxscore = _build_parsed_boxscore()

    save_parsed_boxscore(
        parsed_boxscore,
        connection_factory=lambda: connection,
    )

    pitcher_query, pitcher_parameters = cursor.executions[3]

    assert (
        "INSERT INTO player_game_pitching_statistics"
        in pitcher_query
    )

    assert pitcher_parameters == (
        10,
        102,
        1001,
        1,
        True,
        18,
        24,
        5,
        2,
        2,
        1,
        2,
        0,
        6,
        0,
        92,
        61,
        "W",
        False,
        False,
        False,
        "mlb_stats_api",
    )


def test_save_parsed_boxscore_uses_doubleheader_status() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)

    original = _build_parsed_boxscore()

    parsed_boxscore = ParsedBoxScore(
        game_id=original.game_id,
        game_pk=original.game_pk,
        game_number=2,
        double_header=True,
        team_statistics=original.team_statistics,
        pitcher_statistics=original.pitcher_statistics,
    )

    save_parsed_boxscore(
        parsed_boxscore,
        connection_factory=lambda: connection,
    )

    _, game_parameters = cursor.executions[0]

    assert game_parameters == (
        2,
        "doubleheader",
        10,
    )


def test_save_parsed_boxscore_raises_when_game_is_missing() -> None:
    cursor = FakeCursor(game_rowcount=0)
    connection = FakeConnection(cursor)

    parsed_boxscore = _build_parsed_boxscore()

    with pytest.raises(
        LookupError,
        match="Canonical game does not exist: 10",
    ):
        save_parsed_boxscore(
            parsed_boxscore,
            connection_factory=lambda: connection,
        )

    assert len(cursor.executions) == 1
    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.closed is True


def test_save_parsed_boxscore_rolls_back_on_database_failure() -> None:
    cursor = FakeCursor(
        fail_on_execute_number=4,
    )
    connection = FakeConnection(cursor)

    parsed_boxscore = _build_parsed_boxscore()

    with pytest.raises(
        RuntimeError,
        match="database failure",
    ):
        save_parsed_boxscore(
            parsed_boxscore,
            connection_factory=lambda: connection,
        )

    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.closed is True