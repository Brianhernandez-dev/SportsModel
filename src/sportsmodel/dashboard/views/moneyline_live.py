from datetime import datetime
from decimal import Decimal

import streamlit as st

from sportsmodel.auditing.moneyline_live_pipeline import (
    MoneylineLivePipelineAudit,
    audit_moneyline_live_pipeline,
)
from sportsmodel.database.moneyline_live_dashboard_repository import (
    build_moneyline_live_performance,
    get_moneyline_live_games,
    list_moneyline_live_slates,
)
from sportsmodel.models.moneyline_live_dashboard import (
    MoneylineLiveGame,
    MoneylineLiveSlate,
)


@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def load_moneyline_live_slates(
) -> tuple[MoneylineLiveSlate, ...]:
    """
    Load available Moneyline prediction and odds slates.
    """

    return list_moneyline_live_slates()


@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def load_moneyline_live_games(
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    policy_version: str,
) -> tuple[MoneylineLiveGame, ...]:
    """
    Load one persisted Moneyline slate.
    """

    return get_moneyline_live_games(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=(
            odds_ingestion_run_id
        ),
        policy_version=policy_version,
    )


@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def load_moneyline_live_audit(
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    policy_version: str,
) -> MoneylineLivePipelineAudit:
    """
    Load the integrity audit for one Moneyline slate.
    """

    return audit_moneyline_live_pipeline(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=(
            odds_ingestion_run_id
        ),
        policy_version=policy_version,
    )


def format_percent(
    value: Decimal | None,
) -> str:
    if value is None:
        return "Unavailable"

    return f"{float(value):.2%}"


def format_points(
    value: Decimal | None,
) -> str:
    if value is None:
        return "Unavailable"

    return (
        f"{float(value * Decimal('100')):+.2f} pp"
    )


def format_units(
    value: Decimal | None,
) -> str:
    if value is None:
        return "Pending"

    return f"{value:+.4f} units"


def format_price(
    price: int,
) -> str:
    return f"{price:+d}"


def format_datetime(
    value: datetime,
) -> str:
    return value.strftime(
        "%b %d, %Y %I:%M %p UTC"
    )


def format_slate(
    slate: MoneylineLiveSlate,
) -> str:
    return (
        f"{slate.target_date.isoformat()} — "
        f"Prediction Run {slate.prediction_run_id} / "
        f"Odds Run {slate.odds_ingestion_run_id} / "
        f"Policy {slate.policy_version}"
    )


def render_pipeline_state(
    audit: MoneylineLivePipelineAudit,
) -> None:
    """
    Render the current pipeline state with appropriate severity.
    """

    if audit.pipeline_state == "complete":
        st.success(
            "Pipeline state: **Complete** — all qualified "
            "paper candidates have been settled."
        )
        return

    if audit.pipeline_state == "awaiting_results":
        st.warning(
            "Pipeline state: **Awaiting results** — "
            f"{audit.pending_candidates} qualified paper "
            "candidate(s) remain unsettled."
        )
        return

    if audit.pipeline_state == "awaiting_evaluations":
        st.info(
            "Pipeline state: **Awaiting evaluations** — "
            "some predictions have not been evaluated "
            "against a stored odds run."
        )
        return

    st.error(
        "Pipeline state: **Invalid** — integrity issues "
        "were detected."
    )

    if audit.integrity_issues:
        st.code(
            "\n".join(
                audit.integrity_issues
            )
        )


def build_game_table(
    games: tuple[MoneylineLiveGame, ...],
) -> list[dict[str, object]]:
    """
    Build display rows for Streamlit.
    """

    rows: list[dict[str, object]] = []

    for game in games:
        if (
            game.home_score is not None
            and game.away_score is not None
        ):
            final_score = (
                f"{game.away_team_name} "
                f"{game.away_score}, "
                f"{game.home_team_name} "
                f"{game.home_score}"
            )
        else:
            final_score = "Pending"

        if game.outcome is not None:
            status = game.outcome.upper()
        elif game.qualifies_as_paper_candidate:
            status = "PAPER CANDIDATE"
        else:
            status = "NOT QUALIFIED"

        rows.append(
            {
                "Game": (
                    f"{game.away_team_name} at "
                    f"{game.home_team_name}"
                ),
                "Start": format_datetime(
                    game.game_start_time
                ),
                "Model lean": (
                    game.predicted_team_name
                ),
                "Model probability": (
                    format_percent(
                        game.model_probability
                    )
                ),
                "Market no-vig": (
                    format_percent(
                        game.market_no_vig_probability
                    )
                ),
                "Market edge": (
                    format_points(
                        game.model_market_edge
                    )
                ),
                "Best price": (
                    format_price(game.price)
                ),
                "Sportsbook": (
                    game.sportsbook_name
                ),
                "Model EV": (
                    format_percent(
                        game.model_expected_value
                    )
                ),
                "Starter coverage": (
                    game.starter_coverage.title()
                ),
                "Missing values": (
                    game.missing_raw_value_count
                ),
                "Paper candidate": (
                    "Yes"
                    if game.qualifies_as_paper_candidate
                    else "No"
                ),
                "Status": status,
                "Final score": final_score,
                "Profit": format_units(
                    game.profit_units
                ),
                "Exclusion reasons": (
                    ", ".join(
                        game.disqualification_reasons
                    )
                    if game.disqualification_reasons
                    else ""
                ),
            }
        )

    return rows


def render() -> None:
    """
    Render the live MLB Moneyline dashboard.
    """

    st.header("Moneyline Live")

    st.caption(
        "Read-only tracking for persisted MLB Moneyline "
        "predictions, market evaluations, paper candidates, "
        "and settlements."
    )

    try:
        slates = load_moneyline_live_slates()
    except Exception as error:
        st.error(
            "Unable to load available Moneyline slates."
        )
        st.code(str(error))
        return

    if not slates:
        st.info(
            "No evaluated Moneyline slates are currently "
            "stored."
        )
        return

    selected_slate = st.selectbox(
        label="Prediction and odds slate",
        options=slates,
        index=0,
        format_func=format_slate,
    )

    if selected_slate is None:
        return

    try:
        audit = load_moneyline_live_audit(
            prediction_run_id=(
                selected_slate.prediction_run_id
            ),
            odds_ingestion_run_id=(
                selected_slate.odds_ingestion_run_id
            ),
            policy_version=(
                selected_slate.policy_version
            ),
        )

        games = load_moneyline_live_games(
            prediction_run_id=(
                selected_slate.prediction_run_id
            ),
            odds_ingestion_run_id=(
                selected_slate.odds_ingestion_run_id
            ),
            policy_version=(
                selected_slate.policy_version
            ),
        )
    except Exception as error:
        st.error(
            "Unable to load the selected Moneyline slate."
        )
        st.code(str(error))
        return

    performance = (
        build_moneyline_live_performance(
            games
        )
    )

    render_pipeline_state(audit)

    st.subheader("Pipeline summary")

    (
        predictions_column,
        evaluations_column,
        candidates_column,
        settlements_column,
        pending_column,
    ) = st.columns(5)

    predictions_column.metric(
        label="Predictions",
        value=f"{audit.predictions:,}",
    )

    evaluations_column.metric(
        label="Evaluations",
        value=f"{audit.evaluations:,}",
    )

    candidates_column.metric(
        label="Paper candidates",
        value=f"{audit.paper_candidates:,}",
    )

    settlements_column.metric(
        label="Settlements",
        value=f"{audit.settlements:,}",
    )

    pending_column.metric(
        label="Pending",
        value=f"{audit.pending_candidates:,}",
    )

    with st.expander(
        "Pipeline identifiers and integrity"
    ):
        st.write(
            {
                "Prediction run ID": (
                    selected_slate
                    .prediction_run_id
                ),
                "Odds ingestion run ID": (
                    selected_slate
                    .odds_ingestion_run_id
                ),
                "Policy version": (
                    selected_slate.policy_version
                ),
                "Prediction status": (
                    audit.prediction_run_status
                ),
                "Odds status": (
                    audit.odds_ingestion_run_status
                ),
                "Odds snapshots": (
                    audit.odds_snapshots
                ),
                "Odds games": (
                    audit.odds_games
                ),
                "Duplicate prediction games": (
                    audit.duplicate_prediction_games
                ),
                "Duplicate evaluations": (
                    audit.duplicate_evaluations
                ),
                "Duplicate settlements": (
                    audit.duplicate_settlements
                ),
                "Integrity issues": (
                    list(audit.integrity_issues)
                ),
            }
        )

    st.subheader("Forward paper performance")

    (
        record_column,
        profit_column,
        roi_column,
        average_ev_column,
        drawdown_column,
    ) = st.columns(5)

    record_column.metric(
        label="Record",
        value=(
            f"{performance.wins}-"
            f"{performance.losses}-"
            f"{performance.pushes}"
        ),
    )

    profit_column.metric(
        label="Profit",
        value=format_units(
            performance.profit_units
        ),
    )

    roi_column.metric(
        label="ROI",
        value=format_percent(
            performance.roi
        ),
    )

    average_ev_column.metric(
        label="Average model EV",
        value=format_percent(
            performance
            .average_model_expected_value
        ),
    )

    drawdown_column.metric(
        label="Maximum drawdown",
        value=(
            f"{performance.maximum_drawdown_units:.4f} "
            "units"
        ),
    )

    st.caption(
        f"Units staked: {performance.units_staked} · "
        f"Settled decisions: "
        f"{performance.wins + performance.losses} · "
        f"Win rate: "
        f"{format_percent(performance.win_rate)}"
    )

    st.subheader("Game predictions and evaluations")

    st.dataframe(
        build_game_table(games),
        use_container_width=True,
        hide_index=True,
    )

    if st.button(
        "Refresh Moneyline live data"
    ):
        st.cache_data.clear()
        st.rerun()
