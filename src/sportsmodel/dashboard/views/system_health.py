from datetime import date, datetime

import streamlit as st

from sportsmodel.database.control_center_repository import (
    get_system_health_summary,
)
from sportsmodel.features.builders.game_feature_vector import (
    DEFAULT_FEATURE_SCHEMA_VERSION,
)
from sportsmodel.models.system_health_summary import (
    SystemHealthSummary,
)


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def load_system_health_summary() -> SystemHealthSummary:
    """
    Load current read-only system-health metrics.
    """

    return get_system_health_summary()


def format_count(value: int) -> str:
    """
    Format an integer for dashboard display.
    """

    return f"{value:,}"


def format_date(value: date | None) -> str:
    """
    Format a date for dashboard display.
    """

    if value is None:
        return "Unavailable"

    return value.strftime("%b %d, %Y")


def format_datetime(value: datetime | None) -> str:
    """
    Format a timestamp in UTC for dashboard display.
    """

    if value is None:
        return "Unavailable"

    return value.strftime(
        "%b %d, %Y %I:%M %p UTC"
    )


def get_odds_status(
    summary: SystemHealthSummary,
) -> tuple[str, str]:
    """
    Return a user-facing odds status and severity.
    """

    status = summary.latest_odds_run_status
    error_message = (
        summary.latest_odds_run_error_message or ""
    )

    quota_exhausted = (
        "OUT_OF_USAGE_CREDITS" in error_message
        or "Usage quota has been reached" in error_message
    )

    if quota_exhausted:
        return (
            "Paused - quota exhausted",
            "warning",
        )

    if status is None:
        return (
            "No ingestion runs",
            "neutral",
        )

    if status.casefold() == "completed":
        return (
            "Operational",
            "success",
        )

    if status.casefold() == "failed":
        return (
            "Failed",
            "error",
        )

    return (
        status.replace("_", " ").title(),
        "neutral",
    )


def render_odds_status(
    status_text: str,
    severity: str,
) -> None:
    """
    Render the current odds-ingestion state.
    """

    message = (
        f"Odds ingestion status: **{status_text}**"
    )

    if severity == "success":
        st.success(message)
        return

    if severity == "warning":
        st.warning(message)
        return

    if severity == "error":
        st.error(message)
        return

    st.info(message)


def render() -> None:
    """
    Render the SportsModel system-health page.
    """

    st.header("System Health")

    try:
        summary = load_system_health_summary()
    except Exception as error:
        st.error(
            "Unable to load SportsModel health metrics."
        )
        st.code(str(error))
        return

    feature_complete_games = min(
        summary.games_with_complete_team_statistics_count,
        summary.games_with_pitching_statistics_count,
    )

    excluded_completed_games = max(
        summary.completed_games_count
        - feature_complete_games,
        0,
    )

    (
        schema_column,
        completed_column,
        eligible_column,
        latest_date_column,
    ) = st.columns(4)

    schema_column.metric(
        label="Feature schema",
        value=DEFAULT_FEATURE_SCHEMA_VERSION,
    )

    completed_column.metric(
        label="Completed results",
        value=format_count(
            summary.completed_games_count
        ),
    )

    eligible_column.metric(
        label="Feature-complete games",
        value=format_count(
            feature_complete_games
        ),
    )

    latest_date_column.metric(
        label="Latest completed date",
        value=format_date(
            summary.latest_completed_game_date
        ),
    )

    if excluded_completed_games == 1:
        st.success(
            "Core baseball data is healthy. The one "
            "completed game excluded from regular-season "
            "feature coverage is the 2026 MLB All-Star Game."
        )
    elif excluded_completed_games == 0:
        st.success(
            "Every completed game has complete team and "
            "pitching statistics."
        )
    else:
        st.warning(
            f"{excluded_completed_games:,} completed games "
            "do not currently have complete feature "
            "statistics."
        )

    st.subheader("Database coverage")

    (
        canonical_column,
        team_stats_column,
        pitching_column,
    ) = st.columns(3)

    canonical_column.metric(
        label="Canonical game records",
        value=format_count(
            summary.canonical_games_count
        ),
    )

    team_stats_column.metric(
        label="Games with team statistics",
        value=format_count(
            summary.games_with_complete_team_statistics_count
        ),
    )

    pitching_column.metric(
        label="Games with pitching statistics",
        value=format_count(
            summary.games_with_pitching_statistics_count
        ),
    )

    st.subheader("Odds ingestion")

    odds_status, odds_severity = get_odds_status(
        summary
    )

    render_odds_status(
        odds_status,
        odds_severity,
    )

    (
        snapshot_count_column,
        latest_snapshot_column,
        latest_run_column,
    ) = st.columns(3)

    snapshot_count_column.metric(
        label="Stored odds snapshots",
        value=format_count(
            summary.odds_snapshot_count
        ),
    )

    latest_snapshot_column.metric(
        label="Latest odds snapshot",
        value=format_datetime(
            summary.latest_odds_snapshot_time
        ),
    )

    latest_run_column.metric(
        label="Latest ingestion run",
        value=format_datetime(
            summary.latest_odds_run_started_at
        ),
    )

    if (
        odds_severity == "error"
        and summary.latest_odds_run_error_message
    ):
        with st.expander(
            "Latest odds-ingestion error"
        ):
            st.code(
                summary.latest_odds_run_error_message
            )

    if st.button("Refresh health metrics"):
        st.cache_data.clear()
        st.rerun()
