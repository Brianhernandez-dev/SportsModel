import streamlit as st


def render() -> None:
    """
    Render the initial SportsModel data-quality page.
    """

    st.header("Data Quality")

    st.info(
        "The first database-backed checks will cover "
        "training eligibility and feature prerequisites."
    )

    st.subheader("Planned checks")

    st.write(
        "- Games excluded from training\n"
        "- Missing team statistics\n"
        "- Missing starting pitchers\n"
        "- Missing player pitching data\n"
        "- Duplicate game mappings\n"
        "- Feature null counts\n"
        "- Feature minimum and maximum values"
    )
