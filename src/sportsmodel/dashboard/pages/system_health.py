import streamlit as st

from sportsmodel.features.builders.game_feature_vector import (
    DEFAULT_FEATURE_SCHEMA_VERSION,
)


def render() -> None:
    """
    Render the initial SportsModel system-health page.
    """

    st.header("System Health")

    schema_column, model_column, database_column = (
        st.columns(3)
    )

    schema_column.metric(
        label="Feature schema",
        value=DEFAULT_FEATURE_SCHEMA_VERSION,
    )

    model_column.metric(
        label="Model status",
        value="Research",
    )

    database_column.metric(
        label="Database monitoring",
        value="Pending",
    )

    st.info(
        "Database-backed health metrics will be added in "
        "the next dashboard checkpoint."
    )

    st.subheader("Planned monitoring")

    st.write(
        "- Latest results ingestion\n"
        "- Latest odds snapshot\n"
        "- Eligible completed games\n"
        "- Games with complete feature data\n"
        "- Current model version\n"
        "- Failed or incomplete records"
    )
