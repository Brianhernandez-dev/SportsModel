from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sportsmodel.backtesting.backtest import (
    run_backtest,
)
from sportsmodel.models import (
    BetOutcome,
    SettledBet,
)


BASE_TIME = datetime(
    2026,
    7,
    10,
    18,
    0,
    tzinfo=timezone.utc,
)


def make_bet(
    *,
    outcome: BetOutcome,
    profit_units: str,
    expected_value: str = "0.04",
    hour_offset: int = 0,
) -> SettledBet:
    return SettledBet(
        odds_market_snapshot_id=hour_offset + 1,
        game_id=hour_offset + 1,
        sportsbook_id=1,
        market_type="h2h",
        selection_name=f"Team {hour_offset}",
        line_value=None,
        bet_snapshot_time=(
            BASE_TIME
            + timedelta(hours=hour_offset)
        ),
        price=-110,
        consensus_probability=Decimal("0.55"),
        expected_value=Decimal(expected_value),
        outcome=outcome,
        profit_units=Decimal(profit_units),
    )


def test_empty_backtest_returns_zero_report():
    report = run_backtest([])

    assert report.total_bets == 0
    assert report.wins == 0
    assert report.losses == 0
    assert report.pushes == 0
    assert report.win_rate == Decimal("0")
    assert report.profit_units == Decimal("0")
    assert report.roi == Decimal("0")
    assert report.maximum_drawdown_units == Decimal("0")


def test_counts_outcomes():
    bets = [
        make_bet(
            outcome=BetOutcome.WIN,
            profit_units="1",
        ),
        make_bet(
            outcome=BetOutcome.LOSS,
            profit_units="-1",
            hour_offset=1,
        ),
        make_bet(
            outcome=BetOutcome.PUSH,
            profit_units="0",
            hour_offset=2,
        ),
    ]

    report = run_backtest(bets)

    assert report.total_bets == 3
    assert report.wins == 1
    assert report.losses == 1
    assert report.pushes == 1
    assert report.settled_decisions == 2


def test_win_rate_excludes_pushes():
    bets = [
        make_bet(
            outcome=BetOutcome.WIN,
            profit_units="1",
        ),
        make_bet(
            outcome=BetOutcome.LOSS,
            profit_units="-1",
            hour_offset=1,
        ),
        make_bet(
            outcome=BetOutcome.PUSH,
            profit_units="0",
            hour_offset=2,
        ),
    ]

    report = run_backtest(bets)

    assert report.win_rate == Decimal("0.5")


def test_profit_and_roi_use_flat_one_unit_stakes():
    bets = [
        make_bet(
            outcome=BetOutcome.WIN,
            profit_units="1.5",
        ),
        make_bet(
            outcome=BetOutcome.LOSS,
            profit_units="-1",
            hour_offset=1,
        ),
        make_bet(
            outcome=BetOutcome.PUSH,
            profit_units="0",
            hour_offset=2,
        ),
    ]

    report = run_backtest(bets)

    assert report.total_staked_units == Decimal("3")
    assert report.profit_units == Decimal("0.5")
    assert report.roi == (
        Decimal("0.5") / Decimal("3")
    )


def test_calculates_average_expected_value():
    bets = [
        make_bet(
            outcome=BetOutcome.WIN,
            profit_units="1",
            expected_value="0.02",
        ),
        make_bet(
            outcome=BetOutcome.LOSS,
            profit_units="-1",
            expected_value="0.04",
            hour_offset=1,
        ),
        make_bet(
            outcome=BetOutcome.WIN,
            profit_units="1",
            expected_value="0.06",
            hour_offset=2,
        ),
    ]

    report = run_backtest(bets)

    assert (
        report.average_expected_value
        == Decimal("0.04")
    )


def test_calculates_maximum_drawdown():
    bets = [
        make_bet(
            outcome=BetOutcome.WIN,
            profit_units="2",
            hour_offset=0,
        ),
        make_bet(
            outcome=BetOutcome.LOSS,
            profit_units="-1",
            hour_offset=1,
        ),
        make_bet(
            outcome=BetOutcome.LOSS,
            profit_units="-1",
            hour_offset=2,
        ),
        make_bet(
            outcome=BetOutcome.LOSS,
            profit_units="-1",
            hour_offset=3,
        ),
        make_bet(
            outcome=BetOutcome.WIN,
            profit_units="1",
            hour_offset=4,
        ),
    ]

    report = run_backtest(bets)

    assert (
        report.maximum_drawdown_units
        == Decimal("3")
    )


def test_backtest_sorts_bets_before_drawdown():
    bets = [
        make_bet(
            outcome=BetOutcome.LOSS,
            profit_units="-1",
            hour_offset=2,
        ),
        make_bet(
            outcome=BetOutcome.WIN,
            profit_units="2",
            hour_offset=0,
        ),
        make_bet(
            outcome=BetOutcome.LOSS,
            profit_units="-1",
            hour_offset=1,
        ),
    ]

    report = run_backtest(bets)

    assert (
        report.maximum_drawdown_units
        == Decimal("2")
    )
