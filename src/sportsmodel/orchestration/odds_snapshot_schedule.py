from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


PACIFIC_TIME_ZONE = ZoneInfo("America/Los_Angeles")

FIXED_SNAPSHOT_ROLES = frozenset(
    {
        "opening",
        "evening",
        "late_night",
        "morning",
        "afternoon",
    }
)


def resolve_snapshot_target_date(
    snapshot_role: str,
    current_time: datetime | None = None,
) -> date:
    """
    Resolve the Pacific MLB slate date for a fixed snapshot role.
    """

    normalized_role = snapshot_role.strip().lower()

    if normalized_role not in FIXED_SNAPSHOT_ROLES:
        raise ValueError(
            "Unsupported fixed snapshot role: "
            f"{snapshot_role}"
        )

    resolved_time = (
        current_time
        if current_time is not None
        else datetime.now(timezone.utc)
    )

    if resolved_time.tzinfo is None:
        raise ValueError(
            "Current time must be timezone-aware."
        )

    pacific_date = (
        resolved_time
        .astimezone(PACIFIC_TIME_ZONE)
        .date()
    )

    if normalized_role in {
        "opening",
        "evening",
        "late_night",
    }:
        return pacific_date + timedelta(days=1)

    return pacific_date
