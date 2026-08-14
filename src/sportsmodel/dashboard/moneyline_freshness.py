from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


PACIFIC_TIME_ZONE = ZoneInfo(
    "America/Los_Angeles"
)

CURRENT = "CURRENT"

WAITING_FOR_MORNING_WORKFLOW = (
    "WAITING FOR MORNING WORKFLOW"
)

WAITING_FOR_EVENING_REFRESH = (
    "WAITING FOR EVENING REFRESH"
)

WAITING_FOR_LATE_NIGHT_REFRESH = (
    "WAITING FOR LATE-NIGHT REFRESH"
)

PREVIEW_NOT_GENERATED = (
    "PREVIEW NOT GENERATED"
)

STALE = "STALE"

AUTOMATION_ATTENTION_NEEDED = (
    "AUTOMATION ATTENTION NEEDED"
)


def classify_official_freshness(
    *,
    now: datetime,
    target_date: date,
    has_card: bool,
    prediction_completed_at: datetime | None = None,
    market_snapshot_time: datetime | None = None,
) -> str:
    """
    Classify today's official Moneyline card.
    """

    _require_timezone_aware(now)

    now_pacific = now.astimezone(
        PACIFIC_TIME_ZONE
    )

    deadline = _pacific_datetime(
        target_date,
        hour=8,
        minute=15,
    )

    if not has_card:
        if now_pacific < deadline:
            return WAITING_FOR_MORNING_WORKFLOW

        return AUTOMATION_ATTENTION_NEEDED

    if target_date != now_pacific.date():
        return STALE

    if (
        prediction_completed_at is None
        or market_snapshot_time is None
    ):
        return STALE

    if (
        _pacific_date(
            prediction_completed_at
        )
        != target_date
    ):
        return STALE

    if (
        _pacific_date(
            market_snapshot_time
        )
        != target_date
    ):
        return STALE

    return CURRENT


def classify_preview_freshness(
    *,
    now: datetime,
    target_date: date,
    has_preview: bool,
    market_snapshot_role: str | None = None,
    prediction_completed_at: datetime | None = None,
    market_snapshot_time: datetime | None = None,
) -> str:
    """
    Classify tomorrow's preview and market-refresh state.
    """

    _require_timezone_aware(now)

    now_pacific = now.astimezone(
        PACIFIC_TIME_ZONE
    )

    expected_preview_date = (
        target_date
        - timedelta(days=1)
    )

    preview_deadline = _pacific_datetime(
        expected_preview_date,
        hour=19,
        minute=0,
    )

    evening_deadline = _pacific_datetime(
        expected_preview_date,
        hour=20,
        minute=45,
    )

    late_night_deadline = _pacific_datetime(
        expected_preview_date,
        hour=23,
        minute=15,
    )

    if not has_preview:
        if now_pacific < preview_deadline:
            return PREVIEW_NOT_GENERATED

        return AUTOMATION_ATTENTION_NEEDED

    if (
        target_date
        != now_pacific.date()
        + timedelta(days=1)
    ):
        return STALE

    if (
        prediction_completed_at is None
        or market_snapshot_time is None
    ):
        return STALE

    if (
        _pacific_date(
            prediction_completed_at
        )
        != expected_preview_date
    ):
        return STALE

    if (
        _pacific_date(
            market_snapshot_time
        )
        != expected_preview_date
    ):
        return STALE

    if market_snapshot_role == "late_night":
        return CURRENT

    if market_snapshot_role == "evening":
        if now_pacific < late_night_deadline:
            return (
                WAITING_FOR_LATE_NIGHT_REFRESH
            )

        return AUTOMATION_ATTENTION_NEEDED

    if market_snapshot_role == "opening":
        if now_pacific < evening_deadline:
            return (
                WAITING_FOR_EVENING_REFRESH
            )

        return AUTOMATION_ATTENTION_NEEDED

    return STALE


def _pacific_datetime(
    value: date,
    *,
    hour: int,
    minute: int,
) -> datetime:
    return datetime(
        value.year,
        value.month,
        value.day,
        hour,
        minute,
        tzinfo=PACIFIC_TIME_ZONE,
    )


def _pacific_date(
    value: datetime,
) -> date:
    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            "Persisted timestamp must be timezone-aware."
        )

    return value.astimezone(
        PACIFIC_TIME_ZONE
    ).date()


def _require_timezone_aware(
    value: datetime,
) -> None:
    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            "Current time must be timezone-aware."
        )
