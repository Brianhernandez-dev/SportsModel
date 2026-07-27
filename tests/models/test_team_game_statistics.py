from dataclasses import FrozenInstanceError

import pytest

from sportsmodel.models.team_game_statistics import (
    TeamGameStatistics,
)


def build_team_game_statistics(
    **overrides: object,
) -> TeamGameStatistics:
    values: dict[str, object] = {
        "game_id": 100,
        "team_id": 10,
        "is_home": True,
        "runs": 5,
        "hits": 9,
        "errors": 1,
        "at_bats": 34,
        "plate_appearances": 38,
        "doubles": 2,
        "triples": 0,
        "home_runs": 1,
        "walks": 3,
        "intentional_walks": 0,
        "strikeouts": 8,
        "hit_by_pitch": 1,
        "sacrifice_flies": 0,
        "stolen_bases": 1,
        "caught_stealing": 0,
        "pitching_outs": 27,
        "runs_allowed": 3,
        "earned_runs_allowed": 3,
        "hits_allowed": 7,
        "home_runs_allowed": 1,
        "walks_allowed": 2,
        "strikeouts_recorded": 10,
        "left_on_base": 7,
        "double_plays": 1,
        "source_name": "mlb_stats",
    }

    values.update(overrides)

    return TeamGameStatistics(**values)


def test_team_game_statistics_stores_box_score() -> None:
    statistics = build_team_game_statistics()

    assert statistics.game_id == 100
    assert statistics.team_id == 10
    assert statistics.runs == 5
    assert statistics.pitching_outs == 27
    assert statistics.source_name == "mlb_stats"


def test_team_game_statistics_is_immutable() -> None:
    statistics = build_team_game_statistics()

    with pytest.raises(FrozenInstanceError):
        statistics.runs = 6


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("game_id", 0),
        ("team_id", -1),
    ],
)
def test_team_game_statistics_rejects_invalid_identifiers(
    field_name: str,
    field_value: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        build_team_game_statistics(
            **{field_name: field_value},
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "runs",
        "hits",
        "errors",
        "at_bats",
        "home_runs",
        "walks",
        "strikeouts",
        "pitching_outs",
        "runs_allowed",
        "earned_runs_allowed",
    ],
)
def test_team_game_statistics_rejects_negative_counts(
    field_name: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        build_team_game_statistics(
            **{field_name: -1},
        )


def test_team_game_statistics_rejects_excess_earned_runs() -> None:
    with pytest.raises(
        ValueError,
        match="cannot exceed",
    ):
        build_team_game_statistics(
            runs_allowed=3,
            earned_runs_allowed=4,
        )


def test_team_game_statistics_allows_missing_optional_counts() -> None:
    statistics = build_team_game_statistics(
        plate_appearances=None,
        left_on_base=None,
        double_plays=None,
    )

    assert statistics.plate_appearances is None
    assert statistics.left_on_base is None
    assert statistics.double_plays is None


def test_team_game_statistics_rejects_empty_source() -> None:
    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):
        build_team_game_statistics(
            source_name=" ",
        )
