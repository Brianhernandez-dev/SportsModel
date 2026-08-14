from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from sportsmodel.analysis.moneyline_cohort_comparison import (
    AWAITING_OFFICIAL,
    load_moneyline_cohort_comparison,
)
from sportsmodel.analysis.moneyline_preview_dashboard_service import (
    build_moneyline_preview_dashboard,
)
from sportsmodel.analysis.moneyline_overnight_review import (
    MODEL_LEAN_CHANGED,
    NEW_MORNING_VALUE,
    NO_VALUE,
    STILL_POLICY_BLOCKED,
    SURVIVED_TO_MORNING,
    VALUE_LOST_OVERNIGHT,
    build_moneyline_overnight_review,
)
from sportsmodel.analysis.probability import (
    probability_to_american_odds,
)
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
from sportsmodel.dashboard.moneyline_presenter import (
    format_exclusion_reasons,
    format_percent,
    format_points,
    format_price,
    format_units,
    get_candidate_games,
)
from sportsmodel.database.moneyline_dashboard_status_repository import (
    get_moneyline_run_timing,
)
from sportsmodel.database.moneyline_live_dashboard_repository import (
    build_moneyline_live_performance,
    get_moneyline_live_games,
    list_moneyline_live_slates,
)


PACIFIC_TIME_ZONE = ZoneInfo(
    "America/Los_Angeles"
)


@st.cache_data(ttl=60)
def _load_slates():
    return list_moneyline_live_slates()


@st.cache_data(ttl=60)
def _load_games(
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    policy_version: str,
):
    return get_moneyline_live_games(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
        policy_version=policy_version,
    )


@st.cache_data(ttl=60)
def _load_preview(
    target_date: date,
):
    return build_moneyline_preview_dashboard(
        target_date=target_date,
    )


@st.cache_data(ttl=60)
def _load_run_timing(
    prediction_run_id: int,
    odds_ingestion_run_id: int,
):
    return get_moneyline_run_timing(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
    )


@st.cache_data(ttl=60)
def _load_cohort_comparison(target_date: date):
    return load_moneyline_cohort_comparison(
        target_date=target_date,
    )


def render() -> None:
    now = datetime.now(
        PACIFIC_TIME_ZONE
    )

    today = now.date()
    tomorrow = today + timedelta(days=1)

    st.header("MLB Moneyline")

    st.caption(
        "Daily model card | "
        f"{now.strftime('%b %d, %Y %I:%M %p')} Pacific"
    )

    today_tab, tomorrow_tab, comparison_tab, results_tab = st.tabs(
        (
            "TODAY",
            "TOMORROW",
            "EARLY VS OFFICIAL",
            "RESULTS",
        )
    )

    with today_tab:
        _render_today(today)

    with tomorrow_tab:
        _render_tomorrow(tomorrow)

    with comparison_tab:
        _render_cohort_comparison(today)

    with results_tab:
        _render_results()


def _render_cohort_comparison(target_date: date) -> None:
    st.subheader(
        f"Early Entry vs Official - {_format_date(target_date)}"
    )
    st.caption(
        "Separate one-unit records from persisted qualified bets. "
        "Price movement is Official price minus Early Entry price."
    )

    try:
        comparison = _load_cohort_comparison(target_date)
    except Exception:
        st.error("Early Entry comparison could not be loaded.")
        return

    early_column, official_column = st.columns(2)
    with early_column:
        _render_cohort_performance(
            title="Early Entry",
            performance=comparison.early_entry,
            detail="Preview prediction + late-night snapshot",
        )

    with official_column:
        _render_cohort_performance(
            title="Official",
            performance=comparison.official,
            detail="Persisted 8 AM daily workflow card",
        )

    if not comparison.official_exists:
        st.info(AWAITING_OFFICIAL)

    if not comparison.rows:
        st.info("No qualified Early Entry or Official bets for this date.")
        return

    st.dataframe(
        [
            {
                "Start": _format_start(row.game_start_time),
                "Matchup": row.matchup,
                "Selection": row.selection_name,
                "Early Entry price": (
                    format_price(row.early_entry_price)
                    if row.early_entry_price is not None
                    else "-"
                ),
                "Official price": (
                    format_price(row.official_price)
                    if row.official_price is not None
                    else "-"
                ),
                "Price movement": (
                    f"{row.price_movement:+d}"
                    if row.price_movement is not None
                    else "-"
                ),
                "Status": row.status,
            }
            for row in comparison.rows
        ],
        use_container_width=True,
        hide_index=True,
    )


def _render_cohort_performance(
    *,
    title: str,
    performance,
    detail: str,
) -> None:
    st.markdown(f"### {title}")
    st.caption(detail)
    qualified_column, settled_column, pending_column = st.columns(3)
    qualified_column.metric("Qualified bets", performance.qualified_bets)
    settled_column.metric("Settled", performance.settled)
    pending_column.metric("Pending", performance.pending)

    record_column, profit_column, roi_column = st.columns(3)
    record_column.metric(
        "W-L-P",
        f"{performance.wins}-{performance.losses}-{performance.pushes}",
    )
    profit_column.metric(
        "Profit units",
        format_units(performance.profit_units),
    )
    roi_column.metric("ROI", format_percent(performance.roi))



def _render_status_message(
    *,
    status: str,
    headline: str,
    detail: str,
) -> None:
    message = (
        f"{headline}\n\n"
        f"{detail}"
    )

    if status == CURRENT:
        st.success(message)
        return

    if status in (
        WAITING_FOR_MORNING_WORKFLOW,
        WAITING_FOR_EVENING_REFRESH,
        WAITING_FOR_LATE_NIGHT_REFRESH,
        PREVIEW_NOT_GENERATED,
    ):
        st.info(message)
        return

    if status == STALE:
        st.warning(message)
        return

    if status == AUTOMATION_ATTENTION_NEEDED:
        st.error(message)
        return

    st.warning(message)


def _render_missing_official_status(
    target_date: date,
) -> None:
    status = classify_official_freshness(
        now=datetime.now(
            PACIFIC_TIME_ZONE
        ),
        target_date=target_date,
        has_card=False,
    )

    if status == WAITING_FOR_MORNING_WORKFLOW:
        headline = (
            "OFFICIAL CARD - "
            "WAITING FOR MORNING WORKFLOW"
        )

        detail = (
            "Today's official card is expected "
            "after the 8:00 AM workflow."
        )

    else:
        headline = (
            "OFFICIAL CARD - "
            "AUTOMATION ATTENTION NEEDED"
        )

        detail = (
            "The normal morning window has passed "
            "and no official card is stored."
        )

    _render_status_message(
        status=status,
        headline=headline,
        detail=detail,
    )


def _render_official_freshness_status(
    *,
    target_date: date,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
) -> None:
    try:
        timing = _load_run_timing(
            prediction_run_id,
            odds_ingestion_run_id,
        )

    except Exception:
        _render_status_message(
            status=STALE,
            headline="OFFICIAL CARD - STALE",
            detail=(
                "The card exists, but persisted "
                "run timing could not be verified."
            ),
        )
        return

    status = classify_official_freshness(
        now=datetime.now(
            PACIFIC_TIME_ZONE
        ),
        target_date=target_date,
        has_card=True,
        prediction_completed_at=(
            timing.prediction_completed_at
        ),
        market_snapshot_time=(
            timing.market_snapshot_time
        ),
    )

    prediction_time = (
        _format_start(
            timing.prediction_completed_at
        )
        if timing.prediction_completed_at
        else "Unavailable"
    )

    market_time = (
        _format_start(
            timing.market_snapshot_time
        )
        if timing.market_snapshot_time
        else "Unavailable"
    )

    _render_status_message(
        status=status,
        headline=(
            f"OFFICIAL CARD - {status}"
        ),
        detail=(
            f"Model generated {prediction_time} | "
            f"Entry market captured {market_time}"
        ),
    )


def _render_missing_preview_status(
    *,
    target_date: date,
    message: str,
) -> None:
    status = classify_preview_freshness(
        now=datetime.now(
            PACIFIC_TIME_ZONE
        ),
        target_date=target_date,
        has_preview=False,
    )

    if status == PREVIEW_NOT_GENERATED:
        headline = (
            "TOMORROW PREVIEW - NOT GENERATED YET"
        )

        detail = (
            "This is expected before the evening "
            "opening/preview workflow."
        )

    else:
        headline = (
            "TOMORROW PREVIEW - "
            "AUTOMATION ATTENTION NEEDED"
        )

        detail = (
            "The normal preview window has passed "
            "without a completed preview."
        )

    _render_status_message(
        status=status,
        headline=headline,
        detail=detail,
    )

    st.caption(message)


def _render_preview_freshness_status(
    *,
    target_date: date,
    preview,
) -> None:
    try:
        timing = _load_run_timing(
            preview.prediction_run_id,
            preview.odds_ingestion_run_id,
        )

    except Exception:
        _render_status_message(
            status=STALE,
            headline="TOMORROW PREVIEW - STALE",
            detail=(
                "The preview exists, but persisted "
                "run timing could not be verified."
            ),
        )
        return

    status = classify_preview_freshness(
        now=datetime.now(
            PACIFIC_TIME_ZONE
        ),
        target_date=target_date,
        has_preview=True,
        market_snapshot_role=(
            preview.market_snapshot_role
        ),
        prediction_completed_at=(
            timing.prediction_completed_at
        ),
        market_snapshot_time=(
            timing.market_snapshot_time
        ),
    )

    prediction_time = (
        _format_start(
            timing.prediction_completed_at
        )
        if timing.prediction_completed_at
        else "Unavailable"
    )

    market_time = (
        _format_start(
            timing.market_snapshot_time
        )
        if timing.market_snapshot_time
        else "Unavailable"
    )

    if (
        status
        == WAITING_FOR_EVENING_REFRESH
    ):
        headline = (
            "OPENING PREVIEW - CURRENT"
        )

        detail = (
            f"Model generated {prediction_time} | "
            f"Opening market captured {market_time} | "
            "8:30 PM market refresh pending"
        )

    elif (
        status
        == WAITING_FOR_LATE_NIGHT_REFRESH
        and preview.market_snapshot_role
        == "evening"
    ):
        headline = (
            "EVENING PREVIEW - CURRENT"
        )

        opening_time = (
            _format_start(
                preview.opening_market_snapshot_time
            )
            if preview.opening_market_snapshot_time
            else "Unavailable"
        )

        detail = (
            f"Model generated {prediction_time} | "
            f"Opening market {opening_time} | "
            f"Latest market {market_time} | "
            "11 PM refresh pending"
        )

    elif (
        preview.market_snapshot_role
        == "late_night"
        and status == CURRENT
    ):
        headline = (
            "LATE-NIGHT PREVIEW - CURRENT"
        )

        opening_time = (
            _format_start(
                preview.opening_market_snapshot_time
            )
            if preview.opening_market_snapshot_time
            else "Unavailable"
        )

        detail = (
            f"Model generated {prediction_time} | "
            f"Opening market {opening_time} | "
            f"Latest market {market_time}"
        )

    elif status == AUTOMATION_ATTENTION_NEEDED:
        if preview.market_snapshot_role == "opening":
            headline = (
                "OPENING PREVIEW - "
                "AUTOMATION ATTENTION NEEDED"
            )

            detail = (
                f"Model generated {prediction_time} | "
                f"Opening market captured {market_time} | "
                "8:30 PM market refresh is overdue"
            )

        elif preview.market_snapshot_role == "evening":
            headline = (
                "EVENING PREVIEW - "
                "AUTOMATION ATTENTION NEEDED"
            )

            detail = (
                f"Model generated {prediction_time} | "
                f"Latest market {market_time} | "
                "11 PM refresh is overdue"
            )

        else:
            headline = (
                "TOMORROW PREVIEW - "
                "AUTOMATION ATTENTION NEEDED"
            )

            detail = (
                f"Model generated {prediction_time} | "
                f"Market captured {market_time}"
            )

    else:
        headline = (
            f"TOMORROW PREVIEW - {status}"
        )

        detail = (
            f"Model generated {prediction_time} | "
            f"Market captured {market_time}"
        )

    _render_status_message(
        status=status,
        headline=headline,
        detail=detail,
    )



def _render_today(
    target_date: date,
) -> None:
    st.subheader(
        f"Official Card - "
        f"{_format_date(target_date)}"
    )

    st.caption(
        "Official forward-validation card generated "
        "by the morning workflow."
    )

    slate = _find_latest_slate(
        target_date=target_date,
    )

    if slate is None:
        _render_missing_official_status(
            target_date
        )
        return

    games = _load_games(
        slate.prediction_run_id,
        slate.odds_ingestion_run_id,
        slate.policy_version,
    )

    _render_official_freshness_status(
        target_date=target_date,
        prediction_run_id=(
            slate.prediction_run_id
        ),
        odds_ingestion_run_id=(
            slate.odds_ingestion_run_id
        ),
    )

    candidates = get_candidate_games(
        games
    )

    left, right = st.columns(2)

    left.metric(
        "Games analyzed",
        len(games),
    )

    right.metric(
        "Official candidates",
        len(candidates),
    )

    st.caption(
        f"Official prediction run "
        f"{slate.prediction_run_id} | "
        f"Entry odds run "
        f"{slate.odds_ingestion_run_id}"
    )

    if candidates:
        st.markdown(
            "### Official value plays"
        )

        for game in sorted(
            candidates,
            key=lambda row: (
                row.model_expected_value
            ),
            reverse=True,
        ):
            _render_official_card(game)

    else:
        st.success(
            "No games cleared the official value "
            "policy. Passing is a valid model decision."
        )

    _render_overnight_review(
        target_date=target_date,
        official_games=games,
        official_prediction_run_id=(
            slate.prediction_run_id
        ),
        official_odds_run_id=(
            slate.odds_ingestion_run_id
        ),
    )

    with st.expander(
        "All model predictions",
        expanded=False,
    ):
        st.dataframe(
            _build_official_table(
                games
            ),
            hide_index=True,
            width="stretch",
        )



def _render_overnight_review(
    *,
    target_date: date,
    official_games,
    official_prediction_run_id: int,
    official_odds_run_id: int,
) -> None:
    try:
        preview = _load_preview(
            target_date
        )
    except Exception:
        return

    if (
        preview.market_snapshot_role
        != "late_night"
    ):
        return

    review = build_moneyline_overnight_review(
        late_night_games=preview.games,
        official_games=official_games,
    )

    if not review:
        return

    late_passes = sum(
        row.late_night_policy_pass
        for row in review
    )

    survived = sum(
        row.status == SURVIVED_TO_MORNING
        for row in review
    )

    lost = sum(
        row.status == VALUE_LOST_OVERNIGHT
        for row in review
    )

    new_morning = sum(
        row.status == NEW_MORNING_VALUE
        for row in review
    )

    st.markdown(
        "### Overnight Value Review"
    )

    st.caption(
        "11 PM preview compared with the "
        "8 AM official card. The morning card "
        "remains the official forward-validation "
        "record."
    )

    top_left, top_right = st.columns(2)

    top_left.metric(
        "11 PM passes",
        late_passes,
    )

    top_right.metric(
        "Survived to morning",
        survived,
    )

    lower_left, lower_right = st.columns(2)

    lower_left.metric(
        "Value lost overnight",
        lost,
    )

    lower_right.metric(
        "New morning value",
        new_morning,
    )

    st.caption(
        f"11 PM preview run "
        f"{preview.prediction_run_id} | "
        f"Late-night odds run "
        f"{preview.odds_ingestion_run_id} | "
        f"Official prediction run "
        f"{official_prediction_run_id} | "
        f"Entry odds run "
        f"{official_odds_run_id}"
    )

    interesting = tuple(
        row
        for row in review
        if row.status != NO_VALUE
    )

    for row in interesting:
        _render_overnight_review_card(
            row
        )

    with st.expander(
        "All overnight comparisons",
        expanded=False,
    ):
        st.dataframe(
            _build_overnight_review_table(
                review
            ),
            hide_index=True,
            width="stretch",
        )


def _render_overnight_review_card(
    row,
) -> None:
    with st.container(
        border=True
    ):
        st.markdown(
            f"**{row.status}**"
        )

        if row.selection_changed:
            st.markdown(
                f"### {row.away_team_name} at "
                f"{row.home_team_name}"
            )

            st.write(
                f"11 PM lean: "
                f"**{row.late_night_selection_name}** "
                f"| 8 AM lean: "
                f"**{row.official_selection_name}**"
            )

        else:
            st.markdown(
                f"### "
                f"{row.official_selection_name}"
            )

        late_fair = (
            probability_to_american_odds(
                row.late_night_model_probability
            )
        )

        official_fair = (
            probability_to_american_odds(
                row.official_model_probability
            )
        )

        late_result = (
            "PASS"
            if row.late_night_policy_pass
            else "NO PASS"
        )

        official_result = (
            "PASS"
            if row.official_policy_pass
            else "NO PASS"
        )

        st.markdown(
            "**11 PM Preview**"
        )

        st.write(
            f"Market "
            f"**{format_price(row.late_night_price)}** "
            f"| Model Fair "
            f"**{format_price(late_fair)}** "
            f"| Model "
            f"**{format_percent(row.late_night_model_probability)}**"
        )

        st.write(
            f"EV "
            f"**{format_percent(row.late_night_model_expected_value)}** "
            f"| Edge "
            f"**{format_points(row.late_night_model_market_edge)}** "
            f"| **{late_result}**"
        )

        st.caption(
            f"Best market: "
            f"{row.late_night_sportsbook_name}"
        )

        st.markdown(
            "**8 AM Official**"
        )

        st.write(
            f"Market "
            f"**{format_price(row.official_price)}** "
            f"| Model Fair "
            f"**{format_price(official_fair)}** "
            f"| Model "
            f"**{format_percent(row.official_model_probability)}**"
        )

        st.write(
            f"EV "
            f"**{format_percent(row.official_model_expected_value)}** "
            f"| Edge "
            f"**{format_points(row.official_model_market_edge)}** "
            f"| **{official_result}**"
        )

        st.caption(
            f"Best market: "
            f"{row.official_sportsbook_name}"
        )

        if (
            not row.official_policy_pass
            and row.official_disqualification_reasons
        ):
            st.caption(
                "Morning blockers: "
                + format_exclusion_reasons(
                    row.official_disqualification_reasons
                )
            )


def _build_overnight_review_table(
    review,
):
    rows = []

    for row in review:
        late_fair = (
            probability_to_american_odds(
                row.late_night_model_probability
            )
        )

        official_fair = (
            probability_to_american_odds(
                row.official_model_probability
            )
        )

        rows.append(
            {
                "Status": row.status,
                "Game": (
                    f"{row.away_team_name} at "
                    f"{row.home_team_name}"
                ),
                "11 PM pick": (
                    row.late_night_selection_name
                ),
                "11 PM market": (
                    format_price(
                        row.late_night_price
                    )
                ),
                "11 PM fair": (
                    format_price(late_fair)
                ),
                "11 PM EV": (
                    format_percent(
                        row
                        .late_night_model_expected_value
                    )
                ),
                "8 AM pick": (
                    row.official_selection_name
                ),
                "8 AM market": (
                    format_price(
                        row.official_price
                    )
                ),
                "8 AM fair": (
                    format_price(
                        official_fair
                    )
                ),
                "8 AM EV": (
                    format_percent(
                        row
                        .official_model_expected_value
                    )
                ),
                "Morning blockers": (
                    format_exclusion_reasons(
                        row
                        .official_disqualification_reasons
                    )
                    if (
                        row
                        .official_disqualification_reasons
                    )
                    else "-"
                ),
            }
        )

    return rows



def _render_tomorrow(
    target_date: date,
) -> None:
    st.subheader(
        f"Tomorrow Preview - "
        f"{_format_date(target_date)}"
    )

    st.warning(
        "PREVIEW ONLY - these are not official bets "
        "or forward-validation candidates. "
        "The slate is regenerated during the "
        "morning workflow."
    )

    try:
        preview = _load_preview(
            target_date
        )

        _render_preview_freshness_status(
            target_date=target_date,
            preview=preview,
        )

    except LookupError as error:
        _render_missing_preview_status(
            target_date=target_date,
            message=str(error),
        )
        return

    except Exception as error:
        st.error(
            "Tomorrow Preview could not be loaded."
        )

        with st.expander(
            "Technical details",
            expanded=False,
        ):
            st.code(
                f"{type(error).__name__}: {error}"
            )

        return

    preview_passes = tuple(
        game
        for game in preview.games
        if game.preview_policy_pass
    )

    blocked_value = tuple(
        game
        for game in preview.games
        if (
            game.preview_value_signal
            and not game.preview_policy_pass
        )
    )

    top_left, top_right = st.columns(2)

    top_left.metric(
        "Games on slate",
        preview.predictions_loaded,
    )

    top_right.metric(
        "Market evaluable",
        len(preview.games),
    )

    lower_left, lower_right = st.columns(2)

    lower_left.metric(
        "Preview policy passes",
        len(preview_passes),
    )

    lower_right.metric(
        "Market unavailable",
        len(preview.unavailable_games),
    )

    st.caption(
        f"Model {preview.model_version} | "
        f"Preview run {preview.prediction_run_id} | "
        f"Latest preview-market odds run "
        f"{preview.odds_ingestion_run_id} | "
        f"Market captured "
        f"{_format_start(preview.market_snapshot_time)}"
    )

    if preview_passes:
        st.markdown(
            "### Preview policy passes"
        )

        for game in preview_passes:
            _render_preview_card(
                game,
                status=(
                    "PREVIEW POLICY PASS - "
                    "NOT OFFICIAL"
                ),
            )

    else:
        st.info(
            "No games currently clear every "
            "preview policy requirement."
        )

    if blocked_value:
        st.markdown(
            "### Value - policy blocked"
        )

        st.caption(
            "The model sees price value, but one or "
            "more safety requirements are not met."
        )

        for game in blocked_value:
            _render_preview_card(
                game,
                status="VALUE - POLICY BLOCKED",
            )

    with st.expander(
        "All market-evaluable predictions",
        expanded=False,
    ):
        st.dataframe(
            _build_preview_table(
                preview.games
            ),
            hide_index=True,
            width="stretch",
        )

    if preview.unavailable_games:
        with st.expander(
            "Preview market unavailable",
            expanded=False,
        ):
            for game in (
                preview.unavailable_games
            ):
                st.write(
                    f"**{game.away_team_name} at "
                    f"{game.home_team_name}**"
                )

                st.caption(
                    f"Model lean: "
                    f"{game.predicted_team_name} "
                    f"{format_percent(game.model_probability)} "
                    f"| Starters: "
                    f"{game.starter_coverage.title()} "
                    f"| Missing values: "
                    f"{game.missing_raw_value_count}"
                )

                st.caption(
                    game.reason
                )


def _render_results() -> None:
    st.subheader(
        "Forward-Validation Results"
    )

    slates = _latest_slate_per_date(
        _load_slates()
    )

    if not slates:
        st.info(
            "No official Moneyline results "
            "are available yet."
        )
        return

    candidate_games = []

    for slate in slates[:30]:
        games = _load_games(
            slate.prediction_run_id,
            slate.odds_ingestion_run_id,
            slate.policy_version,
        )

        candidate_games.extend(
            get_candidate_games(games)
        )

    candidates = tuple(
        candidate_games
    )

    performance = (
        build_moneyline_live_performance(
            candidates
        )
    )

    settled_games = sorted(
        (
            game
            for game in candidates
            if (
                game.outcome is not None
                and game.profit_units is not None
            )
        ),
        key=lambda game: (
            game.game_start_time,
            game.game_id,
        ),
        reverse=True,
    )

    pending_games = tuple(
        game
        for game in candidates
        if game.outcome is None
    )

    record_left, record_right = (
        st.columns(2)
    )

    record_left.metric(
        "Record",
        (
            f"{performance.wins}-"
            f"{performance.losses}"
        ),
    )

    record_right.metric(
        "Settled plays",
        performance.settlements,
    )

    units_left, units_right = (
        st.columns(2)
    )

    units_left.metric(
        "Profit",
        format_units(
            performance.profit_units
        ),
    )

    units_right.metric(
        "ROI",
        format_percent(
            performance.roi
        ),
    )

    if settled_games:
        latest_date = (
            settled_games[0]
            .game_start_time
            .astimezone(
                PACIFIC_TIME_ZONE
            )
            .date()
        )

        st.caption(
            f"{performance.settlements} settled "
            f"official plays through "
            f"{_format_date(latest_date)} | "
            f"{len(pending_games)} pending"
        )
    else:
        st.caption(
            f"No settled official plays yet | "
            f"{len(pending_games)} pending"
        )

    if not settled_games:
        st.info(
            "Official candidates exist, but none "
            "are settled yet."
        )
        return

    st.markdown(
        "### Recent results"
    )

    for game in settled_games[:10]:
        _render_result_card(game)


def _render_official_card(
    game,
) -> None:
    with st.container(
        border=True
    ):
        if game.outcome is None:
            status = "OFFICIAL VALUE"
        else:
            status = (
                f"{game.outcome.upper()} - "
                "OFFICIAL VALUE"
            )

        st.markdown(
            f"**{status}**"
        )

        st.markdown(
            f"### {game.predicted_team_name}"
        )

        model_fair_price = (
            probability_to_american_odds(
                game.model_probability
            )
        )

        st.write(
            f"Best Market Price "
            f"**{format_price(game.price)}** "
            f"| Model Fair Price "
            f"**{format_price(model_fair_price)}**"
        )

        st.caption(
            f"{game.away_team_name} at "
            f"{game.home_team_name} | "
            f"{_format_start(game.game_start_time)}"
        )

        st.write(
            f"Model "
            f"**{format_percent(game.model_probability)}** "
            f"| Market "
            f"**{format_percent(game.market_no_vig_probability)}**"
        )

        st.write(
            f"Edge "
            f"**{format_points(game.model_market_edge)}** "
            f"| EV "
            f"**{format_percent(game.model_expected_value)}**"
        )

        st.caption(
            f"Best price: {game.sportsbook_name} | "
            f"Starters: "
            f"{game.starter_coverage.title()} | "
            f"Missing values: "
            f"{game.missing_raw_value_count}"
        )


def _render_preview_card(
    game,
    *,
    status: str,
) -> None:
    with st.container(
        border=True
    ):
        st.markdown(
            f"**{status}**"
        )

        st.markdown(
            f"### {game.predicted_team_name}"
        )

        model_fair_price = (
            probability_to_american_odds(
                game.model_probability
            )
        )

        st.write(
            f"Best Market Price "
            f"**{format_price(game.price)}** "
            f"| Model Fair Price "
            f"**{format_price(model_fair_price)}**"
        )

        st.caption(
            f"{game.away_team_name} at "
            f"{game.home_team_name} | "
            f"{_format_start(game.game_start_time)}"
        )

        st.write(
            f"Model "
            f"**{format_percent(game.model_probability)}** "
            f"| Market "
            f"**{format_percent(game.market_no_vig_probability)}**"
        )

        st.write(
            f"Edge "
            f"**{format_points(game.model_market_edge)}** "
            f"| Price edge "
            f"**{format_points(game.model_price_edge)}**"
        )

        st.write(
            f"Model EV "
            f"**{format_percent(game.model_expected_value)}**"
        )

        st.caption(
            f"Best market: {game.sportsbook_name} | "
            f"Books: {game.sportsbook_count} | "
            f"Starters: "
            f"{game.starter_coverage.title()} | "
            f"Missing values: "
            f"{game.missing_raw_value_count}"
        )

        if game.movement_status == "OPENING ONLY":
            st.caption(
                "Opening market only | "
                "8:30 PM market comparison pending."
            )
        else:
            st.markdown(
                f"**Movement: "
                f"{game.movement_status}**"
            )

            if game.opening_price is not None:
                opening_result = (
                    "PASS"
                    if game.opening_policy_pass
                    else "NO PASS"
                )

                st.caption(
                    f"Opening: "
                    f"{format_price(game.opening_price)} "
                    f"| EV "
                    f"{format_percent(game.opening_model_expected_value)} "
                    f"| Edge "
                    f"{format_points(game.opening_model_market_edge)} "
                    f"| {opening_result}"
                )

                current_result = (
                    "PASS"
                    if game.preview_policy_pass
                    else "NO PASS"
                )

                st.caption(
                    f"Latest: "
                    f"{format_price(game.price)} "
                    f"| EV "
                    f"{format_percent(game.model_expected_value)} "
                    f"| Edge "
                    f"{format_points(game.model_market_edge)} "
                    f"| {current_result}"
                )

        if (
            not game.preview_policy_pass
            and game.disqualification_reasons
        ):
            st.caption(
                "Blocked: "
                + format_exclusion_reasons(
                    game.disqualification_reasons
                )
            )


def _render_result_card(
    game,
) -> None:
    with st.container(
        border=True
    ):
        game_date = (
            game.game_start_time
            .astimezone(
                PACIFIC_TIME_ZONE
            )
            .date()
        )

        st.markdown(
            f"**{game.outcome.upper()} - "
            f"{_format_date(game_date)}**"
        )

        st.markdown(
            f"### {game.predicted_team_name} "
            f"{format_price(game.price)}"
        )

        st.caption(
            f"{game.away_team_name} at "
            f"{game.home_team_name} | "
            f"{_format_start(game.game_start_time)}"
        )

        if (
            game.away_score is not None
            and game.home_score is not None
        ):
            st.write(
                f"Final: {game.away_team_name} "
                f"{game.away_score}, "
                f"{game.home_team_name} "
                f"{game.home_score}"
            )

        st.write(
            f"EV "
            f"{format_percent(game.model_expected_value)} "
            f"| Profit "
            f"{format_units(game.profit_units)}"
        )


def _find_latest_slate(
    *,
    target_date: date,
):
    for slate in _load_slates():
        if (
            slate.target_date
            == target_date
            and slate.run_type == "official"
            and slate.snapshot_role == "entry"
        ):
            return slate

    return None


def _latest_slate_per_date(
    slates,
):
    selected = []
    seen_dates = set()

    for slate in slates:
        if (
            slate.run_type != "official"
            or slate.snapshot_role != "entry"
        ):
            continue

        if slate.target_date in seen_dates:
            continue

        seen_dates.add(
            slate.target_date
        )

        selected.append(
            slate
        )

    return tuple(
        selected
    )


def _build_official_table(
    games,
):
    return [
        {
            "Game": (
                f"{game.away_team_name} at "
                f"{game.home_team_name}"
            ),
            "Start": _format_start(
                game.game_start_time
            ),
            "Model pick": (
                game.predicted_team_name
            ),
            "Model": format_percent(
                game.model_probability
            ),
            "Market": format_percent(
                game.market_no_vig_probability
            ),
            "Edge": format_points(
                game.model_market_edge
            ),
            "Best market": format_price(
                game.price
            ),
            "Model fair": format_price(
                probability_to_american_odds(
                    game.model_probability
                )
            ),
            "EV": format_percent(
                game.model_expected_value
            ),
            "Official value": (
                "YES"
                if game.qualifies_as_paper_candidate
                else "NO"
            ),
        }
        for game in games
    ]


def _build_preview_table(
    games,
):
    rows = []

    for game in games:
        if game.preview_policy_pass:
            status = "POLICY PASS"
        elif game.preview_value_signal:
            status = "VALUE - BLOCKED"
        else:
            status = "NO VALUE"

        rows.append(
            {
                "Game": (
                    f"{game.away_team_name} at "
                    f"{game.home_team_name}"
                ),
                "Start": _format_start(
                    game.game_start_time
                ),
                "Model pick": (
                    game.predicted_team_name
                ),
                "Model": format_percent(
                    game.model_probability
                ),
                "Market": format_percent(
                    game.market_no_vig_probability
                ),
                "Edge": format_points(
                    game.model_market_edge
                ),
                "Best market": format_price(
                    game.price
                ),
                "Model fair": format_price(
                    probability_to_american_odds(
                        game.model_probability
                    )
                ),
                "EV": format_percent(
                    game.model_expected_value
                ),
                "Status": status,
                "Movement": game.movement_status,
            }
        )

    return rows


def _format_start(
    value: datetime,
) -> str:
    pacific = value.astimezone(
        PACIFIC_TIME_ZONE
    )

    return (
        pacific.strftime(
            "%b %d %I:%M %p"
        )
        .replace(
            " 0",
            " ",
        )
        + " PT"
    )


def _format_date(
    value: date,
) -> str:
    return (
        value.strftime(
            "%A, %b %d, %Y"
        )
        .replace(
            " 0",
            " ",
        )
    )
