from collections.abc import Iterable
from decimal import Decimal

from sportsmodel.models import (
    BacktestReport,
    BetOutcome,
    SettledBet,
)


def run_backtest(
    settled_bets: Iterable[SettledBet],
) -> BacktestReport:
    """
    Calculate flat-stake performance from settled wagers.

    Every wager risks one unit. Pushes count as placed wagers and staked
    units but return the original stake, producing zero profit.

    Win rate excludes pushes because they are not decisions.
    ROI is profit divided by all units staked.
    """

    ordered_bets = sorted(
        settled_bets,
        key=lambda bet: (
            bet.bet_snapshot_time,
            bet.game_id,
            bet.sportsbook_id,
            bet.market_type,
            bet.selection_name,
        ),
    )

    total_bets = len(ordered_bets)

    wins = sum(
        bet.outcome is BetOutcome.WIN
        for bet in ordered_bets
    )
    losses = sum(
        bet.outcome is BetOutcome.LOSS
        for bet in ordered_bets
    )
    pushes = sum(
        bet.outcome is BetOutcome.PUSH
        for bet in ordered_bets
    )

    settled_decisions = wins + losses
    total_staked_units = Decimal(total_bets)

    profit_units = sum(
        (
            bet.profit_units
            for bet in ordered_bets
        ),
        start=Decimal("0"),
    )

    if settled_decisions:
        win_rate = (
            Decimal(wins)
            / Decimal(settled_decisions)
        )
    else:
        win_rate = Decimal("0")

    if total_staked_units:
        roi = profit_units / total_staked_units
    else:
        roi = Decimal("0")

    if total_bets:
        average_expected_value = (
            sum(
                (
                    bet.expected_value
                    for bet in ordered_bets
                ),
                start=Decimal("0"),
            )
            / Decimal(total_bets)
        )
    else:
        average_expected_value = Decimal("0")

    maximum_drawdown_units = _calculate_maximum_drawdown(
        ordered_bets
    )

    return BacktestReport(
        total_bets=total_bets,
        wins=wins,
        losses=losses,
        pushes=pushes,
        settled_decisions=settled_decisions,
        win_rate=win_rate,
        total_staked_units=total_staked_units,
        profit_units=profit_units,
        roi=roi,
        average_expected_value=average_expected_value,
        maximum_drawdown_units=maximum_drawdown_units,
    )


def _calculate_maximum_drawdown(
    settled_bets: list[SettledBet],
) -> Decimal:
    """
    Return the largest peak-to-trough decline in cumulative units.

    The result is represented as a positive number.
    """

    cumulative_profit = Decimal("0")
    peak_profit = Decimal("0")
    maximum_drawdown = Decimal("0")

    for bet in settled_bets:
        cumulative_profit += bet.profit_units

        if cumulative_profit > peak_profit:
            peak_profit = cumulative_profit

        current_drawdown = (
            peak_profit - cumulative_profit
        )

        if current_drawdown > maximum_drawdown:
            maximum_drawdown = current_drawdown

    return maximum_drawdown
