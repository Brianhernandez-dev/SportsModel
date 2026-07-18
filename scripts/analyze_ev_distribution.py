from decimal import Decimal
from statistics import median

from sportsmodel.analysis.expected_value import (
    calculate_expected_value_markets,
)
from sportsmodel.analysis.market_builder import (
    build_complete_markets,
)
from sportsmodel.analysis.no_vig import (
    calculate_no_vig_markets,
)
from sportsmodel.database.repository import (
    get_market_snapshots,
)


THRESHOLDS = (
    Decimal("0"),
    Decimal("0.005"),
    Decimal("0.01"),
    Decimal("0.02"),
    Decimal("0.03"),
    Decimal("0.05"),
)


def main() -> None:
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

    selections = [
        selection
        for market in expected_value_markets
        for selection in market.selections
    ]

    ordered = sorted(
        selections,
        key=lambda selection: selection.expected_value,
        reverse=True,
    )

    print()
    print("=" * 62)
    print("SportsModel EV Distribution")
    print("=" * 62)
    print()

    print(f"Snapshots:                {len(snapshots):>10}")
    print(f"Complete markets:         {len(complete_markets):>10}")
    print(f"EV markets:               {len(expected_value_markets):>10}")
    print(f"EV selections:            {len(selections):>10}")

    if not selections:
        print()
        print("No EV selections were generated.")
        return

    values = [
        selection.expected_value
        for selection in selections
    ]

    mean_ev = sum(
        values,
        start=Decimal("0"),
    ) / Decimal(len(values))

    median_ev = median(values)

    print()
    print("-" * 62)
    print("Distribution")
    print("-" * 62)
    print()

    print(f"Maximum EV:               {max(values):>10.4%}")
    print(f"Minimum EV:               {min(values):>10.4%}")
    print(f"Mean EV:                  {mean_ev:>10.4%}")
    print(f"Median EV:                {median_ev:>10.4%}")

    print()
    print("-" * 62)
    print("Threshold Counts")
    print("-" * 62)
    print()

    for threshold in THRESHOLDS:
        count = sum(
            value >= threshold
            for value in values
        )

        print(
            f"EV >= {threshold:>6.2%}:"
            f"{count:>12}"
        )

    print()
    print("-" * 62)
    print("Top 25 Selections")
    print("-" * 62)
    print()

    for index, selection in enumerate(
        ordered[:25],
        start=1,
    ):
        print(
            f"{index:>2}. "
            f"{selection.selection_name:<28} "
            f"price={selection.price:>+5d} "
            f"consensus="
            f"{selection.consensus_probability:>8.4%} "
            f"EV={selection.expected_value:>9.4%}"
        )

    print()
    print("=" * 62)


if __name__ == "__main__":
    main()
