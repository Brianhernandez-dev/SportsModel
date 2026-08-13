from datetime import date, datetime, timezone
from decimal import Decimal

from sportsmodel.dashboard.moneyline_presenter import (
    build_all_prediction_table,
    build_candidate_table,
    calculate_average_candidate_edge,
    calculate_average_candidate_ev,
    format_exclusion_reasons,
    format_slate,
)
from sportsmodel.models.moneyline_live_dashboard import (
    MoneylineLiveGame,
    MoneylineLiveSlate,
)


GAME_TIME = datetime(
    2026,
    7,
    30,
    22,
    10,
    tzinfo=timezone.utc,
)


def test_formats_slate_with_entry_snapshot_context() -> None:
    slate = MoneylineLiveSlate(
        prediction_run_id=1,
        odds_ingestion_run_id=181,
        policy_version="1.0.0",
        target_date=date(2026, 7, 30),
        snapshot_role="entry",
        snapshot_started_at=GAME_TIME,
    )

    assert format_slate(slate) == (
        "2026-07-30 — Entry snapshot "
        "(Jul 30, 2026 10:10 PM UTC) — "
        "Prediction Run 1 / Odds Run 181 / "
        "Policy 1.0.0"
    )


def test_formats_known_exclusion_reasons() -> None:
    formatted = format_exclusion_reasons(
        (
            "model_expected_value_below_minimum",
            "incomplete_starter_coverage",
        )
    )

    assert formatted == (
        "Model EV below 3% minimum; "
        "Incomplete probable-starter coverage"
    )


def test_formats_unknown_exclusion_reason() -> None:
    formatted = format_exclusion_reasons(
        ("new_policy_requirement",)
    )

    assert formatted == (
        "New policy requirement"
    )


def test_calculates_candidate_averages() -> None:
    games = (
        _game(
            game_id=1,
            qualifies=True,
            expected_value=Decimal("0.12"),
            market_edge=Decimal("0.06"),
        ),
        _game(
            game_id=2,
            qualifies=True,
            expected_value=Decimal("0.04"),
            market_edge=Decimal("0.02"),
        ),
        _game(
            game_id=3,
            qualifies=False,
            expected_value=Decimal("0.50"),
            market_edge=Decimal("0.50"),
        ),
    )

    assert (
        calculate_average_candidate_ev(games)
        == Decimal("0.08")
    )

    assert (
        calculate_average_candidate_edge(games)
        == Decimal("0.04")
    )


def test_builds_compact_and_complete_tables() -> None:
    games = (
        _game(
            game_id=1,
            qualifies=True,
            expected_value=Decimal("0.12"),
            market_edge=Decimal("0.06"),
        ),
        _game(
            game_id=2,
            qualifies=False,
            expected_value=Decimal("-0.02"),
            market_edge=Decimal("-0.01"),
            reasons=(
                "model_expected_value_below_minimum",
            ),
        ),
    )

    candidate_rows = build_candidate_table(
        games
    )

    all_rows = build_all_prediction_table(
        games
    )

    assert len(candidate_rows) == 1
    assert candidate_rows[0]["Status"] == "PENDING"
    assert "Exclusion reasons" not in candidate_rows[0]

    assert len(all_rows) == 2
    assert (
        all_rows[1]["Exclusion reasons"]
        == "Model EV below 3% minimum"
    )


def _game(
    *,
    game_id: int,
    qualifies: bool,
    expected_value: Decimal,
    market_edge: Decimal,
    reasons: tuple[str, ...] = (),
) -> MoneylineLiveGame:
    return MoneylineLiveGame(
        game_id=game_id,
        game_start_time=GAME_TIME,
        away_team_name="Kansas City Royals",
        home_team_name="Minnesota Twins",
        predicted_team_name=(
            "Kansas City Royals"
        ),
        model_probability=Decimal("0.51"),
        starter_coverage="both",
        missing_raw_value_count=2,
        market_no_vig_probability=(
            Decimal("0.45")
        ),
        model_market_edge=market_edge,
        price=119,
        sportsbook_name="DraftKings",
        model_expected_value=expected_value,
        qualifies_as_paper_candidate=qualifies,
        disqualification_reasons=reasons,
        outcome=None,
        profit_units=None,
        home_score=None,
        away_score=None,
    )
