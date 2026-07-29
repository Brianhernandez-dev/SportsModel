import streamlit as st

from sportsmodel.dashboard.views.data_quality import (
    render as render_data_quality,
)
from sportsmodel.dashboard.views.system_health import (
    render as render_system_health,
)


def main() -> None:
    """
    Run the SportsModel Control Center.
    """

    st.set_page_config(
        page_title="SportsModel Control Center",
        page_icon="?",
        layout="wide",
    )

    st.title("SportsModel Control Center")

    page_name = st.sidebar.radio(
        label="Navigation",
        options=(
            "System Health",
            "Data Quality",
        ),
    )

    if page_name == "System Health":
        render_system_health()
        return

    render_data_quality()


if __name__ == "__main__":
    main()
