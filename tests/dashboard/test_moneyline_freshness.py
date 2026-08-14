from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sportsmodel.dashboard.moneyline_freshness import (
    AUTOMATION_ATTENTION_NEEDED,
    CURRENT,
    PREVIEW_NOT_GENERATED,
    STALE,
    WAITING_FOR_EVENING_REFRESH,
    WAITING_FOR_LATE_NIGHT_REFRESH,
    WAITING_FOR_MORNING_WORKFLOW,
    classify_official_freshness,
    classify_preview_freshness,
)


PACIFIC = ZoneInfo(
    "America/Los_Angeles"
)


def test_official_card_is_current():
    target = date(2026, 8, 10)

    assert classify_official_freshness(
        now=datetime(
            2026,
            8,
            10,
            20,
            0,
            tzinfo=PACIFIC,
        ),
        target_date=target,
        has_card=True,
        prediction_completed_at=datetime(
            2026,
            8,
            10,
            15,
            0,
            7,
            tzinfo=timezone.utc,
        ),
        market_snapshot_time=datetime(
            2026,
            8,
            10,
            15,
            0,
            10,
            tzinfo=timezone.utc,
        ),
    ) == CURRENT


def test_official_waits_before_morning_deadline():
    target = date(2026, 8, 10)

    assert classify_official_freshness(
        now=datetime(
            2026,
            8,
            10,
            8,
            5,
            tzinfo=PACIFIC,
        ),
        target_date=target,
        has_card=False,
    ) == WAITING_FOR_MORNING_WORKFLOW


def test_official_missing_after_deadline_needs_attention():
    target = date(2026, 8, 10)

    assert classify_official_freshness(
        now=datetime(
            2026,
            8,
            10,
            8,
            20,
            tzinfo=PACIFIC,
        ),
        target_date=target,
        has_card=False,
    ) == AUTOMATION_ATTENTION_NEEDED


def test_official_wrong_day_is_stale():
    assert classify_official_freshness(
        now=datetime(
            2026,
            8,
            10,
            12,
            0,
            tzinfo=PACIFIC,
        ),
        target_date=date(
            2026,
            8,
            9,
        ),
        has_card=True,
        prediction_completed_at=datetime(
            2026,
            8,
            9,
            15,
            0,
            tzinfo=timezone.utc,
        ),
        market_snapshot_time=datetime(
            2026,
            8,
            9,
            15,
            0,
            tzinfo=timezone.utc,
        ),
    ) == STALE


def test_preview_not_generated_before_evening_window():
    assert classify_preview_freshness(
        now=datetime(
            2026,
            8,
            10,
            18,
            0,
            tzinfo=PACIFIC,
        ),
        target_date=date(
            2026,
            8,
            11,
        ),
        has_preview=False,
    ) == PREVIEW_NOT_GENERATED


def test_missing_preview_after_evening_window_needs_attention():
    assert classify_preview_freshness(
        now=datetime(
            2026,
            8,
            10,
            19,
            5,
            tzinfo=PACIFIC,
        ),
        target_date=date(
            2026,
            8,
            11,
        ),
        has_preview=False,
    ) == AUTOMATION_ATTENTION_NEEDED


def test_opening_preview_waits_for_evening_refresh():
    assert classify_preview_freshness(
        now=datetime(
            2026,
            8,
            10,
            20,
            0,
            tzinfo=PACIFIC,
        ),
        target_date=date(
            2026,
            8,
            11,
        ),
        has_preview=True,
        market_snapshot_role="opening",
        prediction_completed_at=datetime(
            2026,
            8,
            10,
            18,
            45,
            tzinfo=PACIFIC,
        ),
        market_snapshot_time=datetime(
            2026,
            8,
            10,
            18,
            30,
            tzinfo=PACIFIC,
        ),
    ) == WAITING_FOR_EVENING_REFRESH

def test_opening_preview_after_1115_needs_attention():
    assert classify_preview_freshness(
        now=datetime(
            2026,
            8,
            10,
            23,
            20,
            tzinfo=PACIFIC,
        ),
        target_date=date(
            2026,
            8,
            11,
        ),
        has_preview=True,
        market_snapshot_role="opening",
        prediction_completed_at=datetime(
            2026,
            8,
            11,
            1,
            45,
            tzinfo=timezone.utc,
        ),
        market_snapshot_time=datetime(
            2026,
            8,
            11,
            1,
            30,
            tzinfo=timezone.utc,
        ),
    ) == AUTOMATION_ATTENTION_NEEDED


def test_late_night_preview_is_current():
    assert classify_preview_freshness(
        now=datetime(
            2026,
            8,
            10,
            23,
            5,
            tzinfo=PACIFIC,
        ),
        target_date=date(
            2026,
            8,
            11,
        ),
        has_preview=True,
        market_snapshot_role="late_night",
        prediction_completed_at=datetime(
            2026,
            8,
            11,
            1,
            45,
            tzinfo=timezone.utc,
        ),
        market_snapshot_time=datetime(
            2026,
            8,
            11,
            6,
            0,
            tzinfo=timezone.utc,
        ),
    ) == CURRENT


def test_preview_wrong_snapshot_day_is_stale():
    assert classify_preview_freshness(
        now=datetime(
            2026,
            8,
            10,
            20,
            0,
            tzinfo=PACIFIC,
        ),
        target_date=date(
            2026,
            8,
            11,
        ),
        has_preview=True,
        market_snapshot_role="opening",
        prediction_completed_at=datetime(
            2026,
            8,
            11,
            1,
            45,
            tzinfo=timezone.utc,
        ),
        market_snapshot_time=datetime(
            2026,
            8,
            9,
            1,
            30,
            tzinfo=timezone.utc,
        ),
    ) == STALE


def test_opening_preview_after_845_needs_attention():
    assert classify_preview_freshness(
        now=datetime(
            2026,
            8,
            10,
            20,
            46,
            tzinfo=PACIFIC,
        ),
        target_date=date(
            2026,
            8,
            11,
        ),
        has_preview=True,
        market_snapshot_role="opening",
        prediction_completed_at=datetime(
            2026,
            8,
            10,
            18,
            45,
            tzinfo=PACIFIC,
        ),
        market_snapshot_time=datetime(
            2026,
            8,
            10,
            18,
            30,
            tzinfo=PACIFIC,
        ),
    ) == AUTOMATION_ATTENTION_NEEDED


def test_evening_preview_waits_for_late_night_refresh():
    assert classify_preview_freshness(
        now=datetime(
            2026,
            8,
            10,
            21,
            0,
            tzinfo=PACIFIC,
        ),
        target_date=date(
            2026,
            8,
            11,
        ),
        has_preview=True,
        market_snapshot_role="evening",
        prediction_completed_at=datetime(
            2026,
            8,
            10,
            18,
            45,
            tzinfo=PACIFIC,
        ),
        market_snapshot_time=datetime(
            2026,
            8,
            10,
            20,
            30,
            tzinfo=PACIFIC,
        ),
    ) == WAITING_FOR_LATE_NIGHT_REFRESH


def test_evening_preview_after_1115_needs_attention():
    assert classify_preview_freshness(
        now=datetime(
            2026,
            8,
            10,
            23,
            20,
            tzinfo=PACIFIC,
        ),
        target_date=date(
            2026,
            8,
            11,
        ),
        has_preview=True,
        market_snapshot_role="evening",
        prediction_completed_at=datetime(
            2026,
            8,
            10,
            18,
            45,
            tzinfo=PACIFIC,
        ),
        market_snapshot_time=datetime(
            2026,
            8,
            10,
            20,
            30,
            tzinfo=PACIFIC,
        ),
    ) == AUTOMATION_ATTENTION_NEEDED
