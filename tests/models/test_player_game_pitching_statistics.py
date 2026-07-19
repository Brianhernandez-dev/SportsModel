from dataclasses import FrozenInstanceError

import pytest

from sportsmodel.models.player_game_pitching_statistics import (
    PitchingDecision,
    PlayerGamePitchingStatistics,
)


def build_pitching_statistics(
    **overrides: object,
) -> PlayerGamePitchingStatistics:
    values: dict[str, object] = {
        "game_id": 100,
        "team_id": 10,
        "baseball_player_id": 500,
        "appearance_order": 1,
        "is_starter": True,
        "pitching_outs": 18,
        "batters_faced": 24,
        "hits_allowed": 5,
        "runs_allowed": 2,
        "earned_runs_allowed": 2,
        "home_runs_allowed": 1,
        "walks_allowed": 2,
        "intentional_walks_allowed": 0,
        "strikeouts": 7,
        "hit_batters": 0,
        "pitches_thrown": 94,
        "strikes_thrown": 61,
        "decision": PitchingDecision.WIN,
        "save_recorded": False,
        "hold_recorded": False,
        "blown_save_recorded": False,
        "source_name": "mlb_stats",
    }

    values.update(overrides)

    return PlayerGamePitchingStatistics(**values)


def test_pitching_statistics_stores_appearance() -> None:
    statistics = build_pitching_statistics()

    assert statistics.baseball_player_id == 500
    assert statistics.appearance_order == 1
    assert statistics.is_starter is True
    assert statistics.pitching_outs == 18
    assert statistics.decision == PitchingDecision.WIN


def test_pitching_statistics_is_immutable() -> None:
    statistics = build_pitching_statistics()

    with pytest.raises(FrozenInstanceError):
        statistics.pitching_outs = 21


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("game_id", 0),
        ("team_id", -1),
        ("baseball_player_id", 0),
        ("appearance_order", 0),
    ],
)
def test_pitching_statistics_rejects_invalid_identity_fields(
    field_name: str,
    field_value: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        build_pitching_statistics(
            **{field_name: field_value},
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "pitching_outs",
        "hits_allowed",
        "runs_allowed",
        "earned_runs_allowed",
        "home_runs_allowed",
        "walks_allowed",
        "strikeouts",
        "hit_batters",
    ],
)
def test_pitching_statistics_rejects_negative_counts(
    field_name: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        build_pitching_statistics(
            **{field_name: -1},
        )


def test_pitching_statistics_rejects_excess_earned_runs() -> None:
    with pytest.raises(
        ValueError,
        match="cannot exceed",
    ):
        build_pitching_statistics(
            runs_allowed=2,
            earned_runs_allowed=3,
        )


def test_pitching_statistics_rejects_excess_strikes() -> None:
    with pytest.raises(
        ValueError,
        match="cannot exceed",
    ):
        build_pitching_statistics(
            pitches_thrown=90,
            strikes_thrown=91,
        )


def test_pitching_statistics_allows_missing_pitch_counts() -> None:
    statistics = build_pitching_statistics(
        batters_faced=None,
        pitches_thrown=None,
        strikes_thrown=None,
        decision=None,
    )

    assert statistics.batters_faced is None
    assert statistics.pitches_thrown is None
    assert statistics.strikes_thrown is None
    assert statistics.decision is None


def test_pitching_statistics_rejects_empty_source() -> None:
    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):
        build_pitching_statistics(
            source_name="",
        )
