from datetime import date, datetime, timezone

import pytest

from sportsmodel.orchestration.odds_snapshot_schedule import (
    resolve_snapshot_target_date,
)


REFERENCE_TIME = datetime(
    2026,
    8,
    7,
    1,
    49,
    tzinfo=timezone.utc,
)


def test_opening_targets_next_pacific_date() -> None:
    assert resolve_snapshot_target_date(
        "opening",
        REFERENCE_TIME,
    ) == date(2026, 8, 7)


@pytest.mark.parametrize(
    "snapshot_role",
    (
        "evening",
        "late_night",
    ),
)
def test_evening_roles_target_next_pacific_date(
    snapshot_role: str,
) -> None:
    assert resolve_snapshot_target_date(
        snapshot_role,
        REFERENCE_TIME,
    ) == date(2026, 8, 7)


def test_morning_targets_current_pacific_date() -> None:
    assert resolve_snapshot_target_date(
        "morning",
        REFERENCE_TIME,
    ) == date(2026, 8, 6)


def test_afternoon_targets_current_pacific_date() -> None:
    assert resolve_snapshot_target_date(
        "afternoon",
        REFERENCE_TIME,
    ) == date(2026, 8, 6)


def test_rejects_unsupported_fixed_role() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported fixed snapshot role",
    ):
        resolve_snapshot_target_date(
            "near_close",
            REFERENCE_TIME,
        )


def test_rejects_naive_current_time() -> None:
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        resolve_snapshot_target_date(
            "morning",
            datetime(2026, 8, 6, 6, 0),
        )
