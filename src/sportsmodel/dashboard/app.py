import streamlit as st

from sportsmodel.dashboard.views.daily_moneyline import (
    render as render_daily_moneyline,
)
from sportsmodel.dashboard.views.data_quality import (
    render as render_data_quality,
)
from sportsmodel.dashboard.views.moneyline_live import (
    render as render_moneyline_live,
)
from sportsmodel.dashboard.views.system_health import (
    render as render_system_health,
)


def main() -> None:
    """Run the SportsModel dashboard."""

    st.set_page_config(
        page_title="SportsModel",
        page_icon="⚾",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.title("SportsModel")

    page_name = st.sidebar.radio(
        label="Navigation",
        options=(
            "Daily Card",
            "Moneyline Live",
            "System Health",
            "Data Quality",
        ),
    )

    if page_name == "Daily Card":
        render_daily_moneyline()
        return

    if page_name == "Moneyline Live":
        render_moneyline_live()
        return

    if page_name == "System Health":
        render_system_health()
        return

    render_data_quality()


if __name__ == "__main__":
    main()
