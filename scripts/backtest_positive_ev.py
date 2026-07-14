import argparse
from decimal import Decimal, InvalidOperation

from sportsmodel.analysis.expected_value import (
    calculate_expected_value_markets,
)
from sportsmodel.analysis.market_builder import (
    build_complete_markets,
)
from sportsmodel.analysis.no_vig import (
    calculate_no_vig_markets,
)
from sportsmodel.backtesting.backtest import run_backtest
from sportsmodel.database.repository import (
    get_game_results,
    get_market_snapshots,
)
from sportsmodel.settlement.settlement import (
    settle_bet_candidates,
)
from sportsmodel.strategies.positive_ev import (
    select_positive_ev_candidates,
)


DEFAULT_MINIMUM_EXPECTED_VALUE = Decimal("0.02")


def parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError(
            f"Invalid decimal value: {value}"
        ) from error

    if parsed < Decimal("-1"):
        raise argparse.ArgumentTypeError(
            "Minimum EV cannot be less than -1."
        )

    return parsed


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the positive-EV strategy against linked "
            "historical game results."
        )
    )

    parser.add_argument(
        "--min-ev",
        type=parse_decimal,
        default=DEFAULT_MINIMUM_EXPECTED_VALUE,
        help=(
            "Minimum expected value expressed as a decimal. "
            "Example: 0.02 means 2 percent."
        ),
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    minimum_expected_value = arguments.min_ev

    snapshots = get_market_snapshots()
    complete_markets = build_complete_markets(snapshots)
    no_vig_markets = calculate_no_vig_markets(
        complete_markets
    )
    expected_value_markets = (
        calculate_expected_value_markets(
            no_vig_markets
        )
    )

    candidates = select_positive_ev_candidates(
        expected_value_markets,
        minimum_expected_value=minimum_expected_value,
    )

    game_results = get_game_results()
    settled_bets = settle_bet_candidates(
        candidates,
        game_results,
    )

    report = run_backtest(settled_bets)

    unsettled_candidates = (
        len(candidates) - len(settled_bets)
    )

    print()
    print("=" * 58)
    print("SportsModel v1.1 - Positive EV Backtest")
    print("=" * 58)
    print()

    print(
        f"Market snapshots:          "
        f"{len(snapshots):>10}"
    )
    print(
        f"Complete markets:          "
        f"{len(complete_markets):>10}"
    )
    print(
        f"Expected value markets:    "
        f"{len(expected_value_markets):>10}"
    )
    print(
        f"Minimum expected value:    "
        f"{minimum_expected_value:>9.2%}"
    )
    print(
        f"Bet candidates:            "
        f"{len(candidates):>10}"
    )
    print(
        f"Settled bets:              "
        f"{len(settled_bets):>10}"
    )
    print(
        f"Unsettled candidates:      "
        f"{unsettled_candidates:>10}"
    )

    print()
    print("-" * 58)
    print("Performance")
    print("-" * 58)
    print()

    print(f"Wins:                      {report.wins:>10}")
    print(f"Losses:                    {report.losses:>10}")
    print(f"Pushes:                    {report.pushes:>10}")
    print(
        f"Win rate:                  "
        f"{report.win_rate:>9.2%}"
    )
    print(
        f"Units staked:              "
        f"{report.total_staked_units:>10.2f}"
    )
    print(
        f"Profit:                    "
        f"{report.profit_units:>+10.2f}"
    )
    print(
        f"ROI:                       "
        f"{report.roi:>+9.2%}"
    )
    print(
        f"Average expected value:    "
        f"{report.average_expected_value:>9.2%}"
    )
    print(
        f"Maximum drawdown:          "
        f"{report.maximum_drawdown_units:>10.2f}"
    )

    print()
    print("=" * 58)

    if not candidates:
        print()
        print(
            "No selections met the configured minimum expected "
            "value threshold."
        )
        print(
            "Review the EV distribution before changing the "
            "strategy threshold."
        )
        print()

    elif not settled_bets:
        print()
        print(
            "Candidates were generated, but none could be settled "
            "with the currently linked final results."
        )
        print(
            "The stored odds may belong to unfinished games or "
            "games without linked historical results."
        )
        print()


if __name__ == "__main__":
    main()
