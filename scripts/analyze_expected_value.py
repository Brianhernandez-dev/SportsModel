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

    print(f"Snapshots: {len(snapshots)}")
    print(f"Complete markets: {len(complete_markets)}")
    print(f"No-vig markets: {len(no_vig_markets)}")
    print(
        f"Expected value markets: "
        f"{len(expected_value_markets)}"
    )
    print()

    for market in expected_value_markets[:20]:
        print(market)


if __name__ == "__main__":
    main()